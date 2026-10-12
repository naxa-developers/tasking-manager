"""Evidence invariants for the project-partners op."""

import asyncio
import datetime
from dataclasses import dataclass
from typing import List, Optional

import chat.retrieval.domain.project_partners as partners


@dataclass
class _PartnershipRow:
    partner_id: Optional[int]
    started_on: Optional[datetime.date] = None
    ended_on: Optional[datetime.date] = None


@dataclass
class _Partner:
    name: Optional[str]


def _patch(
    monkeypatch,
    *,
    auth="OK",
    rows=None,
    names=None,
    list_raise=False,
    partner_raise=False,
):
    async def _authorize(user_id, project_id, db):
        return auth, (object() if auth == "OK" else None)

    monkeypatch.setattr(partners, "authorize_project", _authorize)

    from backend.services.partner_service import PartnerService
    from backend.services.project_partnership_service import (
        ProjectPartnershipService,
    )

    async def _get(project_id, db):
        if list_raise:
            raise RuntimeError("boom")
        return rows or []

    async def _partner_by_id(partner_id, db):
        if partner_raise:
            raise RuntimeError("boom")
        return _Partner((names or {}).get(partner_id))

    monkeypatch.setattr(ProjectPartnershipService, "get_partnerships_by_project", _get)
    monkeypatch.setattr(PartnerService, "get_partner_by_id", _partner_by_id)


def test_partners_with_names_and_dates(monkeypatch):
    _patch(
        monkeypatch,
        rows=[
            _PartnershipRow(3, datetime.date(2025, 1, 1), None),
            _PartnershipRow(4, datetime.date(2025, 6, 1), datetime.date(2026, 1, 1)),
        ],
        names={3: "Red Cross", 4: "MSF"},
    )
    evidence = asyncio.run(partners.get_project_partners_evidence(7, 5, db=None))

    assert evidence.status == "OK"
    block = evidence.to_prompt_block()
    assert "operation: get_project_partners" in block
    assert "project_partners (complete list, 2 items):" in block
    assert "1. #3 Red Cross | started: 2025-01-01" in block
    assert "2. #4 MSF | started: 2025-06-01 | ended: 2026-01-01" in block


def test_partners_name_lookup_failure_still_lists(monkeypatch):
    _patch(
        monkeypatch,
        rows=[_PartnershipRow(3, datetime.date(2025, 1, 1))],
        partner_raise=True,
    )
    evidence = asyncio.run(partners.get_project_partners_evidence(7, 5, db=None))

    block = evidence.to_prompt_block()
    assert evidence.status == "OK"
    assert "1. #3 | started: 2025-01-01" in block


def test_partners_empty(monkeypatch):
    _patch(monkeypatch, rows=[])
    evidence = asyncio.run(partners.get_project_partners_evidence(7, 5, db=None))

    block = evidence.to_prompt_block()
    assert "project_partners: none" in block


def test_partners_unauthorized(monkeypatch):
    _patch(monkeypatch, auth="UNAUTHORIZED")
    evidence = asyncio.run(partners.get_project_partners_evidence(7, 5, db=None))

    assert evidence.status == "UNAUTHORIZED"
    assert evidence.to_prompt_block() == ""


def test_partners_unavailable_on_failure(monkeypatch):
    _patch(monkeypatch, list_raise=True)
    evidence = asyncio.run(partners.get_project_partners_evidence(7, 5, db=None))

    assert evidence.status == "UNAVAILABLE"
    assert evidence.to_prompt_block() == ""
