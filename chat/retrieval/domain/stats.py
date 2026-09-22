from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from aiocache import SimpleMemoryCache
from loguru import logger

from chat.retrieval.domain.auth import (
    authorize_project,
    can_read_project,
)
from chat.retrieval.domain.evidence import DomainStatus, EvidenceBase, safe_value

OPERATION = "get_project_stats"
PROVENANCE = "Project.get_task_aggregates"

SUMMARY_OPERATION = "get_project_summary"
SUMMARY_PROVENANCE = "ProjectService.get_project_summary"

# Short-TTL aggregate cache; auth is checked before the cache on every request.
# Note: answers may lag live counts by up to the TTL (30s default);
# set RAG_STATS_CACHE_TTL=0 in tests to disable.
_STATS_CACHE_TTL_DEFAULT = 30.0
_STATS_CACHE = SimpleMemoryCache(namespace="rag_stats")


def _stats_cache_ttl() -> float:
    """Seconds to reuse live task aggregates (``RAG_STATS_CACHE_TTL``; 0 disables)."""
    raw = os.environ.get("RAG_STATS_CACHE_TTL", "")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return _STATS_CACHE_TTL_DEFAULT
    return value if value >= 0 else _STATS_CACHE_TTL_DEFAULT


async def _fetch_task_aggregates(project_id: int, db: Any) -> Any:
    """Uncached live aggregate read (the light read-only model getter)."""
    from backend.models.postgis.project import Project

    return await Project.get_task_aggregates(project_id, db)


async def _cached_task_aggregates(project_id: int, db: Any) -> Any:
    """Live aggregate with a short per-project TTL."""
    ttl = _stats_cache_ttl()
    if ttl <= 0:
        return await _fetch_task_aggregates(project_id, db)
    key = f"task_aggregates:{project_id}"
    cached = await _STATS_CACHE.get(key)
    if cached is not None:
        return cached
    value = await _fetch_task_aggregates(project_id, db)
    await _STATS_CACHE.set(key, value, ttl=ttl)
    return value


async def reset_stats_cache() -> None:
    """Test hook: drop all cached aggregates."""
    await _STATS_CACHE.clear()


def _raw_field(obj: Any, name: str) -> Any:
    """Read an attribute/key off a DTO-ish object; None when absent."""
    if hasattr(obj, name):
        return getattr(obj, name)
    if isinstance(obj, dict):
        return obj.get(name)
    try:
        return obj[name]
    except Exception:
        return None


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _int_field(obj: Any, name: str) -> Optional[int]:
    return _int_or_none(_raw_field(obj, name))


@dataclass(frozen=True)
class DomainEvidence(EvidenceBase):
    status: DomainStatus
    project_id: int
    operation: str = OPERATION
    total_tasks: Optional[int] = None
    tasks_mapped: Optional[int] = None
    tasks_validated: Optional[int] = None
    tasks_bad_imagery: Optional[int] = None
    provenance: str = PROVENANCE

    _CITATION_KIND = "stats"
    _CITATION_TITLE = "Project {id} live stats"
    _CITATION_HEADING = "project_stats"
    _CITATION_SOURCE = {
        "path": "backend/models/postgis/project.py",
        "symbol": "Project.get_task_aggregates",
    }

    def _scope_id(self) -> Any:
        return self.project_id

    def _body_lines(self) -> List[str]:
        lines = [f"total_tasks: {self.total_tasks}"]
        if self.tasks_mapped is not None:
            lines.append(f"tasks_mapped: {self.tasks_mapped}")
        if self.tasks_validated is not None:
            lines.append(f"tasks_validated: {self.tasks_validated}")
        if self.tasks_bad_imagery is not None:
            lines.append(f"tasks_bad_imagery: {self.tasks_bad_imagery}")
        return lines


@dataclass(frozen=True)
class ProjectSummaryEvidence(EvidenceBase):
    """Small allowlisted slice of ProjectSummary for the LLM."""

    status: DomainStatus
    project_id: int
    operation: str = SUMMARY_OPERATION
    name: Optional[str] = None
    project_status: Optional[str] = None
    private: Optional[bool] = None
    priority: Optional[str] = None
    difficulty: Optional[str] = None
    organisation_name: Optional[str] = None
    percent_mapped: Optional[int] = None
    percent_validated: Optional[int] = None
    short_description: Optional[str] = None
    due_date: Optional[str] = None
    campaigns: Tuple[str, ...] = ()
    country: Tuple[str, ...] = ()
    mapping_editors: Tuple[str, ...] = ()
    validation_editors: Tuple[str, ...] = ()
    provenance: str = SUMMARY_PROVENANCE

    _CITATION_KIND = "summary"
    _CITATION_TITLE = "Project {id} live summary"
    _CITATION_HEADING = "project_summary"
    _CITATION_SOURCE = {
        "path": "backend/services/project_service.py",
        "symbol": "ProjectService.get_project_summary",
    }

    def _scope_id(self) -> Any:
        return self.project_id

    def _body_lines(self) -> List[str]:
        lines: List[str] = []
        if self.name:
            lines.append(f"name: {safe_value(self.name)}")
        if self.project_status:
            lines.append(f"status: {safe_value(self.project_status, 64)}")
        if self.private is not None:
            lines.append(f"private: {self.private}")
        if self.priority:
            lines.append(f"priority: {safe_value(self.priority, 64)}")
        if self.difficulty:
            lines.append(f"difficulty: {safe_value(self.difficulty, 64)}")
        if self.organisation_name:
            lines.append(f"organisation: {safe_value(self.organisation_name)}")
        if self.percent_mapped is not None:
            lines.append(f"percent_mapped: {self.percent_mapped}")
        if self.percent_validated is not None:
            lines.append(f"percent_validated: {self.percent_validated}")
        if self.due_date:
            lines.append(f"due_date: {self.due_date}")
        if self.country:
            countries = ", ".join(safe_value(c, 64) for c in self.country[:10])
            lines.append(f"country: {countries}")
        if self.campaigns:
            campaigns = ", ".join(safe_value(c, 80) for c in self.campaigns[:10])
            lines.append(f"campaigns: {campaigns}")
        if self.mapping_editors:
            editors = ", ".join(safe_value(e, 32) for e in self.mapping_editors[:10])
            lines.append(f"mapping_editors: {editors}")
        if self.validation_editors:
            editors = ", ".join(safe_value(e, 32) for e in self.validation_editors[:10])
            lines.append(f"validation_editors: {editors}")
        if self.short_description:
            lines.append(f"summary: {safe_value(self.short_description)}")
        return lines


async def get_project_stats_evidence(
    user_id: int, project_id: int, db: Any
) -> DomainEvidence:
    """Authorized read-only fetch of live task aggregates."""
    from backend.exceptions import NotFound

    status, _project = await authorize_project(user_id, project_id, db)
    if status != "OK":
        return DomainEvidence(status=status, project_id=project_id)

    try:
        stats = await _cached_task_aggregates(project_id, db)
    except NotFound:
        return DomainEvidence(status="NOT_FOUND", project_id=project_id)
    except Exception:
        logger.exception(f"project {project_id} stats fetch failed")
        return DomainEvidence(status="UNAVAILABLE", project_id=project_id)

    return DomainEvidence(
        status="OK",
        project_id=project_id,
        total_tasks=_int_field(stats, "total_tasks"),
        tasks_mapped=_int_field(stats, "tasks_mapped"),
        tasks_validated=_int_field(stats, "tasks_validated"),
        tasks_bad_imagery=_int_field(stats, "tasks_bad_imagery"),
    )


async def get_project_summary_evidence(
    user_id: int, project_id: int, db: Any
) -> ProjectSummaryEvidence:
    """Authorized read-only fetch of live project attributes."""
    from backend.exceptions import NotFound

    status, _project = await authorize_project(user_id, project_id, db)
    if status != "OK":
        return ProjectSummaryEvidence(status=status, project_id=project_id)

    try:
        from backend.services.project_service import ProjectService

        summary = await ProjectService.get_project_summary(project_id, db)
    except NotFound:
        return ProjectSummaryEvidence(status="NOT_FOUND", project_id=project_id)
    except Exception:
        logger.exception(f"project {project_id} summary fetch failed")
        return ProjectSummaryEvidence(status="UNAVAILABLE", project_id=project_id)

    info = _raw_field(summary, "project_info")
    name = None
    short_description = None
    if info is not None:
        short_description = (
            getattr(info, "short_description", None)
            if not isinstance(info, dict)
            else info.get("short_description")
        )
        name = (
            getattr(info, "name", None)
            if not isinstance(info, dict)
            else info.get("name")
        )

    private = _raw_field(summary, "private")
    due_date = _raw_field(summary, "due_date")
    return ProjectSummaryEvidence(
        status="OK",
        project_id=project_id,
        name=str(name) if name else None,
        project_status=_raw_field(summary, "status"),
        private=bool(private) if private is not None else None,
        priority=_raw_field(summary, "priority"),
        difficulty=_raw_field(summary, "difficulty"),
        organisation_name=_raw_field(summary, "organisation_name"),
        percent_mapped=_int_field(summary, "percent_mapped"),
        percent_validated=_int_field(summary, "percent_validated"),
        short_description=(str(short_description) if short_description else None),
        due_date=(
            due_date.strftime("%Y-%m-%d") if hasattr(due_date, "strftime") else None
        ),
        campaigns=_names(_raw_field(summary, "campaigns")),
        country=_str_tuple(_raw_field(summary, "country_tag")),
        mapping_editors=_str_tuple(_raw_field(summary, "mapping_editors")),
        validation_editors=_str_tuple(_raw_field(summary, "validation_editors")),
    )


def _str_tuple(value: Any) -> Tuple[str, ...]:
    """Normalize a list-ish DTO field to a tuple of strings."""
    if not value:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value if item is not None)


def _names(rows: Any) -> Tuple[str, ...]:
    """Extract ``name`` values from DTO-ish campaign rows."""
    if not rows:
        return ()
    names = []
    for row in rows:
        if isinstance(row, dict):
            name = row.get("name")
        else:
            name = getattr(row, "name", None)
        if name:
            names.append(str(name))
    return tuple(names)
