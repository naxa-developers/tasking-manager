"""The routing corpus and the eval scorer stay well-formed."""

from __future__ import annotations

from types import SimpleNamespace

from chat.retrieval.scripts.eval_router import (
    CORPUS_PATH,
    guardrail_pass,
    load_cases,
    route_pass,
    validate_cases,
)


def _cases():
    return load_cases(CORPUS_PATH)


def test_corpus_is_well_formed():
    cases = _cases()
    validate_cases(cases)
    assert len(cases) == 87
    assert len({case["id"] for case in cases}) == 87
    assert any(case["expected_route"] for case in cases)
    assert any(case["expected_guardrail"] for case in cases)


def test_route_scoring_uses_sets_for_operations():
    case = {
        "expected_route": "DOMAIN",
        "expected_ops": ["stats", "teams"],
        "expected_filters": {},
        "expected_project_id": 42,
        "expected_needs_project_id": False,
    }
    route = SimpleNamespace(
        route="DOMAIN",
        ops=("teams", "stats"),
        filters={},
        project_id=42,
        needs_project_id=False,
    )
    assert route_pass(case, route)["pass"] is True


def test_route_scoring_detects_a_wrong_field():
    case = {
        "expected_route": "BOTH",
        "expected_ops": ["stats"],
        "expected_filters": {},
        "expected_project_id": 42,
        "expected_needs_project_id": False,
    }
    route = SimpleNamespace(
        route="DOMAIN",
        ops=("stats",),
        filters={},
        project_id=42,
        needs_project_id=False,
    )
    metrics = route_pass(case, route)
    assert metrics["route"] is False
    assert metrics["pass"] is False


def test_guardrail_scoring_matches_the_pipeline_gates():
    cases = {case["id"]: case for case in _cases()}
    assert guardrail_pass(cases["H1"]) is True  # unsafe
    assert guardrail_pass(cases["H3"]) is True  # third-party
    assert guardrail_pass(cases["H4"]) is True  # out_of_scope
    assert guardrail_pass(cases["H5"]) is True  # smalltalk
