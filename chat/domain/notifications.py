from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from loguru import logger

from chat.domain._rows import _attr, _iso_day
from chat.domain.evidence import DomainStatus, EvidenceBase, safe_value

NOTIFICATIONS_OPERATION = "get_notifications"
NOTIFICATIONS_PROVENANCE = (
    "MessageService.get_all_messages + MessageService.has_user_new_messages"
)

# Matches the notifications endpoint default page size.
_MAX_NOTIFICATIONS = 10


@dataclass(frozen=True)
class NotificationEntry:
    subject: Optional[str] = None
    message_type: Optional[str] = None
    sent_date: str = ""
    read: Optional[bool] = None
    project_title: Optional[str] = None


@dataclass(frozen=True)
class NotificationsEvidence(EvidenceBase):
    """The asker's own notifications (unread count + recent messages).

    Mirrors the notifications endpoints: the unread count
    (``has_user_new_messages``) and the asker's message list
    (``get_all_messages``, newest first). Asker-only by design.
    """

    status: DomainStatus
    user_id: int
    operation: str = NOTIFICATIONS_OPERATION
    unread: Optional[int] = None
    notifications_total: Optional[int] = None
    notifications: Tuple[NotificationEntry, ...] = ()
    provenance: str = NOTIFICATIONS_PROVENANCE

    _CONTEXT_FIELD = "user_id"
    _CITATION_SCOPE = "user"
    _CITATION_KIND = "notifications"
    _CITATION_TITLE = "User {id} notifications"
    _CITATION_HEADING = "user_notifications"
    _CITATION_SOURCE = {
        "path": "backend/services/messaging/message_service.py",
        "symbol": "MessageService.get_all_messages",
    }

    def _scope_id(self) -> Any:
        return self.user_id

    def _notification_line(self, entry: NotificationEntry) -> str:
        parts = [safe_value(entry.subject, 80) if entry.subject else "(no subject)"]
        detail = []
        if entry.message_type:
            detail.append(f"type: {safe_value(entry.message_type, 32)}")
        if entry.sent_date:
            detail.append(entry.sent_date)
        if entry.read is not None:
            detail.append("read" if entry.read else "unread")
        if entry.project_title:
            detail.append(f"project: {safe_value(entry.project_title, 60)}")
        if detail:
            parts.append(" | ".join(detail))
        return " | ".join(parts)

    def _body_lines(self) -> List[str]:
        lines: List[str] = []
        if self.unread is not None:
            lines.append(f"unread_notifications: {self.unread}")
        if self.notifications:
            shown = self.notifications[:_MAX_NOTIFICATIONS]
            label = "recent_notifications"
            if self.notifications_total is not None and self.notifications_total > len(
                shown
            ):
                label += f" (showing {len(shown)} of {self.notifications_total})"
            else:
                label += f" (complete list, {len(shown)} items)"
            lines.append(label + ":")
            lines.extend(
                f"{position}. {self._notification_line(entry)}"
                for position, entry in enumerate(shown, start=1)
            )
        elif self.notifications_total == 0 and self.unread == 0:
            lines.append("recent_notifications: none")
        return lines


async def get_notifications_evidence(user_id: int, db: Any) -> NotificationsEvidence:
    """Read-only notification summary for the asker."""
    from backend.services.messaging.message_service import MessageService

    unread: Optional[int] = None
    try:
        counts = await MessageService.has_user_new_messages(user_id, db)
        unread = _attr(counts, "unread")
    except Exception:
        logger.exception(f"user {user_id} unread-count fetch failed")

    try:
        dto = await MessageService.get_all_messages(
            db, user_id, "en", 1, page_size=_MAX_NOTIFICATIONS
        )
        rows = _attr(dto, "user_messages") or []
        notifications = tuple(
            NotificationEntry(
                subject=_attr(row, "subject"),
                message_type=_attr(row, "message_type"),
                sent_date=_iso_day(_attr(row, "sent_date")),
                read=_attr(row, "read"),
                project_title=_attr(row, "project_title"),
            )
            for row in rows
        )
        pagination = _attr(dto, "pagination")
        total = _attr(pagination, "total") if pagination is not None else None
        if total is None:
            total = len(notifications)
    except Exception:
        logger.exception(f"user {user_id} notifications fetch failed")
        return NotificationsEvidence(status="UNAVAILABLE", user_id=user_id)

    return NotificationsEvidence(
        status="OK",
        user_id=user_id,
        unread=unread,
        notifications_total=int(total),
        notifications=notifications,
    )
