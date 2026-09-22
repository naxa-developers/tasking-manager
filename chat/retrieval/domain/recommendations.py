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

RECOMMENDATION_OPERATION = "get_user_recommendations"
RECOMMENDATION_PROVENANCE = "UserService.get_recommended_projects"

_RESULT_LIMIT = 5


def _attr(obj: Any, name: str) -> Any:
    """Read a field off a DTO/ORM object or mapping; None when absent."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


@dataclass(frozen=True)
class UserRecommendationEvidence(EvidenceBase):
    """Projects suggested from the asker's own contribution history."""

    status: DomainStatus
    user_id: int
    operation: str = RECOMMENDATION_OPERATION
    projects: Tuple[ProjectEntry, ...] = ()
    provenance: str = RECOMMENDATION_PROVENANCE

    _CONTEXT_FIELD = "user_id"
    _CITATION_SCOPE = "user"
    _CITATION_KIND = "recommendations"
    _CITATION_TITLE = "Project recommendations for the user"
    _CITATION_HEADING = "user_recommendations"
    _CITATION_SOURCE = {
        "path": "backend/services/users/user_service.py",
        "symbol": "UserService.get_recommended_projects",
    }

    def _scope_id(self) -> Any:
        return self.user_id

    def _body_lines(self) -> List[str]:
        lines = [
            "basis: campaigns of projects the user contributed to, "
            "plus the user's mapping level"
        ]
        if not self.projects:
            lines.append("recommended_projects: none found")
            return lines
        lines.append(f"recommended_projects ({len(self.projects)}):")
        lines.extend(render_project_entries(self.projects, limit=_RESULT_LIMIT))
        return lines


async def get_user_recommendation_evidence(
    user_id: int, db: Any
) -> UserRecommendationEvidence:
    """Read-only recommendation lookup scoped to the asker."""
    try:
        from backend.models.postgis.user import User as UserModel
        from backend.services.users.user_service import UserService

        user = await UserModel.get_by_id(user_id, db)
        username = _attr(user, "username")
        if not username:
            return UserRecommendationEvidence(status="NOT_FOUND", user_id=user_id)

        results = await UserService.get_recommended_projects(str(username), "en", db)
        # The backend recommender is not visibility-scoped: never surface
        # non-published projects through chat.
        entries = tuple(
            entry_from_dto(dto)
            for dto in (_attr(results, "results") or [])
            if _attr(dto, "status") == "PUBLISHED"
        )[:_RESULT_LIMIT]
        return UserRecommendationEvidence(
            status="OK", user_id=user_id, projects=entries
        )
    except Exception:
        logger.exception(f"user {user_id} recommendations fetch failed")
        return UserRecommendationEvidence(status="UNAVAILABLE", user_id=user_id)
