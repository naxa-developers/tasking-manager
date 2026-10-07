"""Reciprocal-rank-fusion parity: ranking, scores, ties, dedup, retry, metadata.

Expected values were captured from the previous llama-index reciprocal-rerank
handoff; this pins the local implementation to the same outputs (k=60, per-arm
score ranking, content-hash keying, stable tie order).
"""

from __future__ import annotations

import pytest
from llama_index.core.schema import TextNode

from chat.retrieval.query_kb import (
    RankedCandidates,
    RetrievalUnavailable,
    Retriever,
)


def _node_map(*ids):
    return {nid: TextNode(text=f"text-{nid}", id_=nid, metadata={}) for nid in ids}


def _retriever(node_map, vec, bm25):
    retriever = Retriever(nodes=[], node_map=node_map, bm25=None)
    retriever.vector_candidates = vec if callable(vec) else (lambda question: vec)
    retriever.bm25_candidates = bm25 if callable(bm25) else (lambda question: bm25)
    return retriever


def _record(response):
    return [
        (
            r.node.id_,
            r.fused_score,
            r.vector_rank,
            r.bm25_rank,
            r.vector_score,
            r.bm25_score,
        )
        for r in response.results
    ]


def _mix_fixture():
    nodes = _node_map("a", "b", "c", "d")
    vec = RankedCandidates(
        ["a", "b", "c"],
        {"a": 0.9, "b": 0.8, "c": 0.7},
        None,
        {"a": nodes["a"], "b": nodes["b"], "c": nodes["c"]},
    )
    bm25 = RankedCandidates(["c", "d"], {"c": 9.0, "d": 7.0}, None, {})
    return nodes, vec, bm25


def test_fusion_ranking_scores_and_metadata():
    nodes, vec, bm25 = _mix_fixture()
    resp = _retriever(nodes, vec, bm25).retrieve("q")

    assert resp.mode == "hybrid"
    assert resp.query == "q"
    assert resp.candidate_count == 4
    assert _record(resp) == [
        ("c", 1 / 62 + 1 / 60, 3, 1, 0.7, 9.0),
        ("a", 1 / 60, 1, None, 0.9, None),
        ("b", 1 / 61, 2, None, 0.8, None),
        ("d", 1 / 61, None, 2, None, 7.0),
    ]
    # Vector-store nodes are preferred; id-only BM25 entries fall back to node_map.
    assert resp.results[0].node is nodes["c"]
    assert resp.results[3].node is nodes["d"]


def test_fusion_respects_top_k():
    nodes, vec, bm25 = _mix_fixture()
    resp = _retriever(nodes, vec, bm25).retrieve("q", top_k=2)

    assert _record(resp) == [
        ("c", 1 / 62 + 1 / 60, 3, 1, 0.7, 9.0),
        ("a", 1 / 60, 1, None, 0.9, None),
    ]


def test_fusion_collapses_duplicate_content_by_hash():
    nodes = _node_map("x1", "x2", "y1")
    nodes["x2"].text = nodes["x1"].text  # same content + metadata -> same node hash
    vec = RankedCandidates(
        ["x1", "x2"],
        {"x1": 0.9, "x2": 0.1},
        None,
        {"x1": nodes["x1"], "x2": nodes["x2"]},
    )
    bm25 = RankedCandidates(["y1"], {"y1": 3.0}, None, {})

    resp = _retriever(nodes, vec, bm25).retrieve("q")

    assert _record(resp) == [
        ("x2", 1 / 60 + 1 / 61, 2, None, 0.1, None),
        ("y1", 1 / 60, None, 1, None, 3.0),
    ]


def test_fusion_tie_ordering_is_stable():
    nodes = _node_map("a", "b", "c")
    vec = RankedCandidates(
        ["a", "b"], {"a": 1.0, "b": 1.0}, None, {"a": nodes["a"], "b": nodes["b"]}
    )
    bm25 = RankedCandidates(["c"], {"c": 1.0}, None, {})

    resp = _retriever(nodes, vec, bm25).retrieve("q")

    assert _record(resp) == [
        ("a", 1 / 60, 1, None, 1.0, None),
        ("c", 1 / 60, None, 1, None, 1.0),
        ("b", 1 / 61, 2, None, 1.0, None),
    ]


def test_fusion_with_empty_vector_arm():
    nodes = _node_map("a", "b")
    vec = RankedCandidates([], {}, None, {})
    bm25 = RankedCandidates(["a", "b"], {"a": 2.0, "b": 1.0}, None, {})

    resp = _retriever(nodes, vec, bm25).retrieve("q")

    assert _record(resp) == [
        ("a", 1 / 60, None, 1, None, 2.0),
        ("b", 1 / 61, None, 2, None, 1.0),
    ]


def test_vector_retry_runs_once_more_and_matches_clean_run():
    nodes, vec, bm25 = _mix_fixture()
    calls = []

    def flaky_vec(question):
        calls.append(question)
        if len(calls) == 1:
            return RankedCandidates([], {}, "transient boom")
        return vec

    resp = _retriever(nodes, flaky_vec, bm25).retrieve("q")
    clean = _retriever(nodes, vec, bm25).retrieve("q")

    assert calls == ["q", "q"]
    assert _record(resp) == _record(clean)


def test_too_large_input_raises_without_retry():
    nodes = _node_map("a")
    calls = []

    def too_large(question):
        calls.append(question)
        return RankedCandidates([], {}, "input too large to process")

    bm25 = RankedCandidates(["a"], {"a": 1.0}, None, {})
    with pytest.raises(RetrievalUnavailable) as excinfo:
        _retriever(nodes, too_large, bm25).retrieve("q")

    assert excinfo.value.kind == "too_large"
    assert calls == ["q"]


def test_no_candidates_raises():
    empty = RankedCandidates([], {}, None, {})
    with pytest.raises(RetrievalUnavailable):
        _retriever({}, empty, empty).retrieve("q")
