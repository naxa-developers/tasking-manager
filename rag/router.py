"""The routing step: one LLM call that picks KB, DOMAIN, or BOTH.

Everything semantic is the model's decision — intent, which operations, which
project, which filters. This module owns only the contract:

* the JSON shape it asks for,
* the allowlist that validates the answer,
* the fallback when the answer cannot be executed.

Two deliberate non-decisions:

* **Project ids are not regex-grounded.** The model is told never to invent one,
  and the fetchers already run ``authorize_project``, so an invented id comes
  back as ``NOT_FOUND`` rather than as someone else's data.
* **No clarification branch.** If a project-scoped op arrives without a project,
  the op is dropped; generation asks the user which project they meant.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

import litellm  # type: ignore
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from rag.config import RouterConfig, get_router_config
from rag.domain.countries import find_country
from rag.domain.registry import (
    MAX_OPS_PER_TURN,
    OPS_BY_NAME,
    Op,
    prompt_catalogue,
)

Route = Literal["KB", "DOMAIN", "BOTH"]
_ROUTES = frozenset({"KB", "DOMAIN", "BOTH"})

MAX_HISTORY_TURNS = 3
MAX_QUESTION_CHARS = 2000

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

ROUTER_SYSTEM_PROMPT = f"""You are the routing step of a Tasking Manager assistant.
Decide how the question should be answered. Return one JSON object only, and
never answer the question yourself.

JSON shape:
{{"route": "KB" | "DOMAIN" | "BOTH",
  "ops": ["<operation>"],
  "project_id": <integer or null>,
  "filters": {{<string: string>}}}}

Routes:
- "KB": documentation answers it — an explanation, definition, or procedure.
- "DOMAIN": live Tasking Manager data answers it — counts, status, people,
  activity, the asker's own account data.
- "BOTH": it needs documentation and live data together.

Rules:
- "ops" lists operations from the catalogue below. Use [] for a KB route.
- Choose the smallest set of operations that answers the question.
- "project_id" is an integer only when the question or the conversation names
  one. Never invent an id. If the question is about a project but no project is
  named, still return the operations with a null id.
- If two different projects are named, use a null id.
- "filters" applies only to project_search, organisation_info, and team_detail.
  organisation_info requires "organisation"; team_detail requires "team_id".
- Never include user identity, permissions, or account ids.

Catalogue:
{prompt_catalogue()}

/no_think
"""


class RouterOutput(BaseModel):
    """The tolerant shape accepted from the model before validation."""

    model_config = ConfigDict(extra="ignore")

    route: Any = "KB"
    ops: List[Any] = Field(default_factory=list)
    project_id: Any = None
    filters: Dict[Any, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class RouteDecision:
    """A validated routing decision, ready for the pipeline."""

    route: Route = "KB"
    ops: Tuple[str, ...] = ()
    project_id: Optional[int] = None
    filters: Dict[str, str] = field(default_factory=dict)
    # True when the model asked for live data but nothing executable survived.
    degraded: bool = False

    @property
    def wants_domain(self) -> bool:
        return self.route in ("DOMAIN", "BOTH") and bool(self.ops)

    @property
    def wants_kb(self) -> bool:
        return self.route in ("KB", "BOTH")


def _coerce_project_id(value: Any) -> Optional[int]:
    """Positive integer project id from an int or numeric string, else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if not isinstance(value, str):
        return None
    match = re.search(r"\d{1,8}", value.strip().lstrip("#"))
    if match is None:
        return None
    project_id = int(match.group(0))
    return project_id if project_id > 0 else None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "on"}


def _normalize_route(value: Any) -> Route:
    text = str(value or "").strip().upper()
    return text if text in _ROUTES else "KB"  # type: ignore[return-value]


def _validate_ops(raw_ops: Any) -> Tuple[str, ...]:
    """Known op names in model order, deduplicated and capped."""
    if not isinstance(raw_ops, list):
        return ()
    ops: List[str] = []
    for raw in raw_ops:
        if not isinstance(raw, str):
            continue
        name = raw.strip().lower()
        if name in OPS_BY_NAME and name not in ops:
            ops.append(name)
    return tuple(ops[:MAX_OPS_PER_TURN])


def _allowed_keys(ops: Sequence[str]) -> frozenset:
    keys = set()
    for name in ops:
        keys.update(OPS_BY_NAME[name].allowlisted_filters)
    return frozenset(keys)


def _validate_filters(raw_filters: Any, ops: Sequence[str]) -> Dict[str, str]:
    """Allowlisted filters with normalized values; invalid entries are dropped."""
    if not isinstance(raw_filters, dict):
        return {}
    allowed = _allowed_keys(ops)
    filters: Dict[str, str] = {}
    for raw_key, raw_value in raw_filters.items():
        key = str(raw_key).strip().lower()
        if key not in allowed:
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


def _drop_unrunnable(
    ops: Sequence[str],
    project_id: Optional[int],
    filters: Dict[str, str],
) -> Tuple[str, ...]:
    """Keep only ops that can actually execute with what the model supplied."""
    kept: List[str] = []
    for name in ops:
        op: Op = OPS_BY_NAME[name]
        if op.needs_project_id and project_id is None:
            continue
        if any(key not in filters for key in op.required_filters):
            continue
        kept.append(name)
    return tuple(kept)


def _validate_output(output: RouterOutput) -> RouteDecision:
    """Turn the model payload into a decision that is safe to execute."""
    route = _normalize_route(output.route)
    ops = _validate_ops(output.ops)
    if route == "KB" or not ops:
        return RouteDecision(route="KB")

    project_id = _coerce_project_id(output.project_id)
    filters = _validate_filters(output.filters, ops)
    runnable = _drop_unrunnable(ops, project_id, filters)
    if not runnable:
        # The model asked for live data we cannot fetch — answer from docs and
        # let generation ask for the missing detail.
        return RouteDecision(route="KB", degraded=True)
    return RouteDecision(
        route=route,
        ops=runnable,
        project_id=project_id,
        filters=filters,
    )


def _last_turns(
    history: Sequence[Dict[str, str]], max_turns: int
) -> List[Dict[str, str]]:
    """The last ``max_turns`` complete turns, oldest first."""
    turns: List[List[Dict[str, str]]] = []
    current: List[Dict[str, str]] = []
    for message in history or []:
        if message.get("role") == "user" and current:
            turns.append(current)
            current = [message]
        else:
            current.append(message)
    if current:
        turns.append(current)
    kept = turns[-max_turns:] if max_turns > 0 else []
    return [message for turn in kept for message in turn]


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


def _build_messages(
    question: str, history: Sequence[Dict[str, str]]
) -> List[Dict[str, str]]:
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": ROUTER_SYSTEM_PROMPT}
    ]
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


def _parse_content(response: Any) -> Dict[str, Any]:
    """Extract the first JSON object from a chat-completions response."""
    choices = _get(response, "choices")
    if not choices:
        raise ValueError("router response has no choices")
    content = _get(_get(choices[0], "message"), "content")
    if isinstance(content, dict):
        return content
    if not isinstance(content, str) or not content.strip():
        raise ValueError("router response content is empty")
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("router JSON must be an object")
    return payload


async def _complete(config: RouterConfig, messages: List[Dict[str, str]]) -> Any:
    kwargs: Dict[str, Any] = {
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
    history: Optional[Sequence[Dict[str, str]]] = None,
    config: Optional[RouterConfig] = None,
) -> RouteDecision:
    """Route one question with one model call; KB on any failure."""
    text = (question or "").strip()
    if not text:
        return RouteDecision(route="KB")
    try:
        selected = config or get_router_config()
        response = await _complete(selected, _build_messages(text, history or []))
        output = RouterOutput.model_validate(_parse_content(response))
        return _validate_output(output)
    except Exception as error:
        # Never log the question or the prompt: only the failure class.
        logger.warning("router fallback: {}", type(error).__name__)
        return RouteDecision(route="KB")
