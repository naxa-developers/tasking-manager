from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Tuple

from loguru import logger

from chat.domain._rows import _attr
from chat.domain.auth import authorize_project
from chat.domain.evidence import DomainStatus, EvidenceBase
from chat.domain.project_entries import (
    ProjectEntry,
    entry_from_dto,
    render_project_entries,
)

SIMILAR_OPERATION = "get_similar_projects"
SIMILAR_PROVENANCE = "ProjectRecommendationService.get_similar_projects"
_SIMILAR_LIMIT = 5


@dataclass(frozen=True)
class SimilarProjectsEvidence(EvidenceBase):
    """Projects similar to one project, ranked by the recommendation service.

    Mirrors ``ProjectRecommendationService.get_similar_projects``: the
    endpoint's target gate (published project only) surfaces as NOT_FOUND.
    """

    status: DomainStatus
    project_id: int
    operation: str = SIMILAR_OPERATION
    projects: Tuple[ProjectEntry, ...] = ()
    provenance: str = SIMILAR_PROVENANCE

    _CITATION_KIND = "similar_projects"
    _CITATION_TITLE = "Projects similar to {id}"
    _CITATION_HEADING = "similar_projects"
    _CITATION_SOURCE = {
        "path": "backend/services/recommendation_service.py",
        "symbol": "ProjectRecommendationService.get_similar_projects",
    }

    def _scope_id(self) -> Any:
        return self.project_id

    def _body_lines(self) -> List[str]:
        if not self.projects:
            return ["similar_projects: none found"]
        lines = [f"similar_projects ({len(self.projects)}):"]
        lines.extend(render_project_entries(self.projects, limit=_SIMILAR_LIMIT))
        return lines


async def get_similar_projects_evidence(
    user_id: int, project_id: int, db: Any
) -> SimilarProjectsEvidence:
    """Authorized read-only similar-projects list for one project."""
    status, _project = await authorize_project(user_id, project_id, db)
    if status != "OK":
        return SimilarProjectsEvidence(status=status, project_id=project_id)

    from backend.exceptions import NotFound
    from backend.services.recommendation_service import (
        ProjectRecommendationService,
    )

    try:
        dto = await ProjectRecommendationService.get_similar_projects(
            db, project_id, user_id, "en", _SIMILAR_LIMIT
        )
    except NotFound:
        # The endpoint's own gate: the target must be a published project.
        return SimilarProjectsEvidence(status="NOT_FOUND", project_id=project_id)
    except Exception:
        logger.exception(f"project {project_id} similar-projects fetch failed")
        return SimilarProjectsEvidence(status="UNAVAILABLE", project_id=project_id)

    entries = tuple(
        entry_from_dto(row) for row in (_attr(dto, "results") or [])[:_SIMILAR_LIMIT]
    )
    return SimilarProjectsEvidence(status="OK", project_id=project_id, projects=entries)
