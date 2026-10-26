from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from loguru import logger

from chat.domain._rows import _attr, _int_or_zero, _iso_day
from chat.domain.auth import authorize_project
from chat.domain.evidence import DomainStatus, EvidenceBase, safe_value

TASKS_OPERATION = "get_project_tasks"
TASKS_PROVENANCE = (
    "ValidatorService.get_mapped_tasks_by_user + task_history INVALIDATED rollup"
)

# Per-op prompt-size guards for the two task lists.
_MAX_MAPPED_USERS = 20
_MAX_INVALIDATED = 20


@dataclass(frozen=True)
class MappedTaskUser:
    username: str
    mapped_task_count: int = 0
    last_seen: str = ""


@dataclass(frozen=True)
class InvalidatedTask:
    task_id: int
    invalidated_count: int = 0


@dataclass(frozen=True)
class ProjectTasksEvidence(EvidenceBase):
    """Task-level status for one project: mapped-by-user + invalidations.

    Mirrors the task endpoints that are chat-appropriate: mapped tasks grouped
    by user (``get_mapped_tasks_by_user``) and the invalidated-counts query
    from the project statistics endpoint (tasks with ``count > 0`` only). The
    full task GeoJSON dump and single-task detail stay out of prompt evidence
    (payload size / no task-id route).
    """

    status: DomainStatus
    project_id: int
    operation: str = TASKS_OPERATION
    mapped_users_total: Optional[int] = None
    mapped_users: Tuple[MappedTaskUser, ...] = ()
    invalidated_total: Optional[int] = None
    invalidated: Tuple[InvalidatedTask, ...] = ()
    provenance: str = TASKS_PROVENANCE

    _CITATION_KIND = "tasks"
    _CITATION_TITLE = "Project {id} task status"
    _CITATION_HEADING = "project_tasks"
    _CITATION_SOURCE = {
        "path": "backend/services/validator_service.py",
        "symbol": "ValidatorService.get_mapped_tasks_by_user",
    }

    def _scope_id(self) -> Any:
        return self.project_id

    def _body_lines(self) -> List[str]:
        lines: List[str] = []
        if self.mapped_users:
            shown = self.mapped_users[:_MAX_MAPPED_USERS]
            label = "mapped_tasks_by_user"
            if self.mapped_users_total is not None and self.mapped_users_total > len(
                shown
            ):
                label += f" (top {len(shown)} of {self.mapped_users_total})"
            else:
                label += f" (complete list, {len(shown)} items)"
            lines.append(label + ":")
            for position, row in enumerate(shown, start=1):
                line = (
                    f"{position}. {safe_value(row.username, 64)}"
                    f" | mapped: {row.mapped_task_count}"
                )
                if row.last_seen:
                    line += f" | last_seen: {row.last_seen}"
                lines.append(line)
        elif self.mapped_users_total == 0:
            lines.append("mapped_tasks_by_user: none yet")
        if self.invalidated:
            shown = self.invalidated[:_MAX_INVALIDATED]
            label = "invalidated_tasks"
            if self.invalidated_total is not None and self.invalidated_total > len(
                shown
            ):
                label += (
                    f" (showing {len(shown)} of {self.invalidated_total},"
                    " by invalidation count)"
                )
            else:
                label += f" (complete list, {len(shown)} items)"
            lines.append(label + ":")
            lines.extend(
                f"{position}. task #{row.task_id}"
                f" | invalidated {row.invalidated_count} times"
                for position, row in enumerate(shown, start=1)
            )
        elif self.invalidated_total == 0:
            lines.append("invalidated_tasks: none")
        return lines


async def get_project_tasks_evidence(
    user_id: int, project_id: int, db: Any
) -> ProjectTasksEvidence:
    """Authorized read-only task-status summary for one project."""
    status, _project = await authorize_project(user_id, project_id, db)
    if status != "OK":
        return ProjectTasksEvidence(status=status, project_id=project_id)

    from backend.services.validator_service import ValidatorService

    mapped: List[MappedTaskUser] = []
    try:
        dto = await ValidatorService.get_mapped_tasks_by_user(project_id, db)
        for row in _attr(dto, "mapped_tasks") or []:
            username = _attr(row, "username")
            if not username:
                continue
            mapped.append(
                MappedTaskUser(
                    username=str(username),
                    mapped_task_count=_int_or_zero(_attr(row, "mapped_task_count")),
                    last_seen=_iso_day(_attr(row, "last_seen")),
                )
            )
        mapped.sort(key=lambda row: (-row.mapped_task_count, row.username))
    except Exception:
        logger.exception(f"project {project_id} mapped-tasks fetch failed")
        return ProjectTasksEvidence(status="UNAVAILABLE", project_id=project_id)

    invalidated: List[InvalidatedTask] = []
    invalidated_ok = False
    try:
        rows = await db.fetch_all(
            query="""
                SELECT th.task_id, COUNT(*) AS cnt
                FROM task_history th
                WHERE th.project_id = :project_id
                  AND th.action = 'STATE_CHANGE'
                  AND th.action_text = 'INVALIDATED'
                GROUP BY th.task_id
                HAVING COUNT(*) > 0
                ORDER BY cnt DESC, th.task_id ASC
            """,
            values={"project_id": project_id},
        )
        invalidated_ok = True
        for row in rows or []:
            task_id = _attr(row, "task_id")
            if task_id is None:
                continue
            invalidated.append(
                InvalidatedTask(
                    task_id=int(task_id),
                    invalidated_count=_int_or_zero(_attr(row, "cnt")),
                )
            )
        invalidated.sort(key=lambda row: (-row.invalidated_count, row.task_id))
    except Exception:
        logger.exception(f"project {project_id} invalidated-tasks rollup failed")

    return ProjectTasksEvidence(
        status="OK",
        project_id=project_id,
        mapped_users_total=len(mapped),
        mapped_users=tuple(mapped),
        # None (unknown) when the rollup failed — never a misleading "none".
        invalidated_total=len(invalidated) if invalidated_ok else None,
        invalidated=tuple(invalidated),
    )
