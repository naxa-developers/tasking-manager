"""Evidence invariants for the managed-organisation projects op."""

import asyncio
from dataclasses import dataclass
from typing import Any, List

from chat.retrieval.domain.user_orgs import get_user_org_projects_evidence


@dataclass
class _FakeUser:
    id: int


@dataclass
class _FakeOrg:
    name: str


@dataclass
class _FakePagination:
    total: int


@dataclass
class _FakeSearchResults:
    pagination: _FakePagination
    results: List[Any]


class _FakeProjectDTO:
    def __init__(self, project_id, name, status="PUBLISHED"):
        self.project_id = project_id
        self.name = name
        self.status = status


def _patch(monkeypatch, user, orgs, search_results):
    import backend.models.postgis.organisation as org_module
    import backend.models.postgis.user as user_module
    import backend.services.project_search_service as search_module

    async def _get_by_id(user_id, db):
        return user

    async def _orgs(user_id, db):
        return orgs

    async def _search(search_dto, user_obj, db):
        return search_results

    monkeypatch.setattr(user_module.User, "get_by_id", _get_by_id)
    monkeypatch.setattr(
        org_module.Organisation, "get_organisations_managed_by_user", _orgs
    )
    monkeypatch.setattr(search_module.ProjectSearchService, "search_projects", _search)


def test_no_managed_orgs_reports_none(monkeypatch):
    _patch(monkeypatch, _FakeUser(id=1), [], None)
    evidence = asyncio.run(get_user_org_projects_evidence(1, object()))

    assert evidence.status == "OK"
    block = evidence.to_prompt_block()
    assert "organisations_managed_by_you: none" in block
    assert "does not manage any organisation" in block


def test_managed_org_lists_running_projects(monkeypatch):
    results = _FakeSearchResults(
        pagination=_FakePagination(total=7),
        results=[_FakeProjectDTO(122, "usa-dc"), _FakeProjectDTO(123, "ru-moscow")],
    )
    _patch(monkeypatch, _FakeUser(id=2), [_FakeOrg(name="Naxa Test ORG")], results)
    evidence = asyncio.run(get_user_org_projects_evidence(2, object()))

    assert evidence.status == "OK"
    block = evidence.to_prompt_block()
    assert "organisations_managed_by_you: 1" in block
    assert (
        "organisation: Naxa Test ORG | projects_running_by_this_organisation: 7"
        in block
    )
    assert "#122 usa-dc" in block
    assert "#123 ru-moscow" in block
    assert "task_history" not in block


def test_missing_user_is_not_found(monkeypatch):
    _patch(monkeypatch, None, [], None)
    evidence = asyncio.run(get_user_org_projects_evidence(404, object()))

    assert evidence.status == "NOT_FOUND"
    assert evidence.to_prompt_block() == ""
