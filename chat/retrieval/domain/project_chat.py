from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, List, Optional

from loguru import logger

from backend.models.postgis.utils import html_to_text
from chat.retrieval.domain.auth import authorize_project
from chat.retrieval.domain.evidence import DomainStatus, EvidenceBase
from chat.retrieval.guardrails import neutralize_untrusted

CHAT_OPERATION = "get_project_chat"
CHAT_PROVENANCE = "ProjectChat.get_messages"
CHAT_LIMIT = 5
CHAT_EXCERPT_CHARS = 200

# Excerpts shorter than this are insubstantial; never invent discussion.
_INSUBSTANTIAL_CHARS = 15


def _safe_username(username: str) -> str:
    """Sanitize a UGC username for the prompt (fallback: generic label)."""
    cleaned = neutralize_untrusted(username)
    if cleaned == "[message withheld]":
        return "user"
    return cleaned[:60] or "user"


def _plain_text(message_html: str, limit: int = CHAT_EXCERPT_CHARS) -> str:
    """Short, sanitized plain-text excerpt for the prompt (shared HTML->text)."""
    text = html_to_text(message_html or "")
    text = re.sub(r"\s+", " ", text).strip()
    text = neutralize_untrusted(text)
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


@dataclass(frozen=True)
class ChatMessageEntry:
    username: str
    excerpt: str


@dataclass(frozen=True)
class ProjectChatEvidence(EvidenceBase):
    status: DomainStatus
    project_id: int
    operation: str = CHAT_OPERATION
    message_count: Optional[int] = None
    messages: tuple = ()
    provenance: str = CHAT_PROVENANCE

    _CITATION_KIND = "chat"
    _CITATION_TITLE = "Project {id} recent discussion"
    _CITATION_HEADING = "project_chat"
    _CITATION_SOURCE = {
        "path": "backend/models/postgis/project_chat.py",
        "symbol": "ProjectChat.get_messages",
    }

    def _scope_id(self) -> Any:
        return self.project_id

    def _body_lines(self) -> List[str]:
        lines: List[str] = []
        if self.message_count is not None:
            lines.append(f"message_count: {self.message_count}")
        if not self.messages:
            lines.append("messages: none yet")
        else:
            lines.append(f"recent messages ({len(self.messages)}):")
            for entry in self.messages:
                lines.append(f"- {entry.username}: {entry.excerpt}")
            if all(
                len(entry.excerpt) < _INSUBSTANTIAL_CHARS for entry in self.messages
            ):
                lines.append(
                    "Note: all excerpts are very short — report that the recent "
                    "discussion is insubstantial; never invent details."
                )
        return lines


async def get_project_chat_evidence(
    user_id: int, project_id: int, db: Any, limit: int = CHAT_LIMIT
) -> ProjectChatEvidence:
    """Authorized read-only fetch of recent project discussion."""
    from backend.exceptions import NotFound

    status, _project = await authorize_project(user_id, project_id, db)
    if status != "OK":
        return ProjectChatEvidence(status=status, project_id=project_id)

    try:
        from backend.models.postgis.project_chat import ProjectChat

        dto = await ProjectChat.get_messages(project_id, db, 1, limit)
    except NotFound:
        return ProjectChatEvidence(status="NOT_FOUND", project_id=project_id)
    except Exception:
        logger.exception(f"project {project_id} chat fetch failed")
        return ProjectChatEvidence(status="UNAVAILABLE", project_id=project_id)

    entries: List[ChatMessageEntry] = []
    for msg in getattr(dto, "chat", None) or []:
        if isinstance(msg, dict):
            username, body = msg.get("username"), msg.get("message")
        else:
            username, body = getattr(msg, "username", None), getattr(
                msg, "message", None
            )
        if username and body:
            entries.append(
                ChatMessageEntry(
                    username=_safe_username(str(username)),
                    excerpt=_plain_text(str(body)),
                )
            )

    count: Optional[int] = None
    pagination = getattr(dto, "pagination", None)
    if pagination is not None:
        count = getattr(pagination, "total", None) or getattr(
            pagination, "total_count", None
        )
        if isinstance(pagination, dict):
            count = pagination.get("total", pagination.get("total_count"))
    try:
        count = int(count) if count is not None else None
    except (TypeError, ValueError):
        count = None

    return ProjectChatEvidence(
        status="OK", project_id=project_id, message_count=count, messages=tuple(entries)
    )
