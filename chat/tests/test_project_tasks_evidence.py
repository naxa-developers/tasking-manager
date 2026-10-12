"""Evidence invariants for the project-tasks op.

Mirrors the task endpoints: mapped tasks grouped by user
(``ValidatorService.get_mapped_tasks_by_user``) plus the invalidated-counts
rollup from the project statistics endpoint (``count > 0`` only).
"""

import asyncio
import datetime
from dataclasses import dataclass
from typing import Any, List, Optional

import chat.retrieval.domain.project_tasks as tasks


@dataclass
class _MappedRow:
    username: Optional[str]
    mapped_task_count: Optional[int]
    last_seen: Any = None


class _MappedDTO:
    def __init__(self, rows: List[_MappedRow]):
        self.mapped_tasks = rows


class _FakeDB:
    def __init__(self, rows: Optional[List[dict]] = None, raise_on_fetch=False):
        self.rows = rows or []
        self.raise_on_fetch = raise_on_fetch
        self.queries: List[str] = []

    async def fetch_all(self, query: str, values: Optional[dict] = None):
        self.queries.append(query)
        if self.raise_on_fetch:
            raise RuntimeError("boom")
        return self.rows


def _patch(monkeypatch, *, auth="OK", mapped=None, mapped_raise=False):
    async def _authorize(user_id, project_id, db):
        return auth, (object() if auth == "OK" else None)

    monkeypatch.setattr(tasks, "authorize_project", _authorize)

    from backend.services.validator_service import ValidatorService

    async def _get_mapped(project_id, db):
        if mapped_raise:
            raise RuntimeError("boom")
        return _MappedDTO(mapped or [])

    monkeypatch.setattr(ValidatorService, "get_mapped_tasks_by_user", _get_mapped)


def test_tasks_mapped_by_user_and_invalidated(monkeypatch):
    _patch(
        monkeypatch,
        mapped=[
            _MappedRow("alice", 12, datetime.datetime(2026, 1, 2)),
            _MappedRow("bob", 3),
        ],
    )
    db = _FakeDB(rows=[{"task_id": 77, "cnt": 3}, {"task_id": 80, "cnt": 1}])
    evidence = asyncio.run(tasks.get_project_tasks_evidence(7, 5, db))

    assert evidence.status == "OK"
    block = evidence.to_prompt_block()
    assert "operation: get_project_tasks" in block
    assert "mapped_tasks_by_user (complete list, 2 items):" in block
    assert "1. alice | mapped: 12 | last_seen: 2026-01-02" in block
    assert "2. bob | mapped: 3" in block
    assert "invalidated_tasks (complete list, 2 items):" in block
    assert "1. task #77 | invalidated 3 times" in block
    assert "2. task #80 | invalidated 1 times" in block


def test_tasks_caps_disclose_slices(monkeypatch):
    users = [_MappedRow(f"user{i}", i) for i in range(25)]
    _patch(monkeypatch, mapped=users)
    db = _FakeDB(rows=[{"task_id": i, "cnt": i} for i in range(1, 26)])
    evidence = asyncio.run(tasks.get_project_tasks_evidence(7, 5, db))

    block = evidence.to_prompt_block()
    assert "mapped_tasks_by_user (top 20 of 25):" in block
    assert "1. user24 | mapped: 24" in block
    assert "invalidated_tasks (showing 20 of 25, by invalidation count):" in block
    assert "1. task #25 | invalidated 25 times" in block


def test_tasks_empty_project(monkeypatch):
    _patch(monkeypatch, mapped=[])
    db = _FakeDB(rows=[])
    evidence = asyncio.run(tasks.get_project_tasks_evidence(7, 5, db))

    block = evidence.to_prompt_block()
    assert "mapped_tasks_by_user: none yet" in block
    assert "invalidated_tasks: none" in block


def test_tasks_unavailable_when_mapped_fetch_fails(monkeypatch):
    _patch(monkeypatch, mapped_raise=True)
    db = _FakeDB()
    evidence = asyncio.run(tasks.get_project_tasks_evidence(7, 5, db))

    assert evidence.status == "UNAVAILABLE"
    assert evidence.to_prompt_block() == ""


def test_tasks_degrades_when_invalidated_query_fails(monkeypatch):
    _patch(monkeypatch, mapped=[_MappedRow("alice", 2)])
    db = _FakeDB(raise_on_fetch=True)
    evidence = asyncio.run(tasks.get_project_tasks_evidence(7, 5, db))

    block = evidence.to_prompt_block()
    assert evidence.status == "OK"
    assert "mapped_tasks_by_user (complete list, 1 items):" in block
    assert "invalidated_tasks" not in block


def test_tasks_unauthorized_renders_nothing(monkeypatch):
    _patch(monkeypatch, auth="UNAUTHORIZED")
    db = _FakeDB()
    evidence = asyncio.run(tasks.get_project_tasks_evidence(7, 5, db))

    assert evidence.status == "UNAUTHORIZED"
    assert evidence.to_prompt_block() == ""
