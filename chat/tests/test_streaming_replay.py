"""A retried streaming turn replays the stored answer, not a new generation."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.db import get_db
from backend.models.dtos.user_dto import AuthUserDTO
from backend.services.users.authentication_service import login_required
from chat import api as chat_api


class _Session:
    id = 5
    user_id = 7
    title = "test"
    created_at = None
    updated_at = None
    message_count = 1


STORED = {
    "id": 11,
    "session_id": 5,
    "question": "q",
    "answer": "stored answer",
    "route": "KB",
    "ops": [],
    "project_id": None,
    "reason": "ok",
    "citations": [],
    "model": "fake-model",
    "candidate_count": 1,
}


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(chat_api.router)

    async def fake_user() -> AuthUserDTO:
        return AuthUserDTO(id=7)

    def fake_db():
        return object()

    app.dependency_overrides[login_required] = fake_user
    app.dependency_overrides[get_db] = fake_db
    return app


@pytest.mark.asyncio
async def test_streaming_retry_replays_stored_turn(monkeypatch) -> None:
    async def fake_get_session(*args, **kwargs):
        return dict(STORED)

    async def fake_list_turns(*args, **kwargs):
        return []

    async def fake_get_by_client_id(*args, **kwargs):
        return dict(STORED)

    monkeypatch.setattr(chat_api.sessions, "get_session", fake_get_session)
    monkeypatch.setattr(chat_api.sessions, "list_turns", fake_list_turns)
    monkeypatch.setattr(
        chat_api.sessions, "get_turn_by_client_id", fake_get_by_client_id
    )
    monkeypatch.setattr(chat_api, "_require_chat_config", lambda: None)

    transport = ASGITransport(app=_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/rag/sessions/5/turns",
            json={
                "question": "q",
                "stream": True,
                "client_message_id": "client-1",
            },
        )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    body = response.text
    assert '"delta": "stored answer"' in body
    assert '"turn_id": "11"' in body
    assert "event: meta" in body
    assert "event: done" in body
    assert body.index("data:") < body.index("event: meta") < body.index("event: done")
