from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Tuple

from loguru import logger

from chat.retrieval.domain._rows import _attr
from chat.retrieval.domain.evidence import DomainStatus, EvidenceBase
from chat.retrieval.domain.project_entries import (
    ProjectEntry,
    entry_from_dto,
    render_project_entries,
)

FEATURED_OPERATION = "get_featured_projects"
FEATURED_PROVENANCE = "ProjectService.get_featured_projects"
_MAX_FEATURED = 8


@dataclass(frozen=True)
class FeaturedProjectsEvidence(EvidenceBase):
    """Site-wide featured projects.

    Mirrors ``ProjectService.get_featured_projects`` (search-shaped results,
    rendered with the shared project-entry lines).
    """

    status: DomainStatus
    user_id: int
    operation: str = FEATURED_OPERATION
    projects: Tuple[ProjectEntry, ...] = ()
    provenance: str = FEATURED_PROVENANCE

    _CONTEXT_FIELD = "user_id"
    _CITATION_SCOPE = "global"
    _CITATION_KIND = "featured_projects"
    _CITATION_TITLE = "Tasking Manager featured projects"
    _CITATION_HEADING = "featured_projects"
    _CITATION_SOURCE = {
        "path": "backend/services/project_service.py",
        "symbol": "ProjectService.get_featured_projects",
    }
    _CITATION_ID_TEMPLATE = "tm:global:{kind}"
    _CITATION_DOC_TEMPLATE = "tasking_manager:global"

    def _scope_id(self) -> Any:
        return "tm"

    def _body_lines(self) -> List[str]:
        if not self.projects:
            return ["featured_projects: none right now"]
        lines = [f"featured_projects ({len(self.projects)}):"]
        lines.extend(render_project_entries(self.projects, limit=_MAX_FEATURED))
        return lines


async def get_featured_projects_evidence(
    user_id: int, db: Any
) -> FeaturedProjectsEvidence:
    """Read-only featured-projects list for the asker."""
    from backend.services.project_service import ProjectService

    try:
        dto = await ProjectService.get_featured_projects("en", db)
    except Exception:
        logger.exception("featured projects fetch failed")
        return FeaturedProjectsEvidence(status="UNAVAILABLE", user_id=user_id)

    entries = tuple(
        entry_from_dto(row) for row in (_attr(dto, "results") or [])[:_MAX_FEATURED]
    )
    return FeaturedProjectsEvidence(status="OK", user_id=user_id, projects=entries)
