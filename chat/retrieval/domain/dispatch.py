from __future__ import annotations

import asyncio
import math
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from loguru import logger

from chat.retrieval.domain.routing import DomainRoute

Fetcher = Callable[[int, Optional[int], Any], Awaitable[Any]]

_DEFAULT_OP_TIMEOUT_SECONDS = 3.0
_MAX_OP_TIMEOUT_SECONDS = 30.0


def _op_timeout() -> float:
    """Per-op budget (``RAG_DOMAIN_TIMEOUT``) so one slow read can't stall chat."""
    raw = os.environ.get("RAG_DOMAIN_TIMEOUT", "")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return _DEFAULT_OP_TIMEOUT_SECONDS
    if not math.isfinite(value) or value <= 0:
        return _DEFAULT_OP_TIMEOUT_SECONDS
    return min(value, _MAX_OP_TIMEOUT_SECONDS)


@dataclass(frozen=True)
class DomainOutcome:
    """Merged result of a domain route: status, prompt block, citations."""

    status: Optional[str] = None
    block: str = ""
    citations: Tuple[Dict[str, Any], ...] = ()
    project_id: Optional[int] = None
    route: Optional[str] = None


def default_fetchers() -> Dict[str, Fetcher]:
    """Op registry: fixed read-only tools, each (user_id, project_id, db)."""
    # Fixed registry by design: the LLM can never invent an op.
    from chat.retrieval.domain.campaigns import get_campaigns_evidence
    from chat.retrieval.domain.global_stats import get_global_stats_evidence
    from chat.retrieval.domain.favorites import get_favorites_evidence
    from chat.retrieval.domain.mywork import get_mywork_evidence
    from chat.retrieval.domain.organisation_info import (
        get_organisation_info_evidence,
    )
    from chat.retrieval.domain.project_activity import get_project_activity_evidence
    from chat.retrieval.domain.project_annotations import (
        get_project_annotations_evidence,
    )
    from chat.retrieval.domain.project_chat import get_project_chat_evidence
    from chat.retrieval.domain.project_contributions import (
        get_project_contributions_evidence,
    )
    from chat.retrieval.domain.project_discovery import get_project_search_evidence
    from chat.retrieval.domain.project_tasks import get_project_tasks_evidence
    from chat.retrieval.domain.active_projects import get_active_projects_evidence
    from chat.retrieval.domain.featured_projects import (
        get_featured_projects_evidence,
    )
    from chat.retrieval.domain.notifications import get_notifications_evidence
    from chat.retrieval.domain.project_partners import (
        get_project_partners_evidence,
    )
    from chat.retrieval.domain.recommendations import (
        get_user_recommendation_evidence,
    )
    from chat.retrieval.domain.similar_projects import (
        get_similar_projects_evidence,
    )
    from chat.retrieval.domain.stats import (
        get_project_stats_evidence,
        get_project_summary_evidence,
    )
    from chat.retrieval.domain.team_detail import get_team_detail_evidence
    from chat.retrieval.domain.teams import get_project_teams_evidence
    from chat.retrieval.domain.trending import get_trending_projects_evidence
    from chat.retrieval.domain.user_activity import get_user_activity_evidence
    from chat.retrieval.domain.user_interests import get_user_interests_evidence
    from chat.retrieval.domain.user_osm_stats import get_user_osm_stats_evidence
    from chat.retrieval.domain.user_contributions import (
        get_user_contribution_evidence,
    )
    from chat.retrieval.domain.user_orgs import get_user_org_projects_evidence
    from chat.retrieval.domain.user_profile import get_user_profile_evidence
    from chat.retrieval.domain.user_projects import (
        get_user_projects_created_evidence,
    )
    from chat.retrieval.domain.user_tasks import get_user_tasks_evidence
    from chat.retrieval.domain.user_teams import get_user_teams_evidence

    return {
        "stats": get_project_stats_evidence,
        "summary": get_project_summary_evidence,
        "teams": get_project_teams_evidence,
        "chat": get_project_chat_evidence,
        "campaigns": get_campaigns_evidence,
        "organisation_info": get_organisation_info_evidence,
        "team_detail": get_team_detail_evidence,
        "favorites": get_favorites_evidence,
        "project_activity": get_project_activity_evidence,
        "project_annotations": get_project_annotations_evidence,
        "project_contributions": get_project_contributions_evidence,
        "project_tasks": get_project_tasks_evidence,
        "similar_projects": get_similar_projects_evidence,
        "project_partners": get_project_partners_evidence,
        "featured_projects": lambda user_id, project_id, db: (
            get_featured_projects_evidence(user_id, db)
        ),
        "active_projects": lambda user_id, project_id, db: (
            get_active_projects_evidence(user_id, db)
        ),
        "notifications": lambda user_id, project_id, db: (
            get_notifications_evidence(user_id, db)
        ),
        "user_interests": lambda user_id, project_id, db: (
            get_user_interests_evidence(user_id, db)
        ),
        "user_osm_stats": lambda user_id, project_id, db: (
            get_user_osm_stats_evidence(user_id, db)
        ),
        "mywork": lambda user_id, project_id, db: get_mywork_evidence(user_id, db),
        "user_profile": lambda user_id, project_id, db: get_user_profile_evidence(
            user_id, db
        ),
        "user_contributions": lambda user_id, project_id, db: (
            get_user_contribution_evidence(user_id, db)
        ),
        "user_projects_created": lambda user_id, project_id, db: (
            get_user_projects_created_evidence(user_id, db)
        ),
        "user_org_projects": lambda user_id, project_id, db: (
            get_user_org_projects_evidence(user_id, db)
        ),
        "user_activity": lambda user_id, project_id, db: get_user_activity_evidence(
            user_id, db
        ),
        "user_teams": lambda user_id, project_id, db: get_user_teams_evidence(
            user_id, db
        ),
        "user_tasks": lambda user_id, project_id, db: get_user_tasks_evidence(
            user_id, db
        ),
        "global_stats": lambda user_id, project_id, db: get_global_stats_evidence(
            user_id, db
        ),
        "project_search": get_project_search_evidence,
        "trending_projects": lambda user_id, project_id, db: (
            get_trending_projects_evidence(user_id, db)
        ),
        "user_recommendations": lambda user_id, project_id, db: (
            get_user_recommendation_evidence(user_id, db)
        ),
    }


# Ops whose fetchers accept the route's allowlisted filters as a 4th argument.
_FILTER_OPS = frozenset({"project_search", "organisation_info", "team_detail"})


def _record(statuses: List[str], op_statuses: List[str], op: str, status: str) -> None:
    """Append one op outcome to the merged and per-op status trails."""
    statuses.append(status)
    op_statuses.append(f"{op}:{status}")


def _merge_status(statuses: List[str]) -> Optional[str]:
    """Worst-case precedence across ops: OK > UNAUTHORIZED > TIMEOUT > ..."""
    if any(s == "OK" for s in statuses):
        return "OK"
    for status in ("UNAUTHORIZED", "TIMEOUT", "UNAVAILABLE"):
        if status in statuses:
            return status
    if statuses:
        return "NOT_FOUND"
    return None


async def _run_op(
    user_id: int,
    route: DomainRoute,
    op: str,
    fetcher: Fetcher,
    db: Any,
) -> tuple[str, str, Optional[Dict[str, Any]]]:
    """One op inside its timeout + render boundary; never raises."""
    try:
        if op in _FILTER_OPS:
            evidence = await asyncio.wait_for(
                fetcher(user_id, route.project_id, db, dict(route.filters or {})),
                timeout=_op_timeout(),
            )
        else:
            evidence = await asyncio.wait_for(
                fetcher(user_id, route.project_id, db), timeout=_op_timeout()
            )
        if evidence.authorized:
            # Rendering stays inside the per-op boundary: a broken renderer fails one op only.
            return evidence.status, evidence.to_prompt_block(), evidence.to_citation()
        return evidence.status, "", None
    except asyncio.TimeoutError:
        logger.warning(f"domain {op} fetch timed out after {_op_timeout():.1f}s")
        return "TIMEOUT", "", None
    except Exception:
        logger.exception(f"domain {op} fetch failed")
        return "UNAVAILABLE", "", None


async def collect_evidence(
    user_id: int,
    route: DomainRoute,
    db: Any,
    fetchers: Optional[Dict[str, Fetcher]] = None,
) -> DomainOutcome:
    """Execute a DOMAIN/BOTH route's ops, fail-soft, authorized evidence only."""
    ops = tuple(getattr(route, "ops", ()) or ())
    if not ops:
        return DomainOutcome(project_id=route.project_id, route=route.route)

    registry = fetchers if fetchers is not None else default_fetchers()
    blocks: List[str] = []
    statuses: List[str] = []
    citations: List[Dict[str, Any]] = []
    op_statuses: List[str] = []
    for op in ops:
        fetcher = registry.get(op)
        if fetcher is None:
            # Router/registry drift: never silent — status keeps the turn deterministic.
            logger.warning(f"domain op {op!r} is not registered; skipping")
            _record(statuses, op_statuses, op, "UNAVAILABLE")
            continue
        status, block, citation = await _run_op(user_id, route, op, fetcher, db)
        _record(statuses, op_statuses, op, status)
        if block:
            blocks.append(block)
        if citation is not None:
            citations.append(citation)

    merged = _merge_status(statuses)
    if op_statuses:
        logger.info(f"rag_domain ops={','.join(op_statuses)} status={merged}")
    return DomainOutcome(
        status=merged,
        block="\n\n".join(b for b in blocks if b),
        citations=tuple(citations),
        project_id=route.project_id,
        route=route.route,
    )
