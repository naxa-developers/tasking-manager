"""Postgres-backed tests for the RAG chat rate limiter."""

import pytest
from httpx import AsyncClient

from chat.api import resources as rag_resources
from chat.dtos import RagChatResponseDTO
from chat.rate_limit import check_chat_rate_limit
from tests.api.helpers.test_helpers import (
    create_canned_user,
    generate_encoded_token,
    return_canned_user,
)


@pytest.mark.anyio
class TestChatRateLimitCounter:
    async def test_allows_up_to_limit_then_blocks(
        self, db_connection_fixture, monkeypatch
    ):
        monkeypatch.setenv("RAG_CHAT_RATE_LIMIT", "3")
        monkeypatch.setenv("RAG_CHAT_RATE_WINDOW_SECONDS", "60")
        db = db_connection_fixture

        for _ in range(3):
            decision = await check_chat_rate_limit(4242, db)
            assert decision.allowed

        blocked = await check_chat_rate_limit(4242, db)
        assert blocked.allowed is False
        assert blocked.retry_after >= 1

    async def test_window_expiry_resets_counter(
        self, db_connection_fixture, monkeypatch
    ):
        monkeypatch.setenv("RAG_CHAT_RATE_LIMIT", "1")
        monkeypatch.setenv("RAG_CHAT_RATE_WINDOW_SECONDS", "60")
        db = db_connection_fixture

        assert (await check_chat_rate_limit(4242, db)).allowed
        assert (await check_chat_rate_limit(4242, db)).allowed is False

        await db.execute(
            """
            UPDATE rag_rate_limits
            SET window_start = NOW() - INTERVAL '2 minutes'
            WHERE user_id = :user_id
            """,
            {"user_id": 4242},
        )
        assert (await check_chat_rate_limit(4242, db)).allowed

    async def test_limit_is_per_user(self, db_connection_fixture, monkeypatch):
        monkeypatch.setenv("RAG_CHAT_RATE_LIMIT", "1")
        db = db_connection_fixture

        assert (await check_chat_rate_limit(1111, db)).allowed
        assert (await check_chat_rate_limit(2222, db)).allowed
        assert (await check_chat_rate_limit(1111, db)).allowed is False

    async def test_disabled_limiter_does_not_write(
        self, db_connection_fixture, monkeypatch
    ):
        monkeypatch.setenv("RAG_CHAT_RATE_LIMIT", "0")
        db = db_connection_fixture

        assert (await check_chat_rate_limit(4242, db)).allowed
        row = await db.fetch_one(
            "SELECT count FROM rag_rate_limits WHERE user_id = :user_id",
            {"user_id": 4242},
        )
        assert row is None


@pytest.mark.anyio
class TestChatRateLimitAPI:
    async def test_chat_returns_429_with_retry_after(
        self, client: AsyncClient, db_connection_fixture, monkeypatch
    ):
        monkeypatch.setenv("RAG_CHAT_RATE_LIMIT", "1")
        monkeypatch.setenv("RAG_CHAT_RATE_WINDOW_SECONDS", "60")

        test_user = await return_canned_user(db_connection_fixture)
        await create_canned_user(db_connection_fixture, test_user)
        auth_header = {"Authorization": f"Token {generate_encoded_token(test_user.id)}"}

        async def _fake_chat(*args, **kwargs):
            return RagChatResponseDTO(
                answer="ok",
                degraded=False,
                candidate_count=0,
                session_id="1",
            )

        monkeypatch.setattr(
            rag_resources.RagService, "is_available", staticmethod(lambda: True)
        )
        monkeypatch.setattr(rag_resources.RagService, "chat", _fake_chat)

        url = "/api/v2/rag/sessions/1/chat"
        payload = {"question": "hello", "stream": False}

        first = await client.post(url, json=payload, headers=auth_header)
        assert first.status_code == 200

        second = await client.post(url, json=payload, headers=auth_header)
        assert second.status_code == 429
        assert int(second.headers["Retry-After"]) >= 1
        body = second.json()
        assert body["SubCode"] == "RAGRateLimited"
        assert "Try again" in body["detail"]
