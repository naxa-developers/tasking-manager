"""The KB relevance gate: dense threshold plus lexical rescue."""

from __future__ import annotations

from chat.retrieval import RetrievalResponse, ScoredNode
from chat.retrieval_gate import (
    GateConfig,
    gate_decision,
    is_low_confidence,
    lexical_coverage,
)


class _Node:
    def __init__(self, text: str) -> None:
        self._text = text

    def get_content(self) -> str:
        return self._text


def _response(score, text: str = "validation review steps") -> RetrievalResponse:
    return RetrievalResponse(
        results=[
            ScoredNode(
                node=_Node(text),
                vector_score=score,
            )
        ],
        candidate_count=1,
        mode="hybrid",
        query="q",
    )


CFG = GateConfig(
    dense_threshold=0.5,
    dense_floor=0.3,
    coverage_threshold=0.75,
    arm_top_k=30,
)


def test_high_dense_score_is_allowed() -> None:
    decision = gate_decision(_response(0.72), "how do I validate?", CFG)
    assert decision.allow is True
    assert decision.reason == "dense_above_threshold"


def test_low_dense_score_is_rejected() -> None:
    decision = gate_decision(_response(0.11), "what is the weather?", CFG)
    assert decision.allow is False
    assert decision.reason == "below_threshold"


def test_lexical_coverage_can_rescue_between_floor_and_threshold() -> None:
    decision = gate_decision(
        _response(0.34, "validate task review steps for mapping"),
        "how do I validate a task?",
        CFG,
    )
    assert decision.allow is True
    assert decision.reason == "lexical_rescue"
    assert decision.coverage >= CFG.coverage_threshold


def test_missing_dense_score_does_not_reject() -> None:
    decision = gate_decision(_response(None), "how do I validate?", CFG)
    assert decision.allow is True
    assert decision.reason == "dense_score_missing"


def test_empty_results_are_low_confidence() -> None:
    response = RetrievalResponse(results=[], candidate_count=0, mode="hybrid", query="q")
    assert is_low_confidence(response, "anything", CFG) is True
    assert gate_decision(response, "anything", CFG).reason == "no_results"


def test_lexical_coverage_ignores_stopwords() -> None:
    assert lexical_coverage("how do I validate a task?", "validate task") == 1.0
    assert lexical_coverage("how do I validate a task?", "unrelated text") == 0.0
