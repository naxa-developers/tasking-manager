"""Unit tests for the turn-debug report builders (no DB, no LLM)."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest

from chat.retrieval.debug_report import (
    SECTIONS,
    build_decisions,
    canned_answer,
    kb_to_dict,
    render_human,
    resolve_sections,
    scored_to_dict,
    to_json,
)
from chat.retrieval.domain.routing import route_query


@dataclass
class _FakeNode:
    id_: str
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class _FakeScored:
    node: _FakeNode
    fused_score: float = 0.03
    vector_rank: Optional[int] = 1
    bm25_rank: Optional[int] = None


@dataclass
class _FakeResp:
    results: List[_FakeScored]
    candidate_count: int = 1
    denied_count: int = 0
    degraded: bool = False
    degraded_reason: Optional[str] = None
    timing_ms: int = 12
    mode: str = "hybrid"
    query: str = "q"


def test_resolve_sections_defaults_to_all():
    assert resolve_sections("") == SECTIONS
    assert resolve_sections("all") == SECTIONS


def test_resolve_sections_subset_and_unknown():
    assert resolve_sections("kb,answer") == ("kb", "answer")
    with pytest.raises(ValueError):
        resolve_sections("nope")


def test_scored_to_dict_allowlists_fields():
    scored = _FakeScored(
        node=_FakeNode(
            id_="kb-1",
            text="A" * 500,
            metadata={
                "title": "FAQ",
                "doc_id": "faq",
                "node_heading": "Register",
                "source_refs": [{"path": "docs/faq.md"}],
                "provenance": {"commit": "abc123"},
            },
        )
    )
    item = scored_to_dict(scored, snippet_chars=50)
    assert item["node_id"] == "kb-1"
    assert item["title"] == "FAQ"
    assert item["heading"] == "Register"
    assert item["commit"] == "abc123"
    assert len(item["snippet"]) <= 51
    assert item["snippet"].endswith("…")


def test_kb_to_dict_summarises_threshold_and_low_confidence():
    resp = _FakeResp(results=[_FakeScored(node=_FakeNode(id_="kb-1", text="hi"))])
    kb = kb_to_dict(resp)
    assert kb["ran"] is True
    assert kb["top_score"] == 0.03
    assert kb["threshold"] > 0
    assert kb["low_confidence"] is False

    empty = kb_to_dict(_FakeResp(results=[], candidate_count=0))
    assert empty["low_confidence"] is True
    assert kb_to_dict(None) == {"ran": False}


def test_build_decisions_marks_created_route():
    question = "how many projects have i created?"
    decisions = build_decisions(question, route_query(question))
    assert decisions["route"] == "DOMAIN"
    assert decisions["ops"] == ["user_projects_created"]
    assert decisions["guardrail"]["verdict"] == "ok"


def test_canned_answer_precedence():
    base: Dict[str, Any] = {
        "guardrail": {"verdict": "ok", "gate": "scope", "reason": ""},
        "smalltalk": False,
        "smalltalk_kind": None,
        "third_party_user": False,
        "third_party_username": None,
        "needs_project_id": False,
        "route": "KB",
    }
    assert canned_answer(
        {**base, "smalltalk": True, "smalltalk_kind": "greeting"}, False, True
    )
    assert canned_answer({**base, "needs_project_id": True}, False, True)
    assert canned_answer(
        {**base, "guardrail": {**base["guardrail"], "verdict": "unsafe"}}, False, True
    )
    assert canned_answer(
        {**base, "route": "DOMAIN", "domain_status": "NOT_FOUND"}, False, True
    )
    assert canned_answer(base, False, True) is not None
    assert canned_answer(base, True, False) is None


def test_render_human_and_json_are_serialisable():
    report: Dict[str, Any] = {
        "meta": {
            "question": "q",
            "user_id": 1,
            "top_k": 5,
            "history_turns": 0,
            "model": "m",
            "temperature": 0.0,
            "max_tokens": 512,
        },
        "decisions": {
            "guardrail": {"verdict": "ok", "gate": "scope", "reason": "r"},
            "smalltalk": False,
            "third_party_user": False,
            "needs_project_id": False,
            "route": "KB",
            "ops": [],
            "project_id": None,
            "filters": {},
        },
        "kb": {"ran": False},
        "domain": {"ran": False, "skipped": None},
        "prompt": {"ran": False},
        "answer": {"ran": False, "reason": "generation not requested"},
    }
    text = render_human(report)
    assert "TMBot turn debug" in text
    assert "route     : KB" in text
    payload = to_json(report)
    assert '"question": "q"' in payload
