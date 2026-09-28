"""Unit tests for the RAG chat rate limiter (no database)."""

import pytest

from chat.rate_limit import (
    check_chat_rate_limit,
    get_rate_limit_config,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("RAG_CHAT_RATE_LIMIT", raising=False)
    monkeypatch.delenv("RAG_CHAT_RATE_WINDOW_SECONDS", raising=False)


class _FakeDB:
    """Returns queued rows and records the values each query received."""

    def __init__(self, rows=None):
        self._rows = list(rows or [])
        self.calls = []

    async def fetch_one(self, query, values):
        self.calls.append(values)
        return self._rows.pop(0) if self._rows else None


class _BrokenDB:
    async def fetch_one(self, query, values):
        raise RuntimeError("db down")


def test_config_defaults():
    cfg = get_rate_limit_config()
    assert cfg.limit == 20
    assert cfg.window_seconds == 60


def test_config_reads_env(monkeypatch):
    monkeypatch.setenv("RAG_CHAT_RATE_LIMIT", "5")
    monkeypatch.setenv("RAG_CHAT_RATE_WINDOW_SECONDS", "30")
    cfg = get_rate_limit_config()
    assert (cfg.limit, cfg.window_seconds) == (5, 30)


def test_config_window_is_at_least_one_second(monkeypatch):
    monkeypatch.setenv("RAG_CHAT_RATE_WINDOW_SECONDS", "0")
    assert get_rate_limit_config().window_seconds == 1


@pytest.mark.anyio
async def test_allows_and_reports_remaining():
    db = _FakeDB([{"count": 1, "retry_after": 0}])
    decision = await check_chat_rate_limit(7, db)
    assert decision.allowed
    assert decision.retry_after == 0
    assert decision.remaining == 19
    assert db.calls == [{"user_id": 7, "window_seconds": 60}]


@pytest.mark.anyio
async def test_blocks_over_limit_with_retry_after():
    db = _FakeDB([{"count": 21, "retry_after": 12}])
    decision = await check_chat_rate_limit(7, db)
    assert not decision.allowed
    assert decision.retry_after == 12
    assert decision.remaining == 0


@pytest.mark.anyio
async def test_retry_after_is_never_zero_when_blocked():
    db = _FakeDB([{"count": 21, "retry_after": 0}])
    decision = await check_chat_rate_limit(7, db)
    assert not decision.allowed
    assert decision.retry_after == 1


@pytest.mark.anyio
async def test_disabled_limiter_skips_database(monkeypatch):
    monkeypatch.setenv("RAG_CHAT_RATE_LIMIT", "0")
    db = _FakeDB()
    decision = await check_chat_rate_limit(7, db)
    assert decision.allowed
    assert db.calls == []


@pytest.mark.anyio
async def test_fails_open_on_counter_store_error():
    decision = await check_chat_rate_limit(7, _BrokenDB())
    assert decision.allowed
    assert decision.retry_after == 0
