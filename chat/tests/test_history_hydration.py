"""Conversation history must never be silently trimmed.

Routing/inheritance hydration fetches the entire session by default; the LLM
history block renders every prior turn. These tests pin that contract.
"""

import asyncio
from typing import Any, Dict, List, Optional

from chat.models import RagSession


class _FakeDB:
    def __init__(self):
        self.queries: List[str] = []
        self.values: List[Dict[str, Any]] = []

    async def fetch_all(self, query: str, values: Optional[Dict] = None):
        self.queries.append(query)
        self.values.append(values or {})
        return []


def test_get_messages_without_limit_omits_limit_clause():
    db = _FakeDB()
    asyncio.run(RagSession.get_messages(1, db))

    assert "LIMIT" not in db.queries[0]
    assert "limit" not in db.values[0]


def test_get_messages_with_limit_keeps_the_clause():
    db = _FakeDB()
    asyncio.run(RagSession.get_messages(1, db, limit=20))

    assert "LIMIT" in db.queries[0]
    assert db.values[0]["limit"] == 20
    assert db.values[0]["offset"] == 0
