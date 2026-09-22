from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from chat.retrieval.domain.evidence import DomainStatus, EvidenceBase
from chat.retrieval.domain.project_entries import (
    ProjectEntry,
    entry_from_dto,
    filters_summary,
    render_project_entries,
)

DISCOVERY_OPERATION = "get_project_search"
DISCOVERY_PROVENANCE = "ProjectSearchService.search_projects"

_DEFAULT_EXPIRING_DAYS = 14
_RESULT_LIMIT = 8


def _attr(obj: Any, name: str) -> Any:
    """Read a field off a DTO/ORM object or mapping; None when absent."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


@dataclass(frozen=True)
class ProjectSearchEvidence(EvidenceBase):
    """Permission-filtered project search results for discovery questions."""

    status: DomainStatus
    user_id: int
    operation: str = DISCOVERY_OPERATION
    filters: Tuple[Tuple[str, str], ...] = ()
    total_matches: Optional[int] = None
    projects: Tuple[ProjectEntry, ...] = ()
    provenance: str = DISCOVERY_PROVENANCE

    _CONTEXT_FIELD = "user_id"
    _CITATION_SCOPE = "global"
    _CITATION_KIND = "projects"
    _CITATION_TITLE = "Tasking Manager project search"
    _CITATION_HEADING = "project_search"
    _CITATION_SOURCE = {
        "path": "backend/services/project_search_service.py",
        "symbol": "ProjectSearchService.search_projects",
    }
    _CITATION_ID_TEMPLATE = "tm:global:{kind}"
    _CITATION_DOC_TEMPLATE = "tasking_manager:global"

    def _scope_id(self) -> Any:
        return "tm"

    def _body_lines(self) -> List[str]:
        lines: List[str] = []
        summary = filters_summary(dict(self.filters))
        if summary:
            lines.append(f"filters: {summary}")
        lines.append(
            f"matching_projects_total: "
            f"{self.total_matches if self.total_matches is not None else 0}"
        )
        if self.projects:
            lines.append("projects:")
            lines.extend(render_project_entries(self.projects, limit=_RESULT_LIMIT))
        else:
            lines.append("projects: none matched these filters")
        return lines


_LEVEL_TO_DIFFICULTY = {
    "BEGINNER": "EASY",
    "INTERMEDIATE": "MODERATE",
    "ADVANCED": "CHALLENGING",
}


async def _resolve_country(text: str, db: Any) -> Optional[str]:
    """Map free text to a canonical project country name, else None."""
    try:
        from backend.services.tags_service import TagsService

        countries = await TagsService.get_all_countries(db)
    except Exception:
        logger.exception("country list lookup failed")
        return None
    rows = _attr(countries, "tags") or countries
    wanted = text.strip().lower()
    if not wanted:
        return None
    try:
        for country in rows or []:
            name = _attr(country, "name") or country
            if str(name).strip().lower() == wanted:
                return str(name)
    except TypeError:
        return None
    return None


async def _difficulty_for_user(user_id: int, db: Any) -> Optional[str]:
    """Map the asker's mapping level to a project difficulty name."""
    try:
        from backend.services.users.user_service import UserService

        level = await UserService.get_mapping_level(user_id, db)
        name = str(_attr(level, "name") or "").upper()
    except Exception:
        logger.exception(f"user {user_id} mapping level lookup failed")
        return None
    return _LEVEL_TO_DIFFICULTY.get(name)


def _expiring_days(filters: Dict[str, str]) -> int:
    raw = filters.get("expiring_days")
    try:
        days = int(raw) if raw else _DEFAULT_EXPIRING_DAYS
    except (TypeError, ValueError):
        days = _DEFAULT_EXPIRING_DAYS
    return max(1, min(days, 90))


def _build_search_dto(
    filters: Dict[str, str], country: Optional[str], difficulty: Optional[str]
):
    from backend.models.dtos.project_dto import ProjectSearchDTO

    search = ProjectSearchDTO(
        preferred_locale="en",
        page=1,
        omit_map_results=True,
        country=country,
        organisation_name=filters.get("organisation") or None,
        campaign=filters.get("campaign") or None,
        difficulty=difficulty,
        text_search=filters.get("text_search") or None,
        action=filters.get("action") or None,
    )
    if filters.get("expiring_days"):
        days = _expiring_days(filters)
        search.due_date_lte = (
            datetime.date.today() + datetime.timedelta(days=days)
        ).isoformat()
        search.order_by = "due_date"
        search.order_by_type = "ASC"
    if filters.get("short_on_mappers"):
        search.action = "map"
        search.order_by = "percent_mapped"
        search.order_by_type = "ASC"
    return search


async def _run_search(search: Any, user: Any, db: Any):
    from backend.services.project_search_service import ProjectSearchService

    try:
        return await ProjectSearchService.search_projects(search, user, db)
    except Exception as exc:
        from backend.exceptions import NotFound

        if isinstance(exc, NotFound):
            return None
        raise


async def get_project_search_evidence(
    user_id: int, project_id: Any, db: Any, filters: Optional[Dict[str, str]] = None
) -> ProjectSearchEvidence:
    """Read-only, permission-filtered project discovery for the asker."""
    filters = {k: v for k, v in (filters or {}).items() if v}
    try:
        from backend.models.postgis.user import User as UserModel

        country = None
        if filters.get("country"):
            country = await _resolve_country(filters["country"], db)

        difficulty = filters.get("difficulty") or None
        if filters.get("based_on_skill") and not difficulty:
            difficulty = await _difficulty_for_user(user_id, db)

        user = await UserModel.get_by_id(user_id, db)
        search = _build_search_dto(filters, country, difficulty)
        results = await _run_search(search, user, db)

        # Exact org/campaign names may miss; fall back to a text search once.
        if results is None and not search.text_search:
            fallback_text = (
                filters.get("organisation")
                or filters.get("campaign")
                or (filters.get("country") if not country else None)
            )
            if fallback_text:
                fallback_filters = dict(filters)
                fallback_filters.pop("organisation", None)
                fallback_filters.pop("campaign", None)
                fallback_filters["text_search"] = fallback_text
                search = _build_search_dto(fallback_filters, None, difficulty)
                results = await _run_search(search, user, db)

        pagination = _attr(results, "pagination") if results is not None else None
        total = _attr(pagination, "total")
        if total is None and results is not None:
            total = len(_attr(results, "results") or [])

        entries = tuple(
            entry_from_dto(dto)
            for dto in (_attr(results, "results") or [])[:_RESULT_LIMIT]
        )

        return ProjectSearchEvidence(
            status="OK",
            user_id=user_id,
            filters=tuple(sorted(filters.items())),
            total_matches=int(total) if total is not None else 0,
            projects=entries,
        )
    except Exception:
        logger.exception(f"user {user_id} project search failed")
        return ProjectSearchEvidence(status="UNAVAILABLE", user_id=user_id)
