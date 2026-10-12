"""Evidence invariants for the notifications op (asker-only)."""

import asyncio
import datetime
from dataclasses import dataclass
from typing import List, Optional

import chat.retrieval.domain.notifications as notifications


@dataclass
class _Msg:
    subject: Optional[str] = "Your task was validated"
    message_type: Optional[str] = "VALIDATION"
    sent_date: Optional[datetime.datetime] = None
    read: Optional[bool] = False
    project_title: Optional[str] = None


class _Pagination:
    def __init__(self, total: int):
        self.total = total


class _MessagesDTO:
    def __init__(self, rows: List[_Msg], total: Optional[int] = None):
        self.user_messages = rows
        self.pagination = _Pagination(total) if total is not None else None


def _patch(
    monkeypatch,
    *,
    rows=None,
    total=None,
    unread=0,
    list_raise=False,
    unread_raise=False,
):
    from backend.services.messaging.message_service import MessageService

    async def _all(db, user_id, locale, page, page_size=10, **kwargs):
        if list_raise:
            raise RuntimeError("boom")
        return _MessagesDTO(rows or [], total)

    async def _unread(user_id, db):
        if unread_raise:
            raise RuntimeError("boom")
        return {"newMessages": unread > 0, "unread": unread}

    monkeypatch.setattr(MessageService, "get_all_messages", _all)
    monkeypatch.setattr(MessageService, "has_user_new_messages", _unread)


def test_notifications_unread_and_recent(monkeypatch):
    _patch(
        monkeypatch,
        rows=[
            _Msg(
                "Your task was validated",
                "VALIDATION",
                datetime.datetime(2026, 1, 2),
                read=False,
                project_title="Roads",
            ),
            _Msg("Welcome", "SYSTEM", datetime.datetime(2026, 1, 1), read=True),
        ],
        total=42,
        unread=1,
    )
    evidence = asyncio.run(notifications.get_notifications_evidence(7, db=None))

    assert evidence.status == "OK"
    block = evidence.to_prompt_block()
    assert "operation: get_notifications" in block
    assert "unread_notifications: 1" in block
    assert "recent_notifications (showing 2 of 42):" in block
    assert (
        "1. Your task was validated | type: VALIDATION | 2026-01-02 | unread"
        " | project: Roads" in block
    )
    assert "2. Welcome | type: SYSTEM | 2026-01-01 | read" in block


def test_notifications_empty(monkeypatch):
    _patch(monkeypatch, rows=[], total=0, unread=0)
    evidence = asyncio.run(notifications.get_notifications_evidence(7, db=None))

    block = evidence.to_prompt_block()
    assert "unread_notifications: 0" in block
    assert "recent_notifications: none" in block


def test_notifications_unavailable_when_list_fails(monkeypatch):
    _patch(monkeypatch, list_raise=True)
    evidence = asyncio.run(notifications.get_notifications_evidence(7, db=None))

    assert evidence.status == "UNAVAILABLE"
    assert evidence.to_prompt_block() == ""


def test_notifications_degrades_when_unread_fails(monkeypatch):
    _patch(monkeypatch, rows=[_Msg()], total=1, unread_raise=True)
    evidence = asyncio.run(notifications.get_notifications_evidence(7, db=None))

    block = evidence.to_prompt_block()
    assert evidence.status == "OK"
    assert "unread_notifications" not in block
    assert "recent_notifications (complete list, 1 items):" in block
