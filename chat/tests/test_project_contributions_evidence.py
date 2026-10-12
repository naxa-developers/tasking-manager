"""Evidence invariants for the project-contributions op.

Mirrors the contribution endpoints: per-user totals from
``StatsService.get_user_contributions`` (already ordered by total desc) and
per-day increments from ``ProjectService.get_contribs_by_day``. The asker's own
row is highlighted when present.
"""

import asyncio
from dataclasses import dataclass
from typing import Any, List, Optional

import chat.retrieval.domain.project_contributions as contributions


@dataclass
class _UserRow:
    username: Optional[str]
    mapped: int = 0
    validated: int = 0
    bad_imagery: int = 0
    total: int = 0


class _ContribsDTO:
    def __init__(self, rows: List[_UserRow]):
        self.user_contributions = rows


@dataclass
class _DayRow:
    date: Any
    mapped: int = 0
    validated: int = 0


class _DaysDTO:
    def __init__(self, rows: List[_DayRow]):
        self.stats = rows


@dataclass
class _FakeUser:
    username: Optional[str]


def _patch(
    monkeypatch,
    *,
    auth="OK",
    rows=None,
    days=None,
    username="manjita pandey",
    on_users=False,
    contribs_raise=False,
    days_raise=False,
):
    async def _authorize(user_id, project_id, db):
        return auth, (object() if auth == "OK" else None)

    monkeypatch.setattr(contributions, "authorize_project", _authorize)

    from backend.models.postgis.user import User as UserModel
    from backend.services.project_service import ProjectService
    from backend.services.stats_service import StatsService

    async def _get_by_id(user_id, db):
        return _FakeUser(username=username) if on_users else None

    async def _get_contribs(project_id, db):
        if contribs_raise:
            raise RuntimeError("boom")
        return _ContribsDTO(rows or [])

    async def _get_days(project_id, db):
        if days_raise:
            raise RuntimeError("boom")
        return _DaysDTO(days or [])

    monkeypatch.setattr(UserModel, "get_by_id", _get_by_id)
    monkeypatch.setattr(StatsService, "get_user_contributions", _get_contribs)
    monkeypatch.setattr(ProjectService, "get_contribs_by_day", _get_days)


def _rows():
    return [
        _UserRow("alice", mapped=12, validated=3, bad_imagery=1, total=16),
        _UserRow("manjita pandey", mapped=4, validated=1, total=5),
        _UserRow("bob", mapped=2, validated=0, total=2),
    ]


def test_contributors_with_asker_highlighted(monkeypatch):
    import datetime

    _patch(
        monkeypatch,
        rows=_rows(),
        days=[
            _DayRow(datetime.date(2026, 1, 1), mapped=2, validated=0),
            _DayRow(datetime.date(2026, 1, 2), mapped=5, validated=1),
        ],
        on_users=True,
    )
    evidence = asyncio.run(
        contributions.get_project_contributions_evidence(7, 5, db=None)
    )

    assert evidence.status == "OK"
    block = evidence.to_prompt_block()
    assert "operation: get_project_contributions" in block
    assert "contributors (complete list, 3 items):" in block
    assert "1. alice | mapped: 12 | validated: 3 | bad_imagery: 1" in block
    assert "2. manjita pandey | mapped: 4 | validated: 1" in block
    assert "your_contributions_on_this_project: mapped: 4 | validated: 1" in block
    assert "contributions_by_day (complete list, 2 days):" in block
    # Newest day first.
    assert block.index("2026-01-02 | mapped: 5") < block.index("2026-01-01 | mapped: 2")


def test_contributors_asker_not_a_contributor(monkeypatch):
    _patch(monkeypatch, rows=_rows(), on_users=True, username="nobody")
    evidence = asyncio.run(
        contributions.get_project_contributions_evidence(7, 5, db=None)
    )

    block = evidence.to_prompt_block()
    assert "your_contributions_on_this_project: none yet" in block


def test_contributors_cap_discloses_top_slice(monkeypatch):
    rows = [_UserRow(f"user{i}", mapped=i, total=i) for i in range(25, 0, -1)]
    _patch(monkeypatch, rows=rows, on_users=False)
    evidence = asyncio.run(
        contributions.get_project_contributions_evidence(7, 5, db=None)
    )

    block = evidence.to_prompt_block()
    assert "contributors (top 20 of 25, by total tasks):" in block
    assert "1. user25" in block
    assert "20. user6" in block
    assert "user5" not in block


def test_contributors_days_capped_newest_first(monkeypatch):
    import datetime

    days = [
        _DayRow(datetime.date(2026, 1, d), mapped=d, validated=0) for d in range(1, 21)
    ]
    _patch(monkeypatch, rows=_rows(), days=days, on_users=False)
    evidence = asyncio.run(
        contributions.get_project_contributions_evidence(7, 5, db=None)
    )

    block = evidence.to_prompt_block()
    assert "contributions_by_day (last 14 of 20 days):" in block
    assert "2026-01-20 | mapped: 20" in block
    assert "2026-01-07 | mapped: 7" in block
    assert "2026-01-06 | mapped: 6" not in block


def test_contributors_unavailable_when_primary_fails(monkeypatch):
    _patch(monkeypatch, contribs_raise=True)
    evidence = asyncio.run(
        contributions.get_project_contributions_evidence(7, 5, db=None)
    )

    assert evidence.status == "UNAVAILABLE"
    assert evidence.to_prompt_block() == ""


def test_contributors_degrades_when_days_fail(monkeypatch):
    _patch(monkeypatch, rows=_rows(), days_raise=True, on_users=False)
    evidence = asyncio.run(
        contributions.get_project_contributions_evidence(7, 5, db=None)
    )

    block = evidence.to_prompt_block()
    assert evidence.status == "OK"
    assert "contributors (complete list, 3 items):" in block
    assert "contributions_by_day" not in block


def test_contributors_unauthorized_renders_nothing(monkeypatch):
    _patch(monkeypatch, auth="UNAUTHORIZED")
    evidence = asyncio.run(
        contributions.get_project_contributions_evidence(7, 5, db=None)
    )

    assert evidence.status == "UNAUTHORIZED"
    assert evidence.to_prompt_block() == ""
