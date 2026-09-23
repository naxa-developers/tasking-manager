from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from loguru import logger

from chat.retrieval.domain.evidence import DomainStatus, EvidenceBase, safe_value

CREATED_PROJECTS_OPERATION = "get_user_projects_created"
CREATED_PROJECTS_PROVENANCE = "ProjectSearchService.get_managed_projects"

_MAX_PROJECTS = 10
_PREFERRED_LOCALE = "en"


def _attr(obj: Any, name: str) -> Any:
    """Read a field off a DTO/ORM object or mapping; None when absent."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _day(value: Any) -> str:
    if isinstance(value, datetime.datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, datetime.date):
        return value.strftime("%Y-%m-%d")
    return ""


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
            parts = []
            for project in self.projects[:_MAX_PROJECTS]:
                name = safe_value(project.name, 80) if project.name else ""
                label = f"#{project.project_id}" + (f" {name}" if name else "")
                details = []
                if project.status:
                    details.append(f"status: {safe_value(project.status, 32)}")
                if project.created:
                    details.append(f"created: {safe_value(project.created, 32)}")
                parts.append(label + (f" ({', '.join(details)})" if details else ""))
            lines.append("recent_created_projects: " + "; ".join(parts))
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

        rows = await db.fetch_all(
            query="""
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
                LIMIT :limit
            """,
            values={
                "user_id": user_id,
                "locale": _PREFERRED_LOCALE,
                "limit": _MAX_PROJECTS,
            },
        )

        projects = tuple(
            CreatedProject(
                project_id=_attr(row, "id"),
                name=_attr(row, "name"),
                status=_status_label(_attr(row, "status")),
                created=_day(_attr(row, "created")),
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
