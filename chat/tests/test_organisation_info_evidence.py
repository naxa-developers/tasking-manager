"""Evidence invariants for the organisation-info op.

Mirrors ``OrganisationService.get_organisation_by_name`` (name lookup), the
organisation DTO, the statistics endpoint (project counts), and the
organisation campaigns list. The name arrives via the route's ``organisation``
filter.
"""

import asyncio
from dataclasses import dataclass
from typing import List, Optional

import chat.retrieval.domain.organisation_info as org_info


@dataclass
class _Org:
    id: int


@dataclass
class _OrgDTO:
    organisation_id: int
    name: Optional[str]
    slug: Optional[str] = None
    url: Optional[str] = None
    description: Optional[str] = None


@dataclass
class _ProjectsStats:
    published: Optional[int] = None
    draft: Optional[int] = None
    archived: Optional[int] = None


@dataclass
class _Stats:
    projects: Optional[_ProjectsStats] = None


@dataclass
class _Camp:
    name: Optional[str]


class _CampList:
    def __init__(self, rows: List[_Camp]):
        self.campaigns = rows


def _patch(
    monkeypatch,
    *,
    dto=None,
    not_found=False,
    lookup_raise=False,
    stats_raise=False,
    campaigns_raise=False,
):
    from backend.exceptions import NotFound
    from backend.services.campaign_service import CampaignService
    from backend.services.organisation_service import OrganisationService

    async def _by_name(name, db):
        if not_found:
            raise NotFound(sub_code="ORGANISATION_NOT_FOUND", organisation_name=name)
        if lookup_raise:
            raise RuntimeError("boom")
        return _Org(id=1)

    async def _by_id_as_dto(organisation_id, user_id, omit_managers, db):
        return dto

    async def _stats(organisation_id, db, year=None):
        if stats_raise:
            raise RuntimeError("boom")
        return _Stats(projects=_ProjectsStats(published=12, draft=3, archived=5))

    async def _org_campaigns(organisation_id, db):
        if campaigns_raise:
            raise RuntimeError("boom")
        return _CampList([_Camp("Health"), _Camp("Roads")])

    monkeypatch.setattr(OrganisationService, "get_organisation_by_name", _by_name)
    monkeypatch.setattr(
        OrganisationService, "get_organisation_by_id_as_dto", _by_id_as_dto
    )
    monkeypatch.setattr(OrganisationService, "get_organisation_stats", _stats)
    monkeypatch.setattr(
        CampaignService, "get_organisation_campaigns_as_dto", _org_campaigns
    )


def _filters(name="HOT"):
    return {"organisation": name}


def test_org_info_full_profile(monkeypatch):
    _patch(
        monkeypatch,
        dto=_OrgDTO(
            organisation_id=1,
            name="HOT",
            slug="hot",
            url="https://hotosm.org",
            description="Humanitarian OpenStreetMap Team",
        ),
    )
    evidence = asyncio.run(
        org_info.get_organisation_info_evidence(7, None, db=None, filters=_filters())
    )

    assert evidence.status == "OK"
    block = evidence.to_prompt_block()
    assert "operation: get_organisation_info" in block
    assert "organisation_name: HOT" in block
    assert "organisation_id: 1" in block
    assert "slug: hot" in block
    assert "url: https://hotosm.org" in block
    assert "description: Humanitarian OpenStreetMap Team" in block
    assert "organisation_projects: 12 published, 3 draft, 5 archived" in block
    assert "organisation_campaigns: Health, Roads" in block


def test_org_info_not_found(monkeypatch):
    _patch(monkeypatch, not_found=True)
    evidence = asyncio.run(
        org_info.get_organisation_info_evidence(7, None, db=None, filters=_filters())
    )

    assert evidence.status == "NOT_FOUND"
    assert evidence.to_prompt_block() == ""


def test_org_info_degrades_when_stats_and_campaigns_fail(monkeypatch):
    _patch(
        monkeypatch,
        dto=_OrgDTO(organisation_id=1, name="HOT"),
        stats_raise=True,
        campaigns_raise=True,
    )
    evidence = asyncio.run(
        org_info.get_organisation_info_evidence(7, None, db=None, filters=_filters())
    )

    block = evidence.to_prompt_block()
    assert evidence.status == "OK"
    assert "organisation_projects" not in block
    assert "organisation_campaigns" not in block


def test_org_info_unavailable_on_lookup_failure(monkeypatch):
    _patch(monkeypatch, lookup_raise=True)
    evidence = asyncio.run(
        org_info.get_organisation_info_evidence(7, None, db=None, filters=_filters())
    )

    assert evidence.status == "UNAVAILABLE"
    assert evidence.to_prompt_block() == ""


def test_org_info_without_filter_is_not_found(monkeypatch):
    _patch(monkeypatch, dto=_OrgDTO(organisation_id=1, name="HOT"))
    evidence = asyncio.run(
        org_info.get_organisation_info_evidence(7, None, db=None, filters={})
    )

    assert evidence.status == "NOT_FOUND"
    assert evidence.to_prompt_block() == ""
