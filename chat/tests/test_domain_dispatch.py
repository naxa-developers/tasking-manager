"""Characterization tests for collect_evidence status precedence."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from chat.retrieval.domain.dispatch import _merge_status, collect_evidence
from chat.retrieval.domain.llm_router import DomainRoute


def _run(coro):
    return asyncio.run(coro)


def _evidence(status="OK", block="block", citation=None):
    return SimpleNamespace(
        status=status,
        authorized=status == "OK",
        to_prompt_block=lambda: block,
        to_citation=lambda: citation,
    )


def _fetcher(evidence=None, error=None):
    async def fetch(user_id, project_id, db):
        if error is not None:
            raise error
        return evidence

    return fetch


def _collect(ops, fetchers):
    route = DomainRoute(route="DOMAIN", project_id=5, ops=tuple(ops))
    return _run(collect_evidence(7, route, None, fetchers=fetchers))


def test_ok_mixed_with_unauthorized_reports_ok():
    outcome = _collect(
        ("stats", "teams"),
        {
            "stats": _fetcher(
                _evidence("OK", block="stats block", citation={"id": "c1"})
            ),
            "teams": _fetcher(_evidence("UNAUTHORIZED")),
        },
    )
    assert outcome.status == "OK"
    assert outcome.block == "stats block"
    assert outcome.citations == ({"id": "c1"},)
    assert outcome.project_id == 5
    assert outcome.route == "DOMAIN"


def test_unauthorized_beats_timeout():
    outcome = _collect(
        ("teams", "stats"),
        {
            "teams": _fetcher(_evidence("UNAUTHORIZED")),
            "stats": _fetcher(error=asyncio.TimeoutError()),
        },
    )
    assert outcome.status == "UNAUTHORIZED"
    assert outcome.block == ""
    assert outcome.citations == ()


def test_timeout_beats_unavailable():
    outcome = _collect(
        ("stats", "teams"),
        {
            "stats": _fetcher(error=asyncio.TimeoutError()),
            "teams": _fetcher(error=RuntimeError("boom")),
        },
    )
    assert outcome.status == "TIMEOUT"


def test_unavailable_beats_not_found():
    outcome = _collect(
        ("teams", "stats"),
        {
            "teams": _fetcher(error=RuntimeError("boom")),
            "stats": _fetcher(_evidence("NOT_FOUND")),
        },
    )
    assert outcome.status == "UNAVAILABLE"


def test_not_found_only():
    outcome = _collect(
        ("stats",),
        {"stats": _fetcher(_evidence("NOT_FOUND"))},
    )
    assert outcome.status == "NOT_FOUND"


def test_ok_survives_a_failed_op():
    outcome = _collect(
        ("teams", "stats"),
        {
            "teams": _fetcher(error=RuntimeError("boom")),
            "stats": _fetcher(_evidence("OK", block="stats block")),
        },
    )
    assert outcome.status == "OK"
    assert outcome.block == "stats block"


def test_unregistered_op_reports_unavailable():
    outcome = _collect(("stats",), {})
    assert outcome.status == "UNAVAILABLE"
    assert outcome.block == ""


def test_empty_ops_returns_route_defaults():
    outcome = _collect((), {})
    assert outcome.status is None
    assert outcome.block == ""
    assert outcome.citations == ()
    assert outcome.project_id == 5
    assert outcome.route == "DOMAIN"


@pytest.mark.parametrize(
    "statuses,expected",
    [
        ([], None),
        (["NOT_FOUND"], "NOT_FOUND"),
        (["NOT_FOUND", "UNAVAILABLE"], "UNAVAILABLE"),
        (["NOT_FOUND", "UNAVAILABLE", "TIMEOUT"], "TIMEOUT"),
        (["NOT_FOUND", "UNAVAILABLE", "TIMEOUT", "UNAUTHORIZED"], "UNAUTHORIZED"),
        (["NOT_FOUND", "UNAVAILABLE", "TIMEOUT", "UNAUTHORIZED", "OK"], "OK"),
        (["UNAUTHORIZED", "OK"], "OK"),
        (["TIMEOUT", "OK"], "OK"),
    ],
)
def test_merge_status_table(statuses, expected):
    assert _merge_status(list(statuses)) == expected
