from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from chat.retrieval.domain.evidence import DomainStatus, EvidenceBase, safe_value

USER_TASKS_OPERATION = "get_user_recent_tasks"
USER_TASKS_PROVENANCE = "UserService.get_tasks_dto"

_MAX_TASKS = 5
_MAX_INVALIDATIONS = 3


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
class InvalidationEntry:
    project_id: Optional[int]
    task_id: Optional[int]
    invalidated: str = ""
    invalidator: Optional[str] = None
    validator_comment: Optional[str] = None


@dataclass(frozen=True)
class UserTasksEvidence(EvidenceBase):
    """Recent tasks the asker interacted with, with current status."""

    status: DomainStatus
    user_id: int
    operation: str = USER_TASKS_OPERATION
    tasks: Tuple[UserTaskEntry, ...] = ()
    invalidations: Tuple[InvalidationEntry, ...] = ()
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
        if self.tasks:
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
            counts: Dict[str, int] = {}
            for entry in self.tasks:
                key = entry.task_status or "UNKNOWN"
                counts[key] = counts.get(key, 0) + 1
            summary = " | ".join(f"{key}: {counts[key]}" for key in sorted(counts))
            lines.append(f"task_status_summary: {summary}")
        else:
            lines = ["recent tasks: none — the user has no task activity yet"]
        if self.invalidations:
            lines.append(f"recent_invalidations ({len(self.invalidations)}):")
            for invalidation in self.invalidations[:_MAX_INVALIDATIONS]:
                parts = []
                if invalidation.project_id is not None:
                    parts.append(f"project {invalidation.project_id}")
                if invalidation.task_id is not None:
                    parts.append(f"task #{invalidation.task_id}")
                if invalidation.invalidated:
                    parts.append(f"invalidated: {invalidation.invalidated}")
                if invalidation.invalidator:
                    parts.append(f"by: {safe_value(invalidation.invalidator, 60)}")
                if invalidation.validator_comment:
                    parts.append(
                        "validator comment: "
                        f'"{safe_value(invalidation.validator_comment, 200)}"'
                    )
                else:
                    parts.append("validator comment: none recorded")
                lines.append("- " + " | ".join(parts))
        else:
            lines.append("recent_invalidations: none — no invalidated tasks")
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

        invalidations: List[InvalidationEntry] = []
        try:
            rows = await db.fetch_all(
                query="""
                    SELECT tih.project_id, tih.task_id, tih.invalidated_date,
                           u.username AS invalidator_username,
                           (
                               SELECT th.action_text
                               FROM task_history th
                               WHERE th.project_id = tih.project_id
                                 AND th.task_id = tih.task_id
                                 AND th.action = 'COMMENT'
                                 AND th.user_id = tih.invalidator_id
                               ORDER BY th.action_date DESC
                               LIMIT 1
                           ) AS validator_comment
                    FROM task_invalidation_history tih
                    LEFT JOIN users u ON u.id = tih.invalidator_id
                    WHERE tih.mapper_id = :user_id
                    ORDER BY tih.invalidated_date DESC NULLS LAST
                    LIMIT :limit
                """,
                values={"user_id": user_id, "limit": _MAX_INVALIDATIONS},
            )
            for row in rows or []:
                invalidations.append(
                    InvalidationEntry(
                        project_id=_attr(row, "project_id"),
                        task_id=_attr(row, "task_id"),
                        invalidated=_when(_attr(row, "invalidated_date")),
                        invalidator=_attr(row, "invalidator_username"),
                        validator_comment=_attr(row, "validator_comment"),
                    )
                )
        except Exception:
            logger.exception(f"user {user_id} invalidation fetch failed")

        return UserTasksEvidence(
            status="OK",
            user_id=user_id,
            tasks=tuple(entries[:_MAX_TASKS]),
            invalidations=tuple(invalidations),
        )
    except Exception:
        logger.exception(f"user {user_id} recent task fetch failed")
        return UserTasksEvidence(status="UNAVAILABLE", user_id=user_id)
