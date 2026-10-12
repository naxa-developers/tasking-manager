"""Evidence invariants for the team-detail op.

Mirrors ``TeamService.get_team_as_dto`` (full form with members). The team id
arrives via the route's ``team_id`` filter. The join-requests count surfaces
only to org/general admins, mirroring the manager-facing endpoint.
"""

import asyncio
from dataclasses import dataclass
from typing import List, Optional

import chat.retrieval.domain.team_detail as team_detail


@dataclass
class _Member:
    username: Optional[str]


@dataclass
class _TeamDTO:
    team_id: int
    name: Optional[str] = "Roads team"
    organisation: Optional[str] = "HOT"
    visibility: Optional[str] = "PUBLIC"
    join_method: Optional[str] = "ANY"
    description: Optional[str] = "Validates roads"
    members: Optional[List[_Member]] = None
    is_org_admin: Optional[bool] = None
    is_general_admin: Optional[bool] = None


class _FakeDB:
    def __init__(self, pending: int = 0):
        self.pending = pending
        self.queries: List[str] = []

    async def fetch_one(self, query: str, values: Optional[dict] = None):
        self.queries.append(query)
        return {"n": self.pending}


def _patch(monkeypatch, *, dto=None, not_found=False, fetch_raise=False):
    from backend.exceptions import NotFound
    from backend.services.team_service import TeamService

    async def _get(team_id, user_id, abbreviated, db):
        if not_found:
            raise NotFound(sub_code="TEAM_NOT_FOUND", team_id=team_id)
        if fetch_raise:
            raise RuntimeError("boom")
        return dto

    monkeypatch.setattr(TeamService, "get_team_as_dto", _get)


def _filters(team_id="12"):
    return {"team_id": team_id}


def test_team_detail_with_members(monkeypatch):
    _patch(
        monkeypatch,
        dto=_TeamDTO(
            team_id=12,
            members=[_Member("alice"), _Member("bob")],
        ),
    )
    db = _FakeDB()
    evidence = asyncio.run(
        team_detail.get_team_detail_evidence(7, None, db=db, filters=_filters())
    )

    assert evidence.status == "OK"
    block = evidence.to_prompt_block()
    assert "operation: get_team_detail" in block
    assert "team_id: 12" in block
    assert "team_name: Roads team" in block
    assert "organisation: HOT" in block
    assert "visibility: PUBLIC" in block
    assert "join_method: ANY" in block
    assert "members (complete list, 2 items):" in block
    assert "1. alice" in block
    assert "2. bob" in block
    # Non-admin: no join-request count (manager-facing data).
    assert "pending_join_requests" not in block
    assert db.queries == []


def test_team_detail_admin_sees_pending_join_requests(monkeypatch):
    _patch(
        monkeypatch,
        dto=_TeamDTO(team_id=12, members=[_Member("alice")], is_org_admin=True),
    )
    db = _FakeDB(pending=3)
    evidence = asyncio.run(
        team_detail.get_team_detail_evidence(7, None, db=db, filters=_filters())
    )

    block = evidence.to_prompt_block()
    assert "pending_join_requests: 3" in block
    assert db.queries and "team_members" in db.queries[0]


def test_team_detail_empty_members(monkeypatch):
    _patch(monkeypatch, dto=_TeamDTO(team_id=12, members=[]))
    db = _FakeDB()
    evidence = asyncio.run(
        team_detail.get_team_detail_evidence(7, None, db=db, filters=_filters())
    )

    block = evidence.to_prompt_block()
    assert "members: none" in block


def test_team_detail_not_found(monkeypatch):
    _patch(monkeypatch, not_found=True)
    db = _FakeDB()
    evidence = asyncio.run(
        team_detail.get_team_detail_evidence(7, None, db=db, filters=_filters())
    )

    assert evidence.status == "NOT_FOUND"
    assert evidence.to_prompt_block() == ""


def test_team_detail_invalid_filter_is_not_found(monkeypatch):
    _patch(monkeypatch, dto=_TeamDTO(team_id=12))
    db = _FakeDB()
    evidence = asyncio.run(
        team_detail.get_team_detail_evidence(7, None, db=db, filters={"team_id": "x"})
    )

    assert evidence.status == "NOT_FOUND"
    assert evidence.to_prompt_block() == ""


def test_team_detail_unavailable_on_failure(monkeypatch):
    _patch(monkeypatch, fetch_raise=True)
    db = _FakeDB()
    evidence = asyncio.run(
        team_detail.get_team_detail_evidence(7, None, db=db, filters=_filters())
    )

    assert evidence.status == "UNAVAILABLE"
    assert evidence.to_prompt_block() == ""
