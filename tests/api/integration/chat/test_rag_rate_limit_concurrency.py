"""Concurrency and real-clock tests for the RAG chat rate limiter.

The force-rollback fixtures in `test_rag_rate_limit.py` run every statement
in one transaction: NOW() never advances and parallel work serializes on a
single connection. These tests need committed rows and genuinely parallel
connections, so they use a short-lived pool against the test database.
"""

import asyncio
import json
import os
import subprocess
import sys
from contextlib import asynccontextmanager

import pytest
from databases import Database

from backend.config import test_settings
from chat.rate_limit import check_chat_rate_limit

_db_url = test_settings.SQLALCHEMY_DATABASE_URI.unicode_string()
_pfx, _db_name = _db_url.rsplit("/", 1)
TEST_DB_URL = f"{_pfx}/{_db_name}_test"

_PARALLEL_USER = 91001
_TWO_PROCESS_USER = 91002
_WINDOW_USER = 91003


@asynccontextmanager
async def _pooled_db():
    """Pooled connections (no rollback): commits are visible, NOW() advances."""
    db = Database(TEST_DB_URL, min_size=1, max_size=8)
    await db.connect()
    try:
        yield db
    finally:
        await db.disconnect()


async def _clear_rows(db, user_id: int) -> None:
    await db.execute("DELETE FROM rag_rate_limits WHERE user_id = :u", {"u": user_id})


_MULTI_PROCESS_SCRIPT = (
    "import asyncio, json, sys\n"
    "from databases import Database\n"
    "from chat.rate_limit import check_chat_rate_limit\n"
    "async def main():\n"
    "    db = Database(sys.argv[1], min_size=1, max_size=4)\n"
    "    await db.connect()\n"
    "    try:\n"
    "        allowed = [\n"
    "            (await check_chat_rate_limit(int(sys.argv[2]), db)).allowed\n"
    "            for _ in range(15)\n"
    "        ]\n"
    "        print(json.dumps(allowed))\n"
    "    finally:\n"
    "        await db.disconnect()\n"
    "asyncio.run(main())\n"
)


@pytest.mark.anyio
class TestChatRateLimitConcurrency:
    async def test_parallel_turns_grant_exactly_the_budget(
        self, test_database, monkeypatch
    ):
        monkeypatch.setenv("RAG_CHAT_RATE_LIMIT", "20")
        monkeypatch.setenv("RAG_CHAT_RATE_WINDOW_SECONDS", "60")

        async with _pooled_db() as db:
            await _clear_rows(db, _PARALLEL_USER)
            decisions = await asyncio.gather(
                *[check_chat_rate_limit(_PARALLEL_USER, db) for _ in range(50)]
            )
            assert sum(1 for d in decisions if d.allowed) == 20
            row = await db.fetch_one(
                "SELECT count FROM rag_rate_limits WHERE user_id = :u",
                {"u": _PARALLEL_USER},
            )
            assert row["count"] == 50
            await _clear_rows(db, _PARALLEL_USER)

    async def test_workers_share_one_budget_across_processes(
        self, test_database, monkeypatch
    ):
        monkeypatch.setenv("RAG_CHAT_RATE_LIMIT", "20")
        monkeypatch.setenv("RAG_CHAT_RATE_WINDOW_SECONDS", "60")

        async with _pooled_db() as db:
            await _clear_rows(db, _TWO_PROCESS_USER)

        processes = [
            subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    _MULTI_PROCESS_SCRIPT,
                    TEST_DB_URL,
                    str(_TWO_PROCESS_USER),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=os.environ.copy(),
            )
            for _ in range(2)
        ]
        allowed_total = 0
        for process in processes:
            out, err = process.communicate(timeout=90)
            assert process.returncode == 0, err
            results = json.loads(out.strip().splitlines()[-1])
            allowed_total += sum(1 for allowed in results if allowed)
        assert allowed_total == 20

        async with _pooled_db() as db:
            await _clear_rows(db, _TWO_PROCESS_USER)


@pytest.mark.anyio
class TestChatRateLimitWindow:
    async def test_window_expiry_resets_on_real_clock(self, test_database, monkeypatch):
        monkeypatch.setenv("RAG_CHAT_RATE_LIMIT", "1")
        monkeypatch.setenv("RAG_CHAT_RATE_WINDOW_SECONDS", "3")

        async with _pooled_db() as db:
            await _clear_rows(db, _WINDOW_USER)

            assert (await check_chat_rate_limit(_WINDOW_USER, db)).allowed
            first = await check_chat_rate_limit(_WINDOW_USER, db)
            assert not first.allowed
            assert 1 <= first.retry_after <= 3

            await asyncio.sleep(1.1)
            second = await check_chat_rate_limit(_WINDOW_USER, db)
            assert not second.allowed
            assert 1 <= second.retry_after <= 2

            await asyncio.sleep(2.2)
            assert (await check_chat_rate_limit(_WINDOW_USER, db)).allowed

            await _clear_rows(db, _WINDOW_USER)
