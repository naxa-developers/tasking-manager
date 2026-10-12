from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from loguru import logger

from chat.retrieval.domain._rows import _attr
from chat.retrieval.domain.evidence import DomainStatus, EvidenceBase, safe_value

FAVORITES_OPERATION = "get_user_favorites"
FAVORITES_PROVENANCE = (
    "UserService.get_projects_favorited + ProjectService.is_favorited"
)

# Per-op prompt-size guard for the favorites list.
_MAX_FAVORITES = 20


@dataclass(frozen=True)
class FavoriteProject:
    project_id: Optional[int]
    name: Optional[str] = None


@dataclass(frozen=True)
class FavoritesEvidence(EvidenceBase):
    """The asker's favorite (saved) projects — asker-only by design.

    Mirrors ``UserService.get_projects_favorited`` for the list and
    ``ProjectService.is_favorited`` for the per-project status when the
    question names one project id.
    """

    status: DomainStatus
    user_id: int
    operation: str = FAVORITES_OPERATION
    favorite_projects_total: Optional[int] = None
    favorite_projects: Tuple[FavoriteProject, ...] = ()
    project_is_favorite: Optional[bool] = None
    favorite_status_project_id: Optional[int] = None
    provenance: str = FAVORITES_PROVENANCE

    _CONTEXT_FIELD = "user_id"
    _CITATION_SCOPE = "user"
    _CITATION_KIND = "favorites"
    _CITATION_TITLE = "User {id} favorite projects"
    _CITATION_HEADING = "user_favorites"
    _CITATION_SOURCE = {
        "path": "backend/services/users/user_service.py",
        "symbol": "UserService.get_projects_favorited",
    }

    def _scope_id(self) -> Any:
        return self.user_id

    def _body_lines(self) -> List[str]:
        lines: List[str] = []
        if self.favorite_projects_total is not None:
            lines.append(f"favorite_projects_total: {self.favorite_projects_total}")
        if self.project_is_favorite is not None:
            answer = "yes" if self.project_is_favorite else "no"
            lines.append(
                f"project_{self.favorite_status_project_id}_is_favorite: {answer}"
            )
        if self.favorite_projects:
            shown = self.favorite_projects[:_MAX_FAVORITES]
            label = "favorite_projects"
            if (
                self.favorite_projects_total is not None
                and self.favorite_projects_total > len(shown)
            ):
                label += f" (showing {len(shown)} of {self.favorite_projects_total})"
            else:
                label += f" (complete list, {len(shown)} items)"
            lines.append(label + ":")
            for position, project in enumerate(shown, start=1):
                name = safe_value(project.name, 80) if project.name else ""
                line = f"{position}. #{project.project_id}"
                if name:
                    line += f" {name}"
                lines.append(line)
        elif self.favorite_projects_total == 0:
            lines.append("favorite_projects: none yet")
        return lines


async def get_favorites_evidence(
    user_id: int, project_id: Optional[int], db: Any
) -> FavoritesEvidence:
    """Read-only favorites summary for the asker (their own data, no gate)."""
    from backend.services.users.user_service import UserService

    favorites: List[FavoriteProject] = []
    try:
        dto = await UserService.get_projects_favorited(user_id, db)
        for row in _attr(dto, "favorited_projects") or []:
            info = _attr(row, "project_info")
            favorites.append(
                FavoriteProject(
                    project_id=_attr(row, "project_id"),
                    name=_attr(info, "name") if info is not None else None,
                )
            )
    except Exception:
        logger.exception(f"user {user_id} favorites fetch failed")
        return FavoritesEvidence(status="UNAVAILABLE", user_id=user_id)

    is_favorite: Optional[bool] = None
    if project_id is not None:
        try:
            from backend.services.project_service import ProjectService

            is_favorite = bool(
                await ProjectService.is_favorited(project_id, user_id, db)
            )
        except Exception:
            logger.exception(f"user {user_id} favorite status check failed")

    return FavoritesEvidence(
        status="OK",
        user_id=user_id,
        favorite_projects_total=len(favorites),
        favorite_projects=tuple(favorites),
        project_is_favorite=is_favorite,
        favorite_status_project_id=project_id if is_favorite is not None else None,
    )
