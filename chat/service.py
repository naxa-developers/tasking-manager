from __future__ import annotations

import time
from typing import (
    Any,
    AsyncIterator,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
)

from databases import Database
from fastapi import HTTPException
from loguru import logger

from chat.constants import MAX_ROUTING_HISTORY
from chat.dtos import (
    RagChatResponseDTO,
    RagMessageDTO,
    RagSessionDTO,
)
from chat.models import MAX_SESSION_MESSAGES, RagSession
from chat.turn.errors import RagAnswerFailed

try:
    from chat.retrieval.guardrails import classify_query
    from chat.retrieval.llm_answer import LLMService
    from chat.turn.decide import GenerateTurn, decide_early_turn, decide_turn
    from chat.turn.emit import emit_canned_turn, emit_generated_turn
    from chat.turn.persist import persist_user_turn
    from chat.turn.plan import prepare_turn
    from chat.retrieval.domain.dispatch import default_fetchers

    # Import every domain handler up front (building the registry) so a broken
    # handler degrades health instead of failing one op at turn time.
    default_fetchers()

    _RAG_AVAILABLE = True
    _RAG_IMPORT_ERROR: Optional[str] = None
except Exception as e:
    logger.warning(f"RAG unavailable: {e}")
    _RAG_AVAILABLE = False
    _RAG_IMPORT_ERROR = str(e)


def _session_dto(row: Dict[str, Any]) -> RagSessionDTO:
    return RagSessionDTO(
        id=str(row.get("id")),
        title=row.get("title") or "New chat",
        user_id=row.get("user_id"),
        created_at=str(row.get("created_at")) if row.get("created_at") else None,
        updated_at=str(row.get("updated_at")) if row.get("updated_at") else None,
        message_count=int(row.get("message_count") or 0),
    )


async def _get_session(session_id: int, db: Database) -> Any:
    session = await RagSession.get_by_id(session_id, db)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


async def _get_owned_session(session_id: int, user_id: int, db: Database) -> Any:
    """Fetch a session or 404 — including when it belongs to another user."""
    session = await _get_session(session_id, db)
    if session.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


class RagService:
    """Session CRUD + the RAG answer pipeline."""

    @staticmethod
    def is_available() -> bool:
        """True when the chat/retrieval library imported successfully."""
        return _RAG_AVAILABLE

    @staticmethod
    def unavailable_reason() -> Optional[str]:
        """Import error behind an unavailable RAG deployment, if any."""
        return _RAG_IMPORT_ERROR

    @staticmethod
    async def create_session(user_id: int, title: str, db: Database) -> RagSessionDTO:
        """Create a session owned by ``user_id`` and return it."""
        row = await RagSession.create(user_id, title or "New chat", db)
        return _session_dto(row)

    @staticmethod
    async def list_sessions(
        user_id: int, limit: int, offset: int, db: Database
    ) -> List[RagSessionDTO]:
        """List ``user_id``'s sessions, newest first (bounded page size)."""
        limit = max(1, min(int(limit or 20), 100))
        offset = max(0, int(offset or 0))
        rows = await RagSession.list_for(user_id, db, limit=limit, offset=offset)
        return [_session_dto(row) for row in rows]

    @staticmethod
    async def get_session_messages(
        session_id: int, user_id: int, db: Database
    ) -> Tuple[RagSessionDTO, List[RagMessageDTO]]:
        """Return an owned session plus its messages, oldest first."""
        session = await _get_owned_session(session_id, user_id, db)
        messages = await RagSession.get_messages(
            session_id, db, limit=MAX_SESSION_MESSAGES, newest_first=True
        )
        return _session_dto(session), [
            RagMessageDTO(
                role=m["role"],
                content=m["content"],
                model=m.get("model"),
                candidate_count=m.get("candidate_count"),
                created_at=str(m.get("created_at")) if m.get("created_at") else None,
            )
            for m in messages
        ]

    @staticmethod
    async def update_session_title(
        session_id: int, user_id: int, title: Optional[str], db: Database
    ) -> RagSessionDTO:
        """Update an owned session's title (no-op when ``title`` is None)."""
        await _get_owned_session(session_id, user_id, db)
        if title is not None:
            await RagSession.update_title(session_id, title, db)
        return _session_dto(await _get_owned_session(session_id, user_id, db))

    @staticmethod
    async def delete_session(session_id: int, user_id: int, db: Database) -> bool:
        """Delete an owned session; False when the row was already gone."""
        await _get_owned_session(session_id, user_id, db)
        return await RagSession.delete(session_id, db)

    @staticmethod
    async def chat(
        session_id: int,
        user_id: int,
        question: str,
        stream: bool,
        db: Database,
    ) -> Union[RagChatResponseDTO, AsyncIterator[str]]:
        """Run one chat turn: guardrails, routing, retrieval, generation, persist."""
        q = question
        started = time.monotonic()

        def elapsed_ms() -> int:
            return int((time.monotonic() - started) * 1000)

        # Ownership first: unknown or foreign sessions (incl. legacy anonymous) 404.
        session = await _get_owned_session(session_id, user_id, db)

        # Static gate: unsafe refusal or small-talk canned answer, no retrieval.
        guard = classify_query(q)
        early = decide_early_turn(guard, q)
        if early is not None:
            await persist_user_turn(session_id, session, q, db)
            return await emit_canned_turn(
                db=db,
                session_id=session_id,
                user_id=user_id,
                stream=stream,
                decision=early,
                elapsed_ms=elapsed_ms,
            )

        # Prior turns: routing history for follow-up and project-id inheritance.
        prior = await RagSession.get_messages(
            session_id, db, limit=MAX_ROUTING_HISTORY, newest_first=True
        )

        prepared = await prepare_turn(q, session, db, guard, user_id, prior=prior)
        decision = decide_turn(prepared)

        if isinstance(decision, GenerateTurn):
            return await emit_generated_turn(
                db=db,
                session_id=session_id,
                user_id=user_id,
                stream=stream,
                question=q,
                prepared=prepared,
                decision=decision,
                llm=LLMService(),
                elapsed_ms=elapsed_ms,
            )
        return await emit_canned_turn(
            db=db,
            session_id=session_id,
            user_id=user_id,
            stream=stream,
            decision=decision,
            elapsed_ms=elapsed_ms,
        )
