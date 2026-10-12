"""Evidence invariants for the user-OSM-stats op (external OSM, mocked)."""

import asyncio
from dataclasses import dataclass
from typing import Optional

import chat.retrieval.domain.user_osm_stats as osm


@dataclass
class _User:
    username: Optional[str]


@dataclass
class _OsmDTO:
    account_created: Optional[str] = None
    changeset_count: Optional[int] = None


def _patch(monkeypatch, *, user=None, dto=None, fetch_raise=False):
    import backend.models.postgis.user as user_module
    from backend.services.users.user_service import UserService

    async def _get_by_id(user_id, db):
        return user

    async def _osm_details(username, db):
        if fetch_raise:
            raise RuntimeError("osm unreachable")
        return dto

    monkeypatch.setattr(user_module.User, "get_by_id", _get_by_id)
    monkeypatch.setattr(UserService, "get_osm_details_for_user", _osm_details)


def test_osm_details(monkeypatch):
    _patch(
        monkeypatch,
        user=_User("manjita pandey"),
        dto=_OsmDTO(account_created="2018-06-01", changeset_count=421),
    )
    evidence = asyncio.run(osm.get_user_osm_stats_evidence(7, db=None))

    assert evidence.status == "OK"
    block = evidence.to_prompt_block()
    assert "operation: get_user_osm_stats" in block
    assert "osm_username: manjita pandey" in block
    assert "osm_account_created: 2018-06-01" in block
    assert "osm_changeset_count: 421" in block


def test_osm_missing_user_is_not_found(monkeypatch):
    _patch(monkeypatch, user=None)
    evidence = asyncio.run(osm.get_user_osm_stats_evidence(7, db=None))

    assert evidence.status == "NOT_FOUND"
    assert evidence.to_prompt_block() == ""


def test_osm_unreachable_is_unavailable(monkeypatch):
    _patch(monkeypatch, user=_User("manjita pandey"), fetch_raise=True)
    evidence = asyncio.run(osm.get_user_osm_stats_evidence(7, db=None))

    assert evidence.status == "UNAVAILABLE"
    assert evidence.to_prompt_block() == ""
