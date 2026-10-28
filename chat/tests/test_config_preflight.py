"""Missing model configuration is a deployment error, not a canned answer."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.db import get_db
from backend.models.dtos.user_dto import AuthUserDTO
from backend.services.users.authentication_service import login_required
from chat import api as chat_api
from chat.config import validate_chat_config


def _set_generation_only(monkeypatch) -> None:
    monkeypatch.setenv("LITELLM_MODEL", "fake/generation")
    monkeypatch.delenv("GENERATION_MODEL", raising=False)
    monkeypatch.delenv("RAG_ROUTER_MODEL", raising=False)


def test_missing_generation_model_raises(monkeypatch) -> None:
    monkeypatch.delenv("LITELLM_MODEL", raising=False)
    monkeypatch.delenv("GENERATION_MODEL", raising=False)
    monkeypatch.delenv("RAG_ROUTER_MODEL", raising=False)
    with pytest.raises(RuntimeError):
        validate_chat_config()


def test_missing_embedding_model_raises(monkeypatch) -> None:
    _set_generation_only(monkeypatch)
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    with pytest.raises(RuntimeError):
        validate_chat_config()


def test_complete_config_passes(monkeypatch) -> None:
    _set_generation_only(monkeypatch)
    monkeypatch.setenv("EMBEDDING_MODEL", "fake/embedding")
    monkeypatch.setenv("EMBEDDING_DIMENSION", "8")
    validate_chat_config()


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(chat_api.router)

    async def fake_user() -> AuthUserDTO:
        return AuthUserDTO(id=1)

    def fake_db():
        return object()

    app.dependency_overrides[login_required] = fake_user
    app.dependency_overrides[get_db] = fake_db
    return app


@pytest.mark.asyncio
async def test_ask_returns_500_when_config_is_missing(monkeypatch) -> None:
    monkeypatch.delenv("LITELLM_MODEL", raising=False)
    monkeypatch.delenv("GENERATION_MODEL", raising=False)
    monkeypatch.delenv("RAG_ROUTER_MODEL", raising=False)
    transport = ASGITransport(app=_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/rag/ask", json={"question": "hello"})
    assert response.status_code == 500
    assert "configuration" in response.text.lower()


@pytest.mark.asyncio
async def test_streaming_ask_returns_500_before_sse(monkeypatch) -> None:
    monkeypatch.delenv("LITELLM_MODEL", raising=False)
    monkeypatch.delenv("GENERATION_MODEL", raising=False)
    monkeypatch.delenv("RAG_ROUTER_MODEL", raising=False)
    transport = ASGITransport(app=_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/rag/ask", json={"question": "hello", "stream": True}
        )
    assert response.status_code == 500
    assert "text/event-stream" not in response.headers.get("content-type", "")
