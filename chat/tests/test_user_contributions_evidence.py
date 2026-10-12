"""Evidence invariants for the contributions op.

The contributed-projects list must come from the backend's canonical
``users.projects_mapped`` array (the append-only record the backend writes when
a user maps a project): every recorded project is listed, the total and status
breakdown are stated, and any render-cap truncation is disclosed. Per-project
counts merge in from the tasks query where the tasks still exist.
"""

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from chat.retrieval.domain.user_contributions import (
    UserContributionEvidence,
    get_user_contribution_evidence,
)

# manjita pandey in the dev DB: 19 array entries, 15 published, 2 archived,
# 2 draft; the tasks query only covers 16 of them.
_MANJITA_ARRAY = [3, 1, 2, 6, 7, 8, 9, 11, 14, 19, 20, 23, 25, 27, 28, 98, 99, 100, 104]
_ARCHIVED = {1, 9}
_DRAFT = {7, 8}
_NO_CURRENT_TASKS = {11, 19, 25}


@dataclass
class _FakeUser:
    id: int
    username: str = "manjita pandey"


class _FakeStats:
    total_time_spent = 93.6 * 3600
    time_spent_mapping = 91.7 * 3600
    time_spent_validating = 1.9 * 3600
    tasks_mapped = 64
    tasks_validated = 26
    tasks_invalidated = 15
    countries_contributed = None
    # Deliberately different from the array length (task_history semantics):
    # this number must never surface in the block.
    projects_mapped = 18


class _CountRow:
    def __init__(self, pid: int, mapped: int, validated: int):
        self.project_id = pid
        self.tasks_mapped = mapped
        self.tasks_validated = validated


class _CountsDTO:
    def __init__(self, rows: List[_CountRow]):
        self.mapped_projects = rows


class _FakeDB:
    """Answers only the contributed-projects name/status query."""

    def __init__(self, project_rows: Optional[List[Dict[str, Any]]] = None):
        self.project_rows = project_rows or []
        self.queries: List[str] = []
        self.values: List[Dict[str, Any]] = []

    async def fetch_all(
        self, query: Optional[str] = None, values: Optional[Dict] = None
    ):
        self.queries.append(query or "")
        self.values.append(values or {})
        return self.project_rows


def _patch(monkeypatch, *, user, array, counts):
    import backend.models.postgis.user as user_module
    from backend.services.users.user_service import UserService

    async def _get_by_id(user_id, db):
        return user

    async def _get_detailed_stats(username, db):
        return _FakeStats()

    async def _get_contributions_by_day(user_id, db):
        return []

    async def _get_projects_mapped(user_id, db):
        return array

    async def _get_mapped_projects(user_id, locale, db):
        return _CountsDTO(counts)

    monkeypatch.setattr(user_module.User, "get_by_id", _get_by_id)
    monkeypatch.setattr(user_module.User, "get_mapped_projects", _get_mapped_projects)
    monkeypatch.setattr(UserService, "get_detailed_stats", _get_detailed_stats)
    monkeypatch.setattr(
        UserService, "get_contributions_by_day", _get_contributions_by_day
    )
    monkeypatch.setattr(UserService, "get_projects_mapped", _get_projects_mapped)


def _manjita_rows():
    rows = []
    for pid in sorted(_MANJITA_ARRAY, reverse=True):
        status = 0 if pid in _ARCHIVED else (2 if pid in _DRAFT else 1)
        rows.append({"id": pid, "status": status, "name": f"Project {pid}"})
    return rows


def _manjita_counts():
    return [
        _CountRow(pid, mapped=1, validated=0)
        for pid in sorted(set(_MANJITA_ARRAY) - _NO_CURRENT_TASKS, reverse=True)
    ]


def test_contributed_projects_list_uses_backend_array(monkeypatch):
    _patch(
        monkeypatch,
        user=_FakeUser(id=10022716),
        array=list(_MANJITA_ARRAY),
        counts=_manjita_counts(),
    )
    db = _FakeDB(_manjita_rows())
    evidence = asyncio.run(get_user_contribution_evidence(10022716, db))

    assert evidence.status == "OK"
    block = evidence.to_prompt_block()
    assert "contributed_projects_total: 19" in block
    assert "contributed_projects_by_status: 15 published, 2 archived, 2 draft" in block
    assert "contributed_projects (complete list, 19 items):" in block
    for pid in _MANJITA_ARRAY:
        assert f"#{pid} " in block, f"project {pid} missing from the block"
    assert "#9 Project 9 | status: ARCHIVED | mapped: 1 | validated: 0" in block
    assert "#25 Project 25 | no current tasks" in block
    # The task_history count (18) must never surface as the contributed total.
    assert "distinct_projects_mapped" not in block
    # The list is built from the array ids, not from task state.
    assert set(db.values[0]["project_ids"]) == set(_MANJITA_ARRAY)


def test_contributed_projects_truncation_is_disclosed(monkeypatch):
    monkeypatch.setenv("RAG_MAX_USER_PROJECTS", "5")
    ids = [10, 9, 8, 7, 6, 5, 4, 3]
    rows = [{"id": pid, "status": 1, "name": f"P{pid}"} for pid in ids]
    _patch(monkeypatch, user=_FakeUser(id=1), array=list(ids), counts=[])
    db = _FakeDB(rows)
    evidence = asyncio.run(get_user_contribution_evidence(1, db))

    block = evidence.to_prompt_block()
    assert "contributed_projects_total: 8" in block
    assert "contributed_projects (showing 5 of 8):" in block
    assert block.count("#") == 5


def test_contributed_projects_default_renders_every_project(monkeypatch):
    monkeypatch.delenv("RAG_MAX_USER_PROJECTS", raising=False)
    ids = list(range(40, 0, -1))
    rows = [{"id": pid, "status": 1, "name": f"P{pid}"} for pid in ids]
    _patch(monkeypatch, user=_FakeUser(id=1), array=list(ids), counts=[])
    db = _FakeDB(rows)
    evidence = asyncio.run(get_user_contribution_evidence(1, db))

    block = evidence.to_prompt_block()
    assert "contributed_projects_total: 40" in block
    assert "contributed_projects (complete list, 40 items):" in block
    for pid in ids:
        assert f"#{pid} " in block


def test_contributed_projects_zero_env_means_unlimited(monkeypatch):
    monkeypatch.setenv("RAG_MAX_USER_PROJECTS", "0")
    ids = [30, 20, 10]
    rows = [{"id": pid, "status": 1, "name": f"P{pid}"} for pid in ids]
    _patch(monkeypatch, user=_FakeUser(id=1), array=list(ids), counts=[])
    db = _FakeDB(rows)
    evidence = asyncio.run(get_user_contribution_evidence(1, db))

    block = evidence.to_prompt_block()
    assert "contributed_projects (complete list, 3 items):" in block
    assert "#30 " in block and "#20 " in block and "#10 " in block


def test_contributed_projects_empty_array(monkeypatch):
    _patch(monkeypatch, user=_FakeUser(id=1), array=[], counts=[])
    db = _FakeDB([])
    evidence = asyncio.run(get_user_contribution_evidence(1, db))

    block = evidence.to_prompt_block()
    assert "contributed_projects_total: 0" in block
    assert "contributed_projects: none — no contributed projects yet" in block
    assert db.queries == []  # no ids -> no project lookup


def test_contributed_projects_dropped_rows_are_not_counted(monkeypatch):
    _patch(monkeypatch, user=_FakeUser(id=1), array=[1, 2, 3], counts=[])
    db = _FakeDB(
        [
            {"id": 2, "status": 1, "name": "two"},
            {"id": 1, "status": 1, "name": "one"},
        ]
    )
    evidence = asyncio.run(get_user_contribution_evidence(1, db))

    block = evidence.to_prompt_block()
    assert "contributed_projects_total: 2" in block
    assert "#3 " not in block
    assert "contributed_projects_by_status: 2 published" in block
