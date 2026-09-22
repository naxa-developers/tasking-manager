from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from loguru import logger

from chat.retrieval.domain.evidence import DomainStatus, EvidenceBase
from chat.retrieval.domain.project_entries import (
    ProjectEntry,
    entry_from_dto,
    render_project_entries,
)

TRENDING_OPERATION = "get_trending_projects"
TRENDING_PROVENANCE = "StatsService.get_popular_projects"

_RESULT_LIMIT = 5


def _attr(obj: Any, name: str) -> Any:
    """Read a field off a DTO/ORM object or mapping; None when absent."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


@dataclass(frozen=True)
class TrendingProjectsEvidence(EvidenceBase):
    """Projects ranked by recent mapping/validation lock activity."""

    status: DomainStatus
    user_id: int
    operation: str = TRENDING_OPERATION
    projects: Tuple[ProjectEntry, ...] = ()
    provenance: str = TRENDING_PROVENANCE

    _CONTEXT_FIELD = "user_id"
    _CITATION_SCOPE = "global"
    _CITATION_KIND = "trending"
    _CITATION_TITLE = "Tasking Manager trending projects"
    _CITATION_HEADING = "trending_projects"
    _CITATION_SOURCE = {
        "path": "backend/services/stats_service.py",
        "symbol": "StatsService.get_popular_projects",
    }
    _CITATION_ID_TEMPLATE = "tm:global:{kind}"
    _CITATION_DOC_TEMPLATE = "tasking_manager:global"

    def _scope_id(self) -> Any:
        return "tm"

    def _body_lines(self) -> List[str]:
        lines = [
            "ranking_metric: mapping and validation lock activity "
            "over the last 90 days"
        ]
        if not self.projects:
            lines.append("projects: none with recent activity")
            return lines
        lines.append(f"projects ({len(self.projects)}):")
        lines.extend(render_project_entries(self.projects, limit=_RESULT_LIMIT))
        return lines


async def get_trending_projects_evidence(
    user_id: int, db: Any
) -> TrendingProjectsEvidence:
    """Read-only popularity ranking for the authenticated asker."""
    try:
        from backend.services.stats_service import StatsService

        results = await StatsService.get_popular_projects(db)
        entries = tuple(
            entry_from_dto(dto)
            for dto in (_attr(results, "results") or [])[:_RESULT_LIMIT]
        )
        return TrendingProjectsEvidence(status="OK", user_id=user_id, projects=entries)
    except Exception:
        logger.exception(f"user {user_id} trending projects fetch failed")
        return TrendingProjectsEvidence(status="UNAVAILABLE", user_id=user_id)
