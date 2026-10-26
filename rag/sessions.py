"""Sessions and turns, with ownership enforced at the store.

A **turn** is one question and its answer, stored as a single row. That is the
unit the API accepts and returns, so a conversation is a list of turns rather
than a stream of role-tagged messages.

Every public function takes the caller's ``user_id`` and resolves the session
through :func:`_owned`, so a foreign or unknown id raises :class:`SessionNotFound`
before any read or write happens. The store cannot be reached unscoped — a new
endpoint gets the 404 rule by construction rather than by remembering to check.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from databases import Database
from loguru import logger

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
MAX_TITLE_CHARS = 200
# Turns hydrated as conversation context for routing and generation.
MAX_CONTEXT_TURNS = 8


class SessionNotFound(Exception):
    """Unknown session id, or one owned by another user."""


def timestamp() -> datetime:
    """Naive UTC timestamp, matching the existing ``rag_*`` column types."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _page(limit: Optional[int], offset: Optional[int]) -> tuple:
    size = DEFAULT_PAGE_SIZE if limit is None else int(limit)
    return max(1, min(size, MAX_PAGE_SIZE)), max(0, int(offset or 0))


def _session_id(value: Any) -> int:
    """Coerce a path/JSON session id to the integer the column expects."""
    try:
        return int(value)
    except (TypeError, ValueError):
        # An unparseable id cannot match a row, so treat it as not found.
        raise SessionNotFound() from None


async def _owned(
    session_id: int, user_id: Optional[int], db: Database
) -> Dict[str, Any]:
    """The session row when ``user_id`` owns it; otherwise :class:`SessionNotFound`.

    A missing session and someone else's session are deliberately the same
    failure — the caller cannot tell them apart.
    """
    if user_id is None:
        raise SessionNotFound()
    row = await db.fetch_one(
        query="""
            SELECT id, user_id, title, created_at, updated_at, message_count
            FROM rag_sessions
            WHERE id = :id AND user_id = :user_id
        """,
        values={"id": _session_id(session_id), "user_id": user_id},
    )
    if row is None:
        raise SessionNotFound()
    return dict(row)


async def create_session(user_id: int, title: str, db: Database) -> Dict[str, Any]:
    """Create a session owned by ``user_id``."""
    if user_id is None:
        raise ValueError("user_id is required: sessions are owner-scoped")
    now = timestamp()
    row = await db.fetch_one(
        query="""
            INSERT INTO rag_sessions (user_id, title, created_at, updated_at, message_count)
            VALUES (:user_id, :title, :created_at, :updated_at, 0)
            RETURNING id, user_id, title, created_at, updated_at, message_count
        """,
        values={
            "user_id": user_id,
            "title": (title or "New chat")[:MAX_TITLE_CHARS],
            "created_at": now,
            "updated_at": now,
        },
    )
    return dict(row) if row else {}


async def list_sessions(
    user_id: int, limit: Optional[int], offset: Optional[int], db: Database
) -> List[Dict[str, Any]]:
    """The caller's sessions, most recently active first."""
    size, start = _page(limit, offset)
    rows = await db.fetch_all(
        query="""
            SELECT id, user_id, title, created_at, updated_at, message_count
            FROM rag_sessions
            WHERE user_id = :user_id
            ORDER BY updated_at DESC
            LIMIT :limit OFFSET :offset
        """,
        values={"user_id": user_id, "limit": size, "offset": start},
    )
    return [dict(row) for row in rows]


async def get_session(session_id: int, user_id: int, db: Database) -> Dict[str, Any]:
    """One owned session."""
    return await _owned(session_id, user_id, db)


async def rename_session(
    session_id: int, user_id: int, title: str, db: Database
) -> Dict[str, Any]:
    """Rename an owned session and bump its activity time."""
    session_id = _session_id(session_id)
    await _owned(session_id, user_id, db)
    await db.execute(
        query="""
            UPDATE rag_sessions
            SET title = :title, updated_at = :updated_at
            WHERE id = :id
        """,
        values={
            "id": session_id,
            "title": (title or "")[:MAX_TITLE_CHARS],
            "updated_at": timestamp(),
        },
    )
    return await _owned(session_id, user_id, db)


async def delete_session(session_id: int, user_id: int, db: Database) -> bool:
    """Delete an owned session; False when it had already gone (cascade removes turns)."""
    session_id = _session_id(session_id)
    await _owned(session_id, user_id, db)
    row = await db.fetch_one(
        query="DELETE FROM rag_sessions WHERE id = :id RETURNING id",
        values={"id": session_id},
    )
    return row is not None


def _turn_from_row(row: Any) -> Dict[str, Any]:
    data = dict(row)
    for key in ("ops", "citations"):
        if isinstance(data.get(key), str):
            try:
                data[key] = json.loads(data[key])
            except ValueError:
                data[key] = []
    return data


async def list_turns(
    session_id: int,
    user_id: int,
    db: Database,
    limit: int = MAX_PAGE_SIZE,
    newest_first: bool = False,
) -> List[Dict[str, Any]]:
    """Turns in an owned session, oldest first by default."""
    session_id = _session_id(session_id)
    await _owned(session_id, user_id, db)
    order = "DESC" if newest_first else "ASC"
    rows = await db.fetch_all(
        query=f"""
            SELECT id, session_id, question, answer, route, ops, project_id,
                   reason, citations, model, candidate_count, created_at
            FROM rag_turns
            WHERE session_id = :session_id
            ORDER BY created_at {order}, id {order}
            LIMIT :limit
        """,
        values={"session_id": session_id, "limit": max(1, int(limit))},
    )
    return [_turn_from_row(row) for row in rows]


async def append_turn(
    session_id: int,
    user_id: int,
    question: str,
    answer: str,
    db: Database,
    *,
    route: Optional[str] = None,
    ops: Optional[Sequence[str]] = None,
    project_id: Optional[int] = None,
    reason: Optional[str] = None,
    citations: Optional[List[Dict[str, Any]]] = None,
    model: Optional[str] = None,
    candidate_count: Optional[int] = None,
) -> Dict[str, Any]:
    """Persist one completed turn and mark the session active."""
    session_id = _session_id(session_id)
    await _owned(session_id, user_id, db)
    now = timestamp()
    async with db.transaction():
        row = await db.fetch_one(
            query="""
                INSERT INTO rag_turns
                    (session_id, question, answer, route, ops, project_id, reason,
                     citations, model, candidate_count, created_at)
                VALUES
                    (:session_id, :question, :answer, :route, :ops, :project_id,
                     :reason, :citations, :model, :candidate_count, :created_at)
                RETURNING id, session_id, question, answer, route, ops, project_id,
                          reason, citations, model, candidate_count, created_at
            """,
            values={
                "session_id": _session_id(session_id),
                "question": question,
                "answer": answer,
                "route": (route or "")[:16] or None,
                "ops": json.dumps(list(ops or [])),
                "project_id": project_id,
                "reason": (reason or "")[:32] or None,
                "citations": json.dumps(citations or []),
                "model": (model or None) and str(model)[:64],
                "candidate_count": candidate_count,
                "created_at": now,
            },
        )
        await db.execute(
            query="""
                UPDATE rag_sessions
                SET updated_at = :updated_at, message_count = message_count + 1
                WHERE id = :id
            """,
            values={"id": session_id, "updated_at": now},
        )
    logger.debug(f"rag turn appended to session {session_id}")
    return _turn_from_row(row) if row else {}


def history_from_turns(turns: Sequence[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Flatten stored turns into the message list routing and generation expect."""
    history: List[Dict[str, str]] = []
    for turn in list(turns)[-MAX_CONTEXT_TURNS:]:
        question = str(turn.get("question") or "").strip()
        answer = str(turn.get("answer") or "").strip()
        if question:
            history.append({"role": "user", "content": question})
        if answer:
            history.append({"role": "assistant", "content": answer})
    return history
