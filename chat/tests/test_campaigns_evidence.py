"""Evidence invariants for the campaigns op.

Mirrors ``CampaignService.get_project_campaigns_as_dto`` when the question
names a project and ``CampaignService.get_all_campaigns`` for the site-wide
list.
"""

import asyncio
from dataclasses import dataclass
from typing import List, Optional

import chat.retrieval.domain.campaigns as campaigns


@dataclass
class _CampRow:
    id: Optional[int]
    name: Optional[str] = None


class _ListDTO:
    def __init__(self, rows: List[_CampRow]):
        self.campaigns = rows


def _patch(
    monkeypatch,
    *,
    auth="OK",
    rows=None,
    project_raise=False,
    global_raise=False,
):
    async def _authorize(user_id, project_id, db):
        return auth, (object() if auth == "OK" else None)

    monkeypatch.setattr(campaigns, "authorize_project", _authorize)

    from backend.services.campaign_service import CampaignService

    async def _project_campaigns(project_id, db):
        if project_raise:
            raise RuntimeError("boom")
        return _ListDTO(rows or [])

    async def _all_campaigns(db):
        if global_raise:
            raise RuntimeError("boom")
        return _ListDTO(rows or [])

    monkeypatch.setattr(
        CampaignService, "get_project_campaigns_as_dto", _project_campaigns
    )
    monkeypatch.setattr(CampaignService, "get_all_campaigns", _all_campaigns)


def test_project_campaigns_list(monkeypatch):
    _patch(monkeypatch, rows=[_CampRow(3, "Health"), _CampRow(4, "Roads")])
    evidence = asyncio.run(campaigns.get_campaigns_evidence(7, 5, db=None))

    assert evidence.status == "OK"
    block = evidence.to_prompt_block()
    assert "operation: get_campaigns" in block
    assert "project_id: 5" in block
    assert "project_campaigns (complete list, 2 items):" in block
    assert "1. #3 Health" in block
    assert "2. #4 Roads" in block


def test_all_campaigns_without_project(monkeypatch):
    _patch(monkeypatch, rows=[_CampRow(1, "HOT")])
    evidence = asyncio.run(campaigns.get_campaigns_evidence(7, None, db=None))

    block = evidence.to_prompt_block()
    assert "project_id" not in block  # optional context omitted when unscoped
    assert "campaigns (complete list, 1 items):" in block
    assert "1. #1 HOT" in block


def test_campaigns_empty_project(monkeypatch):
    _patch(monkeypatch, rows=[])
    evidence = asyncio.run(campaigns.get_campaigns_evidence(7, 5, db=None))

    block = evidence.to_prompt_block()
    assert "project_campaigns: none" in block


def test_campaigns_unavailable_on_failure(monkeypatch):
    _patch(monkeypatch, project_raise=True)
    evidence = asyncio.run(campaigns.get_campaigns_evidence(7, 5, db=None))

    assert evidence.status == "UNAVAILABLE"
    assert evidence.to_prompt_block() == ""


def test_campaigns_unauthorized_project_renders_nothing(monkeypatch):
    _patch(monkeypatch, auth="UNAUTHORIZED")
    evidence = asyncio.run(campaigns.get_campaigns_evidence(7, 5, db=None))

    assert evidence.status == "UNAUTHORIZED"
    assert evidence.to_prompt_block() == ""
