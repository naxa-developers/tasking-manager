"""Evidence invariants for the project-activity op.

Activity mirrors the two activity endpoints: ``StatsService.get_latest_activity``
(recent task-history events, comments excluded) plus the per-task status rollup
from ``StatsService.get_last_activity``.
"""

import asyncio
import datetime
from dataclasses import dataclass
from typing import Any, List, Optional

import chat.retrieval.domain.project_activity as activity


@dataclass
class _Event:
    task_id: Optional[int]
    action: Optional[str]
    action_date: Any
    action_by: Optional[str]
    action_text: Optional[str] = None


@dataclass
class _Pagination:
    total: int


class _ActivityDTO:
    def __init__(self, events: List[_Event], total: Optional[int] = None):
        self.activity = events
        self.pagination = _Pagination(total) if total is not None else None


@dataclass
class _LastRow:
    task_id: int
    task_status: Optional[str]
    action_date: Any = None
    action_by: Optional[str] = None


class _LastDTO:
    def __init__(self, rows: List[_LastRow]):
        self.activity = rows


def _patch(
    monkeypatch,
    *,
    auth="OK",
    events=None,
    total=None,
    last_rows=None,
    latest_raises=False,
    last_raises=False,
):
    async def _authorize(user_id, project_id, db):
        return auth, (object() if auth == "OK" else None)

    monkeypatch.setattr(activity, "authorize_project", _authorize)

    from backend.services.stats_service import StatsService

    async def _get_latest(project_id, page, db):
        if latest_raises:
            raise RuntimeError("boom")
        return _ActivityDTO(events or [], total)

    async def _get_last(project_id, db):
        if last_raises:
            raise RuntimeError("boom")
        return _LastDTO(last_rows or [])

    monkeypatch.setattr(StatsService, "get_latest_activity", _get_latest)
    monkeypatch.setattr(StatsService, "get_last_activity", _get_last)


def _ten_events():
    return [
        _Event(
            task_id=100 - i,
            action="MAPPED",
            action_date=datetime.datetime(2026, 1, 2),
            action_by=f"user{i}",
        )
        for i in range(10)
    ]


def test_activity_events_and_status_rollup(monkeypatch):
    _patch(
        monkeypatch,
        events=_ten_events(),
        total=128,
        last_rows=[
            _LastRow(1, "MAPPED", datetime.datetime(2026, 1, 2, 10, 0), "alice"),
            _LastRow(2, "READY"),
            _LastRow(3, "MAPPED", datetime.datetime(2026, 1, 1, 9, 0), "bob"),
            _LastRow(4, "INVALIDATED", datetime.datetime(2026, 1, 3, 8, 0), "carol"),
        ],
    )
    evidence = asyncio.run(activity.get_project_activity_evidence(7, 5, db=None))

    assert evidence.status == "OK"
    block = evidence.to_prompt_block()
    assert "operation: get_project_activity" in block
    assert "project_id: 5" in block
    assert "recent_activity_events (showing 10 of 128):" in block
    assert "1. task #100 | MAPPED | 2026-01-02 | by user0" in block
    assert "tasks_by_status: 2 MAPPED, 1 READY, 1 INVALIDATED" in block
    assert "last_task_activity: 2026-01-03 by carol" in block


def test_activity_empty_project(monkeypatch):
    _patch(
        monkeypatch,
        events=[],
        total=0,
        last_rows=[_LastRow(1, "READY"), _LastRow(2, "READY")],
    )
    evidence = asyncio.run(activity.get_project_activity_evidence(7, 5, db=None))

    block = evidence.to_prompt_block()
    assert "recent_activity_events: none yet" in block
    assert "tasks_by_status: 2 READY" in block
    assert "last_task_activity" not in block


def test_activity_unauthorized_renders_nothing(monkeypatch):
    _patch(monkeypatch, auth="UNAUTHORIZED")
    evidence = asyncio.run(activity.get_project_activity_evidence(7, 5, db=None))

    assert evidence.status == "UNAUTHORIZED"
    assert evidence.to_prompt_block() == ""


def test_activity_degrades_when_status_rollup_fails(monkeypatch):
    _patch(monkeypatch, events=_ten_events(), total=128, last_raises=True)
    evidence = asyncio.run(activity.get_project_activity_evidence(7, 5, db=None))

    block = evidence.to_prompt_block()
    assert evidence.status == "OK"
    assert "recent_activity_events (showing 10 of 128):" in block
    assert "tasks_by_status" not in block
    assert "last_task_activity" not in block


def test_activity_unavailable_when_events_fail(monkeypatch):
    _patch(monkeypatch, latest_raises=True)
    evidence = asyncio.run(activity.get_project_activity_evidence(7, 5, db=None))

    assert evidence.status == "UNAVAILABLE"
    assert evidence.to_prompt_block() == ""
