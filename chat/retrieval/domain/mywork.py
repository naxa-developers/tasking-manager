from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from chat.retrieval.domain.evidence import DomainStatus, EvidenceBase

MYWORK_OPERATION = "get_my_work"
MYWORK_PROVENANCE = "Task.get_locked_tasks_details_for_user"


def _attr(row: Any, name: str) -> Any:
    """Read a field off a task row (ORM record or mapping); None when absent."""
    if isinstance(row, dict):
        return row.get(name)
    return getattr(row, name, None)


def _status_name(raw: Any) -> Optional[str]:
    """Map the stored task-status value to its TaskStatus name; never fail."""
    if raw is None:
        return None
    try:
        from backend.models.postgis.statuses import TaskStatus

        return TaskStatus(int(raw)).name
    except Exception:
        return str(raw)


@dataclass(frozen=True)
class LockedTaskGroup:
    """Locked tasks that share one project and one status."""

    project_id: Optional[int]
    task_status: Optional[str]
    task_ids: Tuple[Any, ...] = ()


@dataclass(frozen=True)
class MyWorkEvidence(EvidenceBase):
    status: DomainStatus
    user_id: int
    operation: str = MYWORK_OPERATION
    groups: Tuple[LockedTaskGroup, ...] = ()
    provenance: str = MYWORK_PROVENANCE

    _CONTEXT_FIELD = "user_id"
    _CITATION_SCOPE = "user"
    _CITATION_KIND = "work"
    _CITATION_TITLE = "User locked tasks"
    _CITATION_HEADING = "my_work"
    _CITATION_SOURCE = {
        "path": "backend/models/postgis/task.py",
        "symbol": "Task.get_locked_tasks_details_for_user",
    }

    def _scope_id(self) -> Any:
        return self.user_id

    def _body_lines(self) -> List[str]:
        if not self.groups:
            return ["locked tasks: none — the user has no task locked right now"]
        lines: List[str] = []
        for group in self.groups:
            proj = (
                f" in project {group.project_id}"
                if group.project_id is not None
                else ""
            )
            state = f" ({group.task_status})" if group.task_status else ""
            tasks = ", ".join(f"#{t}" for t in group.task_ids)
            lines.append(f"locked tasks{proj}{state}: {tasks}")
        return lines


def _group_rows(rows: Any) -> Tuple[LockedTaskGroup, ...]:
    """Group locked-task rows by (project_id, status) in deterministic order."""
    grouped: Dict[Tuple[Any, Any], List[Any]] = {}
    for row in rows or []:
        task_id = _attr(row, "id")
        if task_id is None:
            continue
        key = (_attr(row, "project_id"), _status_name(_attr(row, "task_status")))
        grouped.setdefault(key, []).append(task_id)

    def _sort_key(item: Tuple[Tuple[Any, Any], List[Any]]) -> Tuple[int, str]:
        (project_id, status), _ = item
        return (project_id if isinstance(project_id, int) else -1, str(status))

    return tuple(
        LockedTaskGroup(project_id=project_id, task_status=status, task_ids=tuple(ids))
        for (project_id, status), ids in sorted(grouped.items(), key=_sort_key)
    )


async def get_mywork_evidence(user_id: int, db: Any) -> MyWorkEvidence:
    """User-scoped read-only fetch of the asker's locked tasks."""
    try:
        from backend.models.postgis.task import Task

        rows = await Task.get_locked_tasks_details_for_user(user_id, db)
    except Exception:
        logger.exception(f"user {user_id} locked-tasks fetch failed")
        return MyWorkEvidence(status="UNAVAILABLE", user_id=user_id)

    return MyWorkEvidence(status="OK", user_id=user_id, groups=_group_rows(rows))
