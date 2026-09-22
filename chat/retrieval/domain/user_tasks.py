from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from loguru import logger

from chat.retrieval.domain.evidence import DomainStatus, EvidenceBase, safe_value

USER_TASKS_OPERATION = "get_user_recent_tasks"
USER_TASKS_PROVENANCE = "UserService.get_tasks_dto"

_MAX_TASKS = 5


def _attr(obj: Any, name: str) -> Any:
    """Read a field off a DTO/ORM object or mapping; None when absent."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _when(value: Any) -> str:
    if isinstance(value, datetime.datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, datetime.date):
        return value.strftime("%Y-%m-%d")
    return ""


@dataclass(frozen=True)
class UserTaskEntry:
    task_id: Optional[int]
    project_id: Optional[int]
    task_status: Optional[str] = None
    last_updated: str = ""
    comments: int = 0


@dataclass(frozen=True)
class UserTasksEvidence(EvidenceBase):
    """Recent tasks the asker interacted with, with current status."""

    status: DomainStatus
    user_id: int
    operation: str = USER_TASKS_OPERATION
    tasks: Tuple[UserTaskEntry, ...] = ()
    provenance: str = USER_TASKS_PROVENANCE

    _CONTEXT_FIELD = "user_id"
    _CITATION_SCOPE = "user"
    _CITATION_KIND = "tasks"
    _CITATION_TITLE = "User recent tasks"
    _CITATION_HEADING = "user_tasks"
    _CITATION_SOURCE = {
        "path": "backend/services/users/user_service.py",
        "symbol": "UserService.get_tasks_dto",
    }

    def _scope_id(self) -> Any:
        return self.user_id

    def _body_lines(self) -> List[str]:
        if not self.tasks:
            return ["recent tasks: none — the user has no task activity yet"]
        lines = [f"recent_tasks ({len(self.tasks)}):"]
        for entry in self.tasks[:_MAX_TASKS]:
            parts = [f"task #{entry.task_id}"]
            if entry.project_id is not None:
                parts.append(f"project {entry.project_id}")
            if entry.task_status:
                parts.append(f"status: {safe_value(entry.task_status, 32)}")
            if entry.last_updated:
                parts.append(f"last action: {entry.last_updated}")
            parts.append(f"comments: {entry.comments}")
            lines.append("- " + " | ".join(parts))
        return lines


async def get_user_tasks_evidence(user_id: int, db: Any) -> UserTasksEvidence:
    """Read-only recent task activity for the authenticated user."""
    try:
        from backend.services.users.user_service import UserService

        dto = await UserService.get_tasks_dto(
            user_id=user_id,
            page=1,
            page_size=_MAX_TASKS,
            sort_by="-action_date",
            db=db,
        )

        entries: List[UserTaskEntry] = []
        for task in _attr(dto, "user_tasks") or []:
            entries.append(
                UserTaskEntry(
                    task_id=_attr(task, "task_id") or _attr(task, "taskId"),
                    project_id=_attr(task, "project_id"),
                    task_status=_attr(task, "task_status"),
                    last_updated=_when(_attr(task, "last_updated")),
                    comments=int(_attr(task, "comments_number") or 0),
                )
            )

        return UserTasksEvidence(
            status="OK", user_id=user_id, tasks=tuple(entries[:_MAX_TASKS])
        )
    except Exception:
        logger.exception(f"user {user_id} recent task fetch failed")
        return UserTasksEvidence(status="UNAVAILABLE", user_id=user_id)
