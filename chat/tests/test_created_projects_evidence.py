"""Evidence invariants for the authored-projects op.

The fetcher must read authorship from ``projects.author_id`` and must never
derive it from ``task_history`` mapping/validation activity.
"""

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from chat.retrieval.domain.user_projects import get_user_projects_created_evidence


@dataclass
class _FakeUser:
    id: int


class _FakeDB:
    """Records SQL and answers only authored-projects queries."""

    def __init__(self, count: int, rows: Optional[List[Dict[str, Any]]] = None):
        self.count = count
        self.rows = rows or []
        self.queries: List[str] = []
        self.values: List[Dict[str, Any]] = []

    async def fetch_one(self, query: str, values: Optional[Dict[str, Any]] = None):
        self.queries.append(query)
        self.values.append(values or {})
        if "COUNT(*)" in query and "projects" in query:
            return {"n": self.count}
        raise AssertionError(f"unexpected fetch_one: {query}")

    async def fetch_all(self, query: str, values: Optional[Dict[str, Any]] = None):
        self.queries.append(query)
        self.values.append(values or {})
        if "FROM projects" in query:
            return self.rows
        raise AssertionError(f"unexpected fetch_all: {query}")


def _patch_user(monkeypatch, user):
    import backend.models.postgis.user as user_module

    async def _get_by_id(user_id, db):
        return user

    monkeypatch.setattr(user_module.User, "get_by_id", _get_by_id)


def test_created_evidence_reads_author_id_not_task_history(monkeypatch):
    _patch_user(monkeypatch, _FakeUser(id=7))
    db = _FakeDB(
        count=3,
        rows=[
            {"id": 134, "name": "adfasf", "status": 2, "created": None},
            {"id": 122, "name": "usa-dc", "status": 1, "created": None},
        ],
    )
    evidence = asyncio.run(get_user_projects_created_evidence(7, db))

    assert evidence.status == "OK"
    assert evidence.projects_created_by_you == 3
    block = evidence.to_prompt_block()
    assert "projects_created_by_you: 3" in block
    assert "#134 adfasf" in block
    assert "status: DRAFT" in block
    assert "distinct_projects_mapped" not in block
    assert all("task_history" not in query for query in db.queries)
    assert all("author_id" in query for query in db.queries if "projects" in query)


def test_created_evidence_reports_zero_without_projects(monkeypatch):
    _patch_user(monkeypatch, _FakeUser(id=9))
    db = _FakeDB(count=0)
    evidence = asyncio.run(get_user_projects_created_evidence(9, db))

    assert evidence.status == "OK"
    block = evidence.to_prompt_block()
    assert "projects_created_by_you: 0" in block
    assert "recent_created_projects: none" in block


def test_created_evidence_missing_user_is_not_found(monkeypatch):
    _patch_user(monkeypatch, None)
    db = _FakeDB(count=0)
    evidence = asyncio.run(get_user_projects_created_evidence(404, db))

    assert evidence.status == "NOT_FOUND"
    assert evidence.to_prompt_block() == ""
