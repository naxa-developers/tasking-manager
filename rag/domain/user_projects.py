from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from rag.env import env_int
from rag.domain._rows import _attr, _iso_day
from rag.domain.evidence import DomainStatus, EvidenceBase, safe_value

CREATED_PROJECTS_OPERATION = "get_user_projects_created"
# Authorship is read straight from ``projects.author_id`` — the same column the
# backend's createdByMe project-search filter resolves to. Not
# ProjectSearchService.get_managed_projects: "managed" also covers org-manager
# and team-project-manager projects and returns bare ids.
CREATED_PROJECTS_PROVENANCE = "projects.author_id (createdByMe search filter)"

# The authored-projects list renders completely by default; set
# RAG_MAX_USER_PROJECTS=N (N > 0) to cap it for very long answers. The stated
# total always covers every project the backend records; the list is disclosed
# as partial when it exceeds the cap.
_PREFERRED_LOCALE = "en"


def _max_projects() -> Optional[int]:
    """Optional render cap for the authored-projects list.

    ``RAG_MAX_USER_PROJECTS`` unset, 0, or invalid means no cap: render every
    authored project.
    """
    cap = env_int("RAG_MAX_USER_PROJECTS", 0)
    return cap if cap > 0 else None


def _status_label(value: Any) -> Optional[str]:
    """Project status name (PUBLISHED/DRAFT/ARCHIVED), None when unknown."""
    try:
        from backend.models.postgis.statuses import ProjectStatus

        return ProjectStatus(int(value)).name
    except Exception:
        return None


@dataclass(frozen=True)
class CreatedProject:
    project_id: Optional[int]
    name: Optional[str] = None
    status: Optional[str] = None
    created: str = ""


@dataclass(frozen=True)
class UserCreatedProjectsEvidence(EvidenceBase):
    """Projects authored by the asker (``projects.author_id``).

    Authorship is a distinct capability from contribution: this evidence is
    never derived from ``task_history`` mapping/validation activity.
    """

    status: DomainStatus
    user_id: int
    operation: str = CREATED_PROJECTS_OPERATION
    projects_created_by_you: Optional[int] = None
    projects: Tuple[CreatedProject, ...] = ()
    provenance: str = CREATED_PROJECTS_PROVENANCE

    _CONTEXT_FIELD = "user_id"
    _CITATION_SCOPE = "user"
    _CITATION_KIND = "created_projects"
    _CITATION_TITLE = "Projects created by user {id}"
    _CITATION_HEADING = "user_created_projects"
    _CITATION_SOURCE = {
        "path": "backend/models/postgis/project.py",
        "symbol": "Project.author_id",
    }

    def _scope_id(self) -> Any:
        return self.user_id

    def _body_lines(self) -> List[str]:
        lines: List[str] = []
        if self.projects_created_by_you is not None:
            lines.append(f"projects_created_by_you: {self.projects_created_by_you}")
        if self.projects:
            cap = _max_projects()
            shown = self.projects if cap is None else self.projects[:cap]
            label = "recent_created_projects"
            if (
                self.projects_created_by_you is not None
                and self.projects_created_by_you > len(shown)
            ):
                label += f" (showing {len(shown)} of {self.projects_created_by_you})"
            else:
                # A numbered, complete list: small models enumerate it reliably.
                label += f" (complete list, {len(shown)} items)"
            lines.append(label + ":")
            for position, project in enumerate(shown, start=1):
                name = safe_value(project.name, 80) if project.name else ""
                parts = [f"#{project.project_id}" + (f" {name}" if name else "")]
                if project.status:
                    parts.append(f"status: {safe_value(project.status, 32)}")
                if project.created:
                    parts.append(f"created: {safe_value(project.created, 32)}")
                lines.append(f"{position}. " + " | ".join(parts))
        elif self.projects_created_by_you == 0:
            lines.append("recent_created_projects: none")
        return lines


async def get_user_projects_created_evidence(
    user_id: int, db: Any
) -> UserCreatedProjectsEvidence:
    """Read-only authored-projects summary for the asker (all statuses)."""
    try:
        from backend.models.postgis.user import User as UserModel

        user = await UserModel.get_by_id(user_id, db)
        if user is None:
            return UserCreatedProjectsEvidence(status="NOT_FOUND", user_id=user_id)

        count_row = await db.fetch_one(
            query="SELECT COUNT(*) AS n FROM projects WHERE author_id = :user_id",
            values={"user_id": user_id},
        )
        total = int(count_row["n"]) if count_row and count_row["n"] is not None else 0

        query = """
            SELECT p.id, p.status, p.created,
                   COALESCE(pi_locale.name, pi_default.name) AS name
            FROM projects p
            LEFT JOIN project_info pi_locale
                ON pi_locale.project_id = p.id AND pi_locale.locale = :locale
            LEFT JOIN project_info pi_default
                ON pi_default.project_id = p.id
                AND pi_default.locale = p.default_locale
            WHERE p.author_id = :user_id
            ORDER BY p.created DESC NULLS LAST, p.id DESC
        """
        values: Dict[str, Any] = {"user_id": user_id, "locale": _PREFERRED_LOCALE}
        cap = _max_projects()
        if cap is not None:  # only the opt-in RAG_MAX_USER_PROJECTS cap limits rows
            query += " LIMIT :limit"
            values["limit"] = cap
        rows = await db.fetch_all(query=query, values=values)

        projects = tuple(
            CreatedProject(
                project_id=_attr(row, "id"),
                name=_attr(row, "name"),
                status=_status_label(_attr(row, "status")),
                created=_iso_day(_attr(row, "created")),
            )
            for row in rows or []
        )

        return UserCreatedProjectsEvidence(
            status="OK",
            user_id=user_id,
            projects_created_by_you=total,
            projects=projects,
        )
    except Exception:
        logger.exception(f"user {user_id} created projects fetch failed")
        return UserCreatedProjectsEvidence(status="UNAVAILABLE", user_id=user_id)
