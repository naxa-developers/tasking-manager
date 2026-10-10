"""Pins for the chat API error bodies: status, raw JSON, key order included."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from chat.api.resources import session_chat
from chat.retrieval.query_kb import RetrievalUnavailable
from chat.turn.errors import RagAnswerFailed


def _run(coro):
    return asyncio.run(coro)


def _chat(*, available=True, rate=None, chat_error=None):
    req = SimpleNamespace(question="how do I lock a task?", stream=True)
    user = SimpleNamespace(id=2)
    allowed = SimpleNamespace(allowed=True, retry_after=0)
    with (
        patch("chat.api.resources.RagService.is_available", return_value=available),
        patch(
            "chat.api.resources.check_chat_rate_limit",
            new=AsyncMock(return_value=rate if rate is not None else allowed),
        ),
        patch(
            "chat.api.resources.RagService.chat",
            new=AsyncMock(side_effect=chat_error),
        ),
    ):
        return _run(session_chat(1, req, user=user, db=None))


def test_unavailable_body_is_pinned():
    resp = _chat(available=False)
    assert resp.status_code == 503
    assert resp.body.decode() == (
        '{"Error":"RAG not configured",'
        '"detail":"RAG is not available on this deployment.",'
        '"SubCode":"RAGUnavailable"}'
    )


def test_rate_limited_body_and_retry_after_are_pinned():
    resp = _chat(rate=SimpleNamespace(allowed=False, retry_after=17))
    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == "17"
    assert resp.body.decode() == (
        '{"Error":"Rate limit exceeded",'
        '"detail":"Too many chat messages. Try again in 17 seconds.",'
        '"SubCode":"RAGRateLimited"}'
    )


def test_answer_failed_body_is_pinned():
    resp = _chat(chat_error=RagAnswerFailed())
    assert resp.status_code == 503
    assert resp.body.decode() == (
        '{"Error":"Answer generation failed","SubCode":"RAGAnswerFailed"}'
    )


def test_question_too_long_body_is_pinned():
    resp = _chat(chat_error=RetrievalUnavailable("too big", kind="too_large"))
    assert resp.status_code == 422
    assert resp.body.decode() == (
        '{"Error":"This message is too long for search — please shorten it.",'
        '"SubCode":"RAGQuestionTooLong"}'
    )


def test_retrieval_failed_body_is_pinned():
    resp = _chat(chat_error=RetrievalUnavailable("down"))
    assert resp.status_code == 503
    assert resp.body.decode() == (
        '{"Error":"Knowledge base search is temporarily unavailable. Please try again.",'
        '"SubCode":"RAGRetrievalFailed"}'
    )
