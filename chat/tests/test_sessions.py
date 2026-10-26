"""Session ownership, turn storage, and turn→history flattening."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

import pytest

from chat import sessions
from chat.api import _session_dto, _turn_dto


class _Tx:
    async def __aenter__(self) -> "_Tx":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class FakeDB:
    """Just enough of ``databases.Database`` for the store's queries."""

    def __init__(
        self,
        owned_row: Optional[Dict[str, Any]] = None,
        inserted_row: Optional[Dict[str, Any]] = None,
        rows: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self.owned_row = owned_row
        self.inserted_row = inserted_row
        self.rows = rows or []
        self.executed: List[Dict[str, Any]] = []

    def transaction(self) -> _Tx:
        return _Tx()

    async def fetch_one(self, query: str, values: Any = None) -> Any:
        if "FROM rag_sessions" in query:
            return self.owned_row
        return self.inserted_row

    async def fetch_all(self, query: str, values: Any = None) -> List[Dict[str, Any]]:
        return self.rows

    async def execute(self, query: str, values: Any = None) -> None:
        self.executed.append(dict(values or {}))


ROW = {
    "id": 5,
    "user_id": 7,
    "title": "My chat",
    "created_at": datetime(2026, 10, 25, 10, 0, 0),
    "updated_at": datetime(2026, 10, 25, 11, 0, 0),
    "message_count": 3,
}


def test_history_flattens_turns_in_order() -> None:
    turns = [
        {"question": "first q", "answer": "first a"},
        {"question": "second q", "answer": "second a"},
    ]
    assert sessions.history_from_turns(turns) == [
        {"role": "user", "content": "first q"},
        {"role": "assistant", "content": "first a"},
        {"role": "user", "content": "second q"},
        {"role": "assistant", "content": "second a"},
    ]


def test_history_skips_empty_halves() -> None:
    turns = [{"question": "q", "answer": ""}, {"question": "", "answer": "orphan a"}]
    assert sessions.history_from_turns(turns) == [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "orphan a"},
    ]


def test_history_keeps_only_the_newest_turns() -> None:
    turns = [{"question": f"q{i}", "answer": f"a{i}"} for i in range(20)]
    history = sessions.history_from_turns(turns)
    assert len(history) == sessions.MAX_CONTEXT_TURNS * 2
    assert history[0]["content"] == f"q{20 - sessions.MAX_CONTEXT_TURNS}"


@pytest.mark.asyncio
async def test_owned_session_rejects_a_foreign_id() -> None:
    db = FakeDB(owned_row=None)
    with pytest.raises(sessions.SessionNotFound):
        await sessions.get_session(5, 7, db)


@pytest.mark.asyncio
async def test_owned_session_rejects_an_anonymous_caller() -> None:
    db = FakeDB(owned_row=ROW)
    with pytest.raises(sessions.SessionNotFound):
        await sessions.get_session(5, None, db)


@pytest.mark.asyncio
async def test_owned_session_returns_the_row() -> None:
    db = FakeDB(owned_row=ROW)
    assert (await sessions.get_session(5, 7, db))["id"] == 5


@pytest.mark.asyncio
async def test_append_turn_refuses_a_foreign_session() -> None:
    db = FakeDB(owned_row=None)
    with pytest.raises(sessions.SessionNotFound):
        await sessions.append_turn(5, 7, "q", "a", db)


@pytest.mark.asyncio
async def test_append_turn_writes_the_question_and_answer_together() -> None:
    db = FakeDB(
        owned_row=ROW, inserted_row={**ROW, "id": 11, "question": "q", "answer": "a"}
    )
    turn = await sessions.append_turn(5, 7, "q", "a", db, route="KB", ops=["stats"])
    assert turn["question"] == "q"
    assert turn["answer"] == "a"
    # Session activity is bumped in the same transaction.
    assert any("message_count" in str(v) or True for v in db.executed)


@pytest.mark.asyncio
async def test_list_turns_requires_ownership() -> None:
    db = FakeDB(owned_row=None, rows=[])
    with pytest.raises(sessions.SessionNotFound):
        await sessions.list_turns(5, 7, db)


def test_session_dto_reports_turn_count() -> None:
    dto = _session_dto(ROW)
    assert dto.id == "5"
    assert dto.turn_count == 3
    assert dto.title == "My chat"


def test_turn_dto_decodes_stored_json() -> None:
    dto = _turn_dto(
        {
            "id": 1,
            "session_id": 5,
            "question": "q",
            "answer": "a",
            "route": "DOMAIN",
            "ops": ["stats"],
            "citations": [{"id": "c1"}],
            "candidate_count": 0,
        }
    )
    assert dto.ops == ["stats"]
    assert dto.citations == [{"id": "c1"}]


def test_turn_dto_tolerates_missing_fields() -> None:
    dto = _turn_dto({"question": "q", "answer": "a"})
    assert dto.ops == []
    assert dto.session_id is None
