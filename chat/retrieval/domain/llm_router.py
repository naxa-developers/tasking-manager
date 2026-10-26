"""One structured LLM routing call with deterministic post-validation.

Intent is decided by the model. Application code owns the operation allowlist,
project-id grounding, filter allowlists, route derivation, and the KB fallback.
There is no regex intent router behind this.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Tuple

import litellm  # type: ignore
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from chat.retrieval.config import RouterConfig, get_router_config
from chat.retrieval.domain.countries import find_country
from chat.retrieval.domain.references import extract_project_ids
from chat.retrieval.project_context import latest_explicit_project_id

Route = Literal["KB", "DOMAIN", "BOTH"]

MAX_OPERATIONS = 4
# Prior turns (one user + one assistant message each) sent to the router.
MAX_HISTORY_TURNS = 2
MAX_QUESTION_CHARS = 2000

OP_NAMES: Tuple[str, ...] = (
    "stats",
    "summary",
    "teams",
    "chat",
    "project_activity",
    "project_annotations",
    "project_contributions",
    "project_tasks",
    "similar_projects",
    "campaigns",
    "organisation_info",
    "team_detail",
    "user_interests",
    "user_osm_stats",
    "notifications",
    "project_partners",
    "featured_projects",
    "active_projects",
    "mywork",
    "user_profile",
    "user_contributions",
    "user_projects_created",
    "user_org_projects",
    "user_activity",
    "user_teams",
    "user_tasks",
    "favorites",
    "global_stats",
    "project_search",
    "trending_projects",
    "user_recommendations",
)

OP_INSTRUCTIONS: Dict[str, str] = {
    "stats": "Task counts for one project.",
    "summary": "One project's status, difficulty, organisation, progress, dates.",
    "teams": "Teams or members on one project.",
    "chat": "Recent discussion or comments on one project.",
    "project_activity": "Latest task activity on one project.",
    "project_contributions": "Contributors or daily activity for one project.",
    "project_tasks": "Invalidated tasks or mapping by user on one project.",
    "project_annotations": "Flagged task issues on one project.",
    "similar_projects": "Projects similar to one project.",
    "campaigns": "Campaigns on a project, or site campaigns.",
    "organisation_info": "One named organisation's profile, projects, campaigns.",
    "team_detail": "One team by number: details or members.",
    "user_interests": "The asker's mapping interest mix.",
    "user_osm_stats": "The asker's OSM account age or changeset count.",
    "notifications": "The asker's notifications.",
    "project_partners": "Partners on one project.",
    "featured_projects": "Site featured projects.",
    "active_projects": "Recently active projects.",
    "mywork": "The asker's own locked or assigned tasks.",
    "user_profile": "The asker's mapper level or badges.",
    "user_contributions": "The asker's contribution totals: tasks mapped, projects worked on, or hours.",
    "user_projects_created": "Projects the asker personally created.",
    "user_org_projects": "Projects run by the asker's organisation.",
    "user_activity": "The asker's streak or mapping/validation split.",
    "user_teams": "Teams the asker belongs to.",
    "user_tasks": "Whether the asker's own submitted tasks have been validated.",
    "favorites": "The asker's saved/favorite projects.",
    "global_stats": "Site-wide totals: how many users, projects, or tasks exist overall.",
    "project_search": "Find projects by country, difficulty, organisation, campaign, expiry, mappers, or needing validation.",
    "trending_projects": "Most active or popular projects now.",
    "user_recommendations": "Project recommendation for the asker.",
}

# Operations that cannot run without one project id.
PROJECT_OPS: Tuple[str, ...] = (
    "stats",
    "summary",
    "teams",
    "chat",
    "project_activity",
    "project_annotations",
    "project_contributions",
    "project_tasks",
    "similar_projects",
    "project_partners",
)

# Operations that may use a project id when one is grounded, but can run
# without it (global campaigns, the asker's favorites, their submitted tasks).
OPTIONAL_PROJECT_OPS: Tuple[str, ...] = ("campaigns", "favorites", "user_tasks")

# Filter-aware operations and their required keys.
FILTER_OPS: Tuple[str, ...] = ("project_search", "organisation_info", "team_detail")
REQUIRED_FILTERS: Dict[str, Tuple[str, ...]] = {
    "organisation_info": ("organisation",),
    "team_detail": ("team_id",),
}

ALLOWED_FILTERS = frozenset(
    (
        "difficulty",
        "based_on_skill",
        "expiring_days",
        "short_on_mappers",
        "text_search",
        "action",
        "country",
        "organisation",
        "campaign",
        "team_id",
    )
)

_DIFFICULTY_SYNONYMS = {
    "beginner": "EASY",
    "easy": "EASY",
    "beginner-friendly": "EASY",
    "intermediate": "MODERATE",
    "moderate": "MODERATE",
    "advanced": "CHALLENGING",
    "challenging": "CHALLENGING",
    "hard": "CHALLENGING",
}

_OP_LINES = "\n".join(f"- {name}: {OP_INSTRUCTIONS[name]}" for name in OP_NAMES)

ROUTER_SYSTEM_PROMPT = f"""You are the Tasking Manager routing assistant.
Decide which live operations and/or documentation the answer needs. Return one
JSON object only; never answer the question.

JSON shape:
{{"ops": ["<operation>"], "project_id": <integer or null>, "filters": {{<string: string>}}, "needs_docs": <true|false>}}

Rules:
- Use only operation names from the catalogue below.
- Live data goes in "ops". Documentation-only questions use "ops": [] and
  "needs_docs": true.
- Set "needs_docs": true when the answer needs an explanation, definition, or
  procedure, including questions that also need live data.
- "project_id" must be an integer named in the current question or recent
  history. Never invent an id. If no project is named, still return project
  operations with a null id and the application will ask which project.
- If the question names two different projects, use a null id.
- "filters" is only for project_search, organisation_info, and team_detail.
  Allowed keys: difficulty (EASY|MODERATE|CHALLENGING), based_on_skill ("true"),
  expiring_days (a positive integer string), short_on_mappers ("true"),
  text_search, action (map|validate), country (canonical English country name),
  organisation, campaign, team_id (a positive integer string).
  organisation_info requires "organisation"; team_detail requires "team_id".
- Never include user identity, permissions, or account ids.
- These operations need a project id: {", ".join(PROJECT_OPS)}.

Catalogue:
{_OP_LINES}

/no_think
"""


class RouterOutput(BaseModel):
    """The tolerant shape we accept from the model before validation."""

    model_config = ConfigDict(extra="ignore")

    ops: list[Any] = Field(default_factory=list)
    project_id: Any = None
    filters: Dict[Any, Any] = Field(default_factory=dict)
    needs_docs: Any = False


@dataclass(frozen=True)
class DomainRoute:
    """Validated routing outcome consumed by the turn pipeline."""

    route: Route
    project_id: Optional[int] = None
    # Fixed domain operations in execution order; empty unless route is DOMAIN/BOTH.
    ops: tuple = ()
    # True when a project-scoped intent has no single resolvable project id.
    needs_project_id: bool = False
    # Allowlisted search filters for filter-aware ops.
    filters: dict = field(default_factory=dict)


def _coerce_project_id(value: Any) -> Optional[int]:
    """Positive integer project id from an int or numeric string, else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if not isinstance(value, str):
        return None
    text = value.strip().lstrip("#")
    if text.isdigit():
        project_id = int(text)
        return project_id if project_id > 0 else None
    match = re.search(r"\d{1,8}", text)
    if match is None:
        return None
    project_id = int(match.group(0))
    return project_id if project_id > 0 else None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "on"}


def _validate_ops(raw_ops: Any) -> list:
    """Known operation names in model order, deduplicated and capped."""
    if not isinstance(raw_ops, list):
        return []
    ops = []
    for raw in raw_ops:
        if not isinstance(raw, str):
            continue
        name = raw.strip().lower()
        if name in OP_INSTRUCTIONS and name not in ops:
            ops.append(name)
    return ops[:MAX_OPERATIONS]


def _validate_filters(raw_filters: Any) -> dict:
    """Allowlisted filters with normalized values; invalid entries are dropped."""
    if not isinstance(raw_filters, dict):
        return {}
    filters = {}
    for raw_key, raw_value in raw_filters.items():
        key = str(raw_key).strip().lower()
        if key not in ALLOWED_FILTERS:
            continue
        if key == "difficulty":
            value = _DIFFICULTY_SYNONYMS.get(str(raw_value).strip().lower())
            if value is not None:
                filters[key] = value
        elif key in ("based_on_skill", "short_on_mappers"):
            if _as_bool(raw_value):
                filters[key] = "true"
        elif key == "expiring_days":
            try:
                days = int(str(raw_value).strip())
            except (TypeError, ValueError):
                continue
            if 1 <= days <= 365:
                filters[key] = str(days)
        elif key == "action":
            value = str(raw_value).strip().lower()
            if value in ("map", "validate"):
                filters[key] = value
        elif key == "country":
            value = str(raw_value).strip()
            if not value:
                continue
            canonical = find_country(f"in {value}")
            if canonical is not None:
                filters[key] = canonical
        elif key == "team_id":
            try:
                team_id = int(str(raw_value).strip())
            except (TypeError, ValueError):
                continue
            if team_id > 0:
                filters[key] = str(team_id)
        else:
            value = str(raw_value).strip()
            if value and len(value) <= 160:
                filters[key] = value
    return filters


def _has_required_filters(op: str, filters: dict) -> bool:
    required = REQUIRED_FILTERS.get(op, ())
    return all(key in filters for key in required)


def _latest_history_project_id(history) -> Optional[int]:
    try:
        return latest_explicit_project_id(history)
    except Exception:
        return None


def _validate_output(
    output: RouterOutput,
    question: str,
    history,
) -> DomainRoute:
    """Turn the model payload into one validated route, never raising."""
    ops = _validate_ops(output.ops)
    filters = _validate_filters(output.filters)
    ops = [op for op in ops if _has_required_filters(op, filters)]
    if not set(ops) & set(FILTER_OPS):
        filters = {}
    if not ops:
        return DomainRoute(route="KB")

    question_ids = extract_project_ids(question)
    history_id = _latest_history_project_id(history)

    if len(question_ids) > 1:
        # Never guess which project a multi-project question means.
        grounded_id = None
        ambiguous = True
    elif question_ids:
        grounded_id = question_ids[0]
        ambiguous = False
    else:
        grounded_id = history_id
        ambiguous = False

    model_id = _coerce_project_id(output.project_id)
    # The model may echo a grounded id, but it can never introduce one.
    if model_id is not None and model_id not in {grounded_id, history_id}:
        model_id = None
    project_id = grounded_id if grounded_id is not None else model_id

    needs_project = bool(set(ops) & set(PROJECT_OPS))
    if needs_project and project_id is None:
        return DomainRoute(
            route="KB",
            ops=tuple(ops),
            needs_project_id=True,
        )
    if ambiguous and needs_project:
        return DomainRoute(
            route="KB",
            ops=tuple(ops),
            needs_project_id=True,
        )
    if ambiguous:
        project_id = None

    # Public/personal operations do not need a project scope.
    if not set(ops) & (set(PROJECT_OPS) | set(OPTIONAL_PROJECT_OPS)):
        project_id = None

    route = "BOTH" if _as_bool(output.needs_docs) else "DOMAIN"
    return DomainRoute(
        route=route,
        project_id=project_id,
        ops=tuple(ops),
        filters=filters,
    )


@lru_cache(maxsize=1)
def _examples() -> tuple:
    """Packaged few-shot examples as (question, validated route) pairs."""
    path = Path(__file__).with_name("router_examples.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("router examples must be a JSON array")
    examples = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("router example must be an object")
        question = str(item.get("question") or "").strip()
        route = RouterOutput.model_validate(item.get("route") or {})
        if question:
            examples.append((question, route))
    return tuple(examples)


def _last_turns(history, max_turns: int) -> list:
    """Return the last ``max_turns`` complete turns, oldest first.

    A turn starts at a user message and includes the following assistant
    messages. A trailing user-only message is kept as an incomplete turn.
    """
    turns: list = []
    current: list = []
    for message in history or []:
        if message.get("role") == "user" and current:
            turns.append(current)
            current = [message]
        else:
            current.append(message)
    if current:
        turns.append(current)
    return [m for turn in turns[-max_turns:] for m in turn]


def _build_messages(question: str, history) -> list:
    messages = [{"role": "system", "content": ROUTER_SYSTEM_PROMPT}]
    for example_question, example_route in _examples():
        messages.append({"role": "user", "content": example_question})
        messages.append(
            {"role": "assistant", "content": example_route.model_dump_json()}
        )
    for message in _last_turns(history, MAX_HISTORY_TURNS):
        role = str(message.get("role") or "")
        content = str(message.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question[:MAX_QUESTION_CHARS]})
    return messages


def _get(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _parse_content(response: Any) -> dict:
    """Extract the first JSON object from a chat-completions response."""
    choices = _get(response, "choices")
    if not choices:
        raise ValueError("router response has no choices")
    message = _get(choices[0], "message")
    content = _get(message, "content")
    if isinstance(content, dict):
        return content
    if not isinstance(content, str) or not content.strip():
        raise ValueError("router response content is empty")
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("router JSON must be an object")
    return payload


async def _complete(config: RouterConfig, messages: list) -> Any:
    kwargs = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "timeout": config.timeout,
        "num_retries": 0,
        "drop_params": True,
        "response_format": {"type": "json_object"},
    }
    if config.api_key:
        kwargs["api_key"] = config.api_key
    if config.api_base:
        kwargs["api_base"] = config.api_base
    if config.extra_body:
        kwargs["extra_body"] = dict(config.extra_body)
    return await litellm.acompletion(**kwargs)


async def route_question(
    question: str,
    *,
    history=None,
    config: Optional[RouterConfig] = None,
) -> DomainRoute:
    """Route one question with one model call; KB on any failure."""
    text = (question or "").strip()
    if not text:
        return DomainRoute(route="KB")
    try:
        selected = config or get_router_config()
        messages = _build_messages(text, history or [])
        response = await _complete(selected, messages)
        payload = _parse_content(response)
        output = RouterOutput.model_validate(payload)
        return _validate_output(output, text, history or [])
    except Exception as error:
        # Never log the question or prompt text: only the failure class.
        logger.warning("router fallback: {}", type(error).__name__)
        return DomainRoute(route="KB")
