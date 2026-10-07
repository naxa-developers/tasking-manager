"""Strict retrieval: no partial result may leave ``retrieve()``.

Policy: every KB turn runs both arms (vector + BM25) or raises
``RetrievalUnavailable``. ``kind="too_large"`` marks llama.cpp size refusals
(actionable for the user, never retried); everything else is "unavailable".
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from llama_index.core.schema import TextNode

from chat.retrieval.query_kb import (
    RankedCandidates,
    RetrievalUnavailable,
    Retriever,
)


def _run(coro):
    return asyncio.run(coro)


def _node(nid):
    return TextNode(text=f"text for {nid}", id_=nid, metadata={})


def _ranked(ids=(), error=None):
    return RankedCandidates(
        list(ids),
        {nid: 1.0 - i * 0.1 for i, nid in enumerate(ids)},
        error,
        {nid: _node(nid) for nid in ids},
    )


def _retriever(vector=None, bm25=None, load_error=None):
    ret = Retriever([], {}, None, load_error=load_error)
    ret.vector_candidates = vector or (lambda q: _ranked())
    ret.bm25_candidates = bm25 or (lambda q: _ranked())
    return ret


class TestStrictRetrievalRaises:
    def test_vector_error_retries_once_then_raises_unavailable(self):
        vector = Mock(return_value=_ranked(error="connection refused"))
        bm25 = Mock(return_value=_ranked(["a"]))
        ret = _retriever(vector=vector, bm25=bm25)

        with pytest.raises(RetrievalUnavailable) as excinfo:
            ret.retrieve("how do I lock a task?")

        assert excinfo.value.kind == "unavailable"
        assert "vector search failed" in str(excinfo.value)
        assert vector.call_count == 2  # one transient retry

    def test_size_error_raises_too_large_without_retry(self):
        message = (
            "InternalServerError: OpenAIException - Error code: 500 - "
            "{'error': {'message': 'input (3403 tokens) is too large to "
            "process. increase the physical batch size (current batch size: "
            "1024)'}}"
        )
        vector = Mock(return_value=_ranked(error=message))
        ret = _retriever(vector=vector)

        with pytest.raises(RetrievalUnavailable) as excinfo:
            ret.retrieve("a " * 3000)

        assert excinfo.value.kind == "too_large"
        assert vector.call_count == 1  # never retried

    def test_bm25_error_raises_unavailable(self):
        vector = Mock(return_value=_ranked(["a"]))
        bm25 = Mock(return_value=_ranked(error="bm25 exploded"))
        ret = _retriever(vector=vector, bm25=bm25)

        with pytest.raises(RetrievalUnavailable) as excinfo:
            ret.retrieve("how do I lock a task?")

        assert excinfo.value.kind == "unavailable"
        assert "BM25 search failed" in str(excinfo.value)

    def test_both_arms_empty_raises(self):
        ret = _retriever()  # both arms return no ids and no error

        with pytest.raises(RetrievalUnavailable, match="no candidates"):
            ret.retrieve("how do I lock a task?")

    def test_load_error_raises(self):
        ret = _retriever(load_error="chunks.json missing at /somewhere")

        with pytest.raises(RetrievalUnavailable, match="index load error"):
            ret.retrieve("how do I lock a task?")


class TestStrictRetrievalHappyPath:
    def test_healthy_hybrid_returns_results_and_no_degraded(self):
        ret = _retriever(
            vector=lambda q: _ranked(["a"]),
            bm25=lambda q: _ranked(["b"]),
        )

        resp = ret.retrieve("how do I lock a task?", top_k=5)

        assert resp.degraded is False
        assert resp.degraded_reason is None
        assert {r.node.id_ for r in resp.results} == {"a", "b"}
        assert resp.candidate_count == 2

    def test_transient_vector_blip_recovers_on_retry(self):
        vector = Mock(side_effect=[_ranked(error="timeout"), _ranked(["a"])])
        ret = _retriever(vector=vector, bm25=Mock(return_value=_ranked(["b"])))

        resp = ret.retrieve("how do I lock a task?")

        assert vector.call_count == 2
        assert {r.node.id_ for r in resp.results} == {"a", "b"}


class TestChatApiRetrievalErrorMapping:
    """session_chat maps strict-retrieval failures to 422/503 bodies."""

    def _chat_with(self, exc):
        from chat.api.resources import session_chat

        req = SimpleNamespace(question="how do I lock a task?", stream=True)
        allowed = SimpleNamespace(allowed=True, retry_after=0)
        with (
            patch("chat.api.resources.RagService.is_available", return_value=True),
            patch(
                "chat.api.resources.check_chat_rate_limit",
                new=AsyncMock(return_value=allowed),
            ),
            patch(
                "chat.api.resources.RagService.chat",
                new=AsyncMock(side_effect=exc),
            ),
        ):
            return _run(session_chat(1, req, user=SimpleNamespace(id=2), db=None))

    def test_too_large_maps_to_422_question_too_long(self):
        resp = self._chat_with(
            RetrievalUnavailable(
                "vector search failed: input is too large to process",
                kind="too_large",
            )
        )

        assert resp.status_code == 422
        body = json.loads(resp.body)
        assert body["SubCode"] == "RAGQuestionTooLong"
        assert "too long" in body["Error"]

    def test_unavailable_maps_to_503_retrieval_failed(self):
        resp = self._chat_with(RetrievalUnavailable("vector search failed: down"))

        assert resp.status_code == 503
        body = json.loads(resp.body)
        assert body["SubCode"] == "RAGRetrievalFailed"
