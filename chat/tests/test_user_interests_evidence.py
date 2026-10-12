"""Evidence invariants for the user-interests op."""

import asyncio
from dataclasses import dataclass
from typing import List, Optional

import chat.retrieval.domain.user_interests as interests


@dataclass
class _Rate:
    name: Optional[str]
    rate: Optional[float]


@dataclass
class _Interest:
    name: Optional[str]


class _RatesDTO:
    def __init__(self, rates: List[_Rate]):
        self.rates = rates


class _AllDTO:
    def __init__(self, names: List[str]):
        self.interests = [_Interest(n) for n in names]


def _patch(monkeypatch, *, rates=None, names=None, rates_raise=False, all_raise=False):
    from backend.services.interests_service import InterestService

    async def _compute(user_id, db):
        if rates_raise:
            raise RuntimeError("boom")
        return _RatesDTO(rates or [])

    async def _all(db):
        if all_raise:
            raise RuntimeError("boom")
        return _AllDTO(names or [])

    monkeypatch.setattr(InterestService, "compute_contributions_rate", _compute)
    monkeypatch.setattr(InterestService, "get_all_interests", _all)


def test_interests_rates_and_catalog(monkeypatch):
    _patch(
        monkeypatch,
        rates=[_Rate("buildings", 0.625), _Rate("roads", 0.375)],
        names=["buildings", "roads", "waterways"],
    )
    evidence = asyncio.run(interests.get_user_interests_evidence(7, db=None))

    assert evidence.status == "OK"
    block = evidence.to_prompt_block()
    assert "operation: get_user_interests" in block
    assert "interest_rates (complete list, 2 items):" in block
    assert "1. buildings: 0.625" in block
    assert "2. roads: 0.375" in block
    assert "interests (complete list, 3 items):" in block
    assert "1. buildings" in block


def test_interests_empty_rates_are_ok(monkeypatch):
    _patch(monkeypatch, rates=[], names=["buildings"])
    evidence = asyncio.run(interests.get_user_interests_evidence(7, db=None))

    block = evidence.to_prompt_block()
    assert evidence.status == "OK"
    assert "interest_rates" not in block
    assert "interests (complete list, 1 items):" in block


def test_interests_unavailable_when_rates_fail(monkeypatch):
    _patch(monkeypatch, rates_raise=True)
    evidence = asyncio.run(interests.get_user_interests_evidence(7, db=None))

    assert evidence.status == "UNAVAILABLE"
    assert evidence.to_prompt_block() == ""


def test_interests_degrades_when_catalog_fails(monkeypatch):
    _patch(monkeypatch, rates=[_Rate("roads", 1.0)], all_raise=True)
    evidence = asyncio.run(interests.get_user_interests_evidence(7, db=None))

    block = evidence.to_prompt_block()
    assert evidence.status == "OK"
    assert "1. roads: 1.0" in block
    assert "interests_total" not in block
