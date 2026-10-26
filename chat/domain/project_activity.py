from __future__ import annotations

import datetime
from collections import Counter
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from loguru import logger

from chat.domain._rows import _attr, _iso_day
from chat.domain.auth import authorize_project
from chat.domain.evidence import DomainStatus, EvidenceBase, safe_value

ACTIVITY_OPERATION = "get_project_activity"
ACTIVITY_PROVENANCE = "StatsService.get_latest_activity + get_last_activity"

# stats_service.get_latest_activity pages at 10 events; page 1 is the newest.
_MAX_EVENTS = 10
# Distinct task-status names rolled up from get_last_activity.
_MAX_STATUS_ROWS = 8


@dataclass(frozen=True)
class ActivityEvent:
    task_id: Optional[int]
    action: Optional[str] = None
    action_date: str = ""
    action_by: Optional[str] = None
    action_text: Optional[str] = None


@dataclass(frozen=True)
class ProjectActivityEvidence(EvidenceBase):
    """Latest task activity in a project (recent events + per-status rollup).

    Mirrors the two activity endpoints: ``get_latest_activity`` (recent
    task-history events, COMMENT actions excluded) for the event feed, and
    ``get_last_activity`` (per-task latest status) rolled into counts.
    """

    status: DomainStatus
    project_id: int
    operation: str = ACTIVITY_OPERATION
    events_total: Optional[int] = None
    events: Tuple[ActivityEvent, ...] = ()
    tasks_by_status: Tuple[Tuple[str, int], ...] = ()
    last_action_date: str = ""
    last_action_by: Optional[str] = None
    provenance: str = ACTIVITY_PROVENANCE

    _CITATION_KIND = "activity"
    _CITATION_TITLE = "Project {id} latest activity"
    _CITATION_HEADING = "project_activity"
    _CITATION_SOURCE = {
        "path": "backend/services/stats_service.py",
        "symbol": "StatsService.get_latest_activity",
    }

    def _scope_id(self) -> Any:
        return self.project_id

    @staticmethod
    def _event_line(event: ActivityEvent) -> str:
        parts = [f"task #{event.task_id}"]
        if event.action:
            parts.append(safe_value(event.action, 32))
        if event.action_date:
            parts.append(safe_value(event.action_date, 32))
        if event.action_by:
            parts.append(f"by {safe_value(event.action_by, 64)}")
        if event.action_text:
            parts.append(safe_value(event.action_text, 80))
        return " | ".join(parts)

    def _body_lines(self) -> List[str]:
        lines: List[str] = []
        if self.events:
            shown = self.events[:_MAX_EVENTS]
            label = "recent_activity_events"
            if self.events_total is not None and self.events_total > len(shown):
                label += f" (showing {len(shown)} of {self.events_total})"
            else:
                label += f" (complete list, {len(shown)} items)"
            lines.append(label + ":")
            lines.extend(
                f"{position}. {self._event_line(event)}"
                for position, event in enumerate(shown, start=1)
            )
        elif self.events_total == 0:
            lines.append("recent_activity_events: none yet")
        if self.tasks_by_status:
            breakdown = ", ".join(
                f"{count} {safe_value(status_name, 32)}"
                for status_name, count in self.tasks_by_status[:_MAX_STATUS_ROWS]
            )
            lines.append(f"tasks_by_status: {breakdown}")
        if self.last_action_date:
            suffix = (
                f" by {safe_value(self.last_action_by, 64)}"
                if self.last_action_by
                else ""
            )
            lines.append(f"last_task_activity: {self.last_action_date}{suffix}")
        return lines


async def get_project_activity_evidence(
    user_id: int, project_id: int, db: Any
) -> ProjectActivityEvidence:
    """Authorized read-only latest-activity summary for one project."""
    status, _project = await authorize_project(user_id, project_id, db)
    if status != "OK":
        return ProjectActivityEvidence(status=status, project_id=project_id)

    from backend.services.stats_service import StatsService

    events: List[ActivityEvent] = []
    events_total: Optional[int] = None
    try:
        dto = await StatsService.get_latest_activity(project_id, 1, db)
        events = [
            ActivityEvent(
                task_id=_attr(item, "task_id"),
                action=_attr(item, "action"),
                action_date=_iso_day(_attr(item, "action_date")),
                action_by=_attr(item, "action_by"),
                action_text=_attr(item, "action_text"),
            )
            for item in _attr(dto, "activity") or []
        ]
        pagination = _attr(dto, "pagination")
        if pagination is not None:
            events_total = _attr(pagination, "total")
    except Exception:
        logger.exception(f"project {project_id} activity fetch failed")
        return ProjectActivityEvidence(status="UNAVAILABLE", project_id=project_id)

    statuses: Tuple[Tuple[str, int], ...] = ()
    last_date = ""
    last_by: Optional[str] = None
    try:
        last = await StatsService.get_last_activity(project_id, db)
        counts: Counter = Counter()
        latest: Optional[datetime.datetime] = None
        for row in _attr(last, "activity") or []:
            name = _attr(row, "task_status")
            if name:
                counts[str(name)] += 1
            when = _attr(row, "action_date")
            if isinstance(when, datetime.datetime) and (
                latest is None or when > latest
            ):
                latest = when
                last_by = _attr(row, "action_by")
        statuses = tuple(counts.most_common())
        last_date = _iso_day(latest)
    except Exception:
        logger.exception(f"project {project_id} task-status rollup failed")

    return ProjectActivityEvidence(
        status="OK",
        project_id=project_id,
        events_total=events_total,
        events=tuple(events),
        tasks_by_status=statuses,
        last_action_date=last_date,
        last_action_by=last_by,
    )
