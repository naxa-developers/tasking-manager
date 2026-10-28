"""HTTP surface: sessions, turns, and a stateless one-shot.

A turn is the unit here — you post a question, you get back that turn (question
and answer together). History for routing and generation is read from the
session's stored turns, not sent by the client.

Both the store and these routes take the authenticated user's id, and the store
raises ``SessionNotFound`` for a foreign id, so ownership is enforced in one
place rather than at each handler.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from databases import Database
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field

from backend.db import db_connection, get_db
from backend.models.dtos.user_dto import AuthUserDTO
from backend.services.users.authentication_service import login_required
from chat import sessions
from chat.config import validate_chat_config
from chat.health import rag_health, rag_readiness
from chat.pipeline import Delta, Finished, Turn as TurnResult
from chat.pipeline import run_turn, stream_turn
from chat.rate_limit import check_rate_limit

router = APIRouter(prefix="/rag", tags=["rag"])

MAX_QUESTION_CHARS = 4000

_STREAM_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


# --- request / response shapes ------------------------------------------------


class CreateSessionDTO(BaseModel):
    title: str = Field(default="New chat", max_length=200)


class RenameSessionDTO(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class SessionDTO(BaseModel):
    id: str
    title: str
    user_id: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    turn_count: int = 0


class TurnDTO(BaseModel):
    id: Optional[str] = None
    session_id: Optional[str] = None
    question: str
    answer: str
    route: Optional[str] = None
    ops: List[str] = Field(default_factory=list)
    project_id: Optional[int] = None
    reason: Optional[str] = None
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    model: Optional[str] = None
    candidate_count: int = 0
    created_at: Optional[str] = None


class SessionTurnsDTO(BaseModel):
    session: SessionDTO
    turns: List[TurnDTO]


class AskTurnDTO(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    stream: bool = False
    client_message_id: Optional[str] = Field(default=None, max_length=64)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    history: List[Dict[str, str]] = Field(default_factory=list)
    stream: bool = False


# --- mapping ------------------------------------------------------------------


def _session_dto(row: Dict[str, Any]) -> SessionDTO:
    return SessionDTO(
        id=str(row.get("id")),
        title=row.get("title") or "New chat",
        user_id=row.get("user_id"),
        created_at=str(row["created_at"]) if row.get("created_at") else None,
        updated_at=str(row["updated_at"]) if row.get("updated_at") else None,
        # The column predates turns; it now counts turns per session.
        turn_count=int(row.get("message_count") or 0),
    )


def _turn_dto(row: Dict[str, Any]) -> TurnDTO:
    return TurnDTO(
        id=str(row["id"]) if row.get("id") is not None else None,
        session_id=(
            str(row["session_id"]) if row.get("session_id") is not None else None
        ),
        question=row.get("question") or "",
        answer=row.get("answer") or "",
        route=row.get("route"),
        ops=list(row.get("ops") or []),
        project_id=row.get("project_id"),
        reason=row.get("reason"),
        citations=list(row.get("citations") or []),
        model=row.get("model"),
        candidate_count=int(row.get("candidate_count") or 0),
        created_at=str(row["created_at"]) if row.get("created_at") else None,
    )


def _from_result(
    result: TurnResult, question: str, session_id: Optional[int] = None
) -> TurnDTO:
    return TurnDTO(
        session_id=str(session_id) if session_id is not None else None,
        question=question,
        answer=result.answer,
        route=result.route,
        ops=list(result.ops),
        project_id=result.project_id,
        reason=result.reason,
        citations=result.citations,
        model=result.model,
        candidate_count=result.candidate_count,
    )


def _rate_limited(retry_after: int) -> JSONResponse:
    return JSONResponse(
        content={
            "Error": "Rate limit exceeded",
            "detail": f"Too many chat turns. Try again in {retry_after} seconds.",
            "SubCode": "RAGRateLimited",
        },
        status_code=429,
        headers={"Retry-After": str(retry_after)},
    )


def _require_chat_config() -> None:
    """Return HTTP 500 when the deployment's chat model config is incomplete."""
    try:
        validate_chat_config()
    except Exception as exc:
        # Do not leak configuration values or provider details.
        logger.error("chat configuration invalid: {}", type(exc).__name__)
        raise HTTPException(
            status_code=500,
            detail="Chat model configuration is incomplete",
        ) from exc


def _chat_enabled() -> bool:
    """Feature flag; defaults to enabled for the existing deployment."""
    raw = (os.getenv("CHAT_ENABLED") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _require_chat_enabled() -> None:
    if not _chat_enabled():
        raise HTTPException(status_code=404, detail="Chat is disabled")


# --- health -------------------------------------------------------------------


@router.get("/health")
async def health(db: Database = Depends(get_db)):
    """Deployment diagnostics. 503 when the KB index itself is unavailable."""
    payload = await rag_health(db)
    status_code = 200 if payload.get("status") in ("ok", "degraded") else 503
    return JSONResponse(content=payload, status_code=status_code)


@router.get("/ready")
async def ready(db: Database = Depends(get_db)):
    """Strict probe: everything in /health plus reachable model providers."""
    payload = await rag_readiness(db)
    status_code = 200 if payload.get("status") == "ready" else 503
    return JSONResponse(content=payload, status_code=status_code)


# --- sessions -----------------------------------------------------------------


@router.post("/sessions", response_model=SessionDTO)
async def create_session(
    body: CreateSessionDTO,
    user: AuthUserDTO = Depends(login_required),
    db: Database = Depends(get_db),
):
    """Start a conversation."""
    _require_chat_enabled()
    row = await sessions.create_session(user.id, body.title, db)
    return _session_dto(row)


@router.get("/sessions")
async def list_sessions(
    user: AuthUserDTO = Depends(login_required),
    db: Database = Depends(get_db),
    limit: int = sessions.DEFAULT_PAGE_SIZE,
    offset: int = 0,
):
    """The caller's conversations, most recently active first."""
    _require_chat_enabled()
    rows = await sessions.list_sessions(user.id, limit, offset, db)
    return {"sessions": [_session_dto(row) for row in rows]}


@router.get("/sessions/{session_id}", response_model=SessionTurnsDTO)
async def get_session(
    session_id: int,
    user: AuthUserDTO = Depends(login_required),
    db: Database = Depends(get_db),
    limit: int = sessions.MAX_PAGE_SIZE,
):
    """One conversation with its turns; 404 when it is unknown or not yours.

    The turns travel with the session so a client can open a conversation in
    one request — the same reason a chat UI wants history and title together.
    """
    _require_chat_enabled()
    try:
        row = await sessions.get_session(session_id, user.id, db)
        turns = await sessions.list_turns(session_id, user.id, db, limit=limit)
    except sessions.SessionNotFound:
        raise HTTPException(status_code=404, detail="Session not found") from None
    return SessionTurnsDTO(
        session=_session_dto(row), turns=[_turn_dto(turn) for turn in turns]
    )


@router.patch("/sessions/{session_id}", response_model=SessionDTO)
async def rename_session(
    session_id: int,
    body: RenameSessionDTO,
    user: AuthUserDTO = Depends(login_required),
    db: Database = Depends(get_db),
):
    """Rename a conversation."""
    _require_chat_enabled()
    try:
        row = await sessions.rename_session(session_id, user.id, body.title, db)
    except sessions.SessionNotFound:
        raise HTTPException(status_code=404, detail="Session not found") from None
    return _session_dto(row)


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: int,
    user: AuthUserDTO = Depends(login_required),
    db: Database = Depends(get_db),
):
    """Delete a conversation and its turns (cascade)."""
    _require_chat_enabled()
    try:
        deleted = await sessions.delete_session(session_id, user.id, db)
    except sessions.SessionNotFound:
        raise HTTPException(status_code=404, detail="Session not found") from None
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"deleted": True}


# --- turns --------------------------------------------------------------------


@router.get("/sessions/{session_id}/turns", response_model=SessionTurnsDTO)
async def list_turns(
    session_id: int,
    user: AuthUserDTO = Depends(login_required),
    db: Database = Depends(get_db),
    limit: int = sessions.MAX_PAGE_SIZE,
):
    """The conversation as turns, oldest first."""
    _require_chat_enabled()
    try:
        session = await sessions.get_session(session_id, user.id, db)
        turns = await sessions.list_turns(session_id, user.id, db, limit=limit)
    except sessions.SessionNotFound:
        raise HTTPException(status_code=404, detail="Session not found") from None
    return SessionTurnsDTO(
        session=_session_dto(session), turns=[_turn_dto(turn) for turn in turns]
    )


async def _append(
    conn: Any,
    session_id: int,
    user_id: int,
    question: str,
    turn: TurnResult,
    client_message_id: Optional[str] = None,
) -> Dict[str, Any]:
    return await sessions.append_turn(
        session_id,
        user_id,
        question,
        turn.answer,
        conn,
        route=turn.route,
        ops=turn.ops,
        project_id=turn.project_id,
        reason=turn.reason,
        citations=turn.citations,
        model=turn.model,
        candidate_count=turn.candidate_count,
        client_message_id=client_message_id,
    )


async def _persist_turn(
    session_id: int,
    user_id: int,
    question: str,
    turn: TurnResult,
    db: Any = None,
    client_message_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Write the turn; mid-stream callers use a fresh pooled connection.

    Losing the audit row must never lose an answer the user already received,
    so a persistence failure is logged and swallowed.
    """
    try:
        if db is None:
            async with db_connection.database.connection() as fresh:
                return await _append(
                    fresh,
                    session_id,
                    user_id,
                    question,
                    turn,
                    client_message_id=client_message_id,
                )
        return await _append(
            db,
            session_id,
            user_id,
            question,
            turn,
            client_message_id=client_message_id,
        )
    except Exception:
        logger.exception(f"failed to persist turn for session {session_id}")
        return None


def _frame(event: str, payload: Dict[str, Any]) -> str:
    """One SSE frame; ``message`` is the default event, so it carries no name."""
    if event == "message":
        return f"data: {json.dumps(payload)}\n\n"
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


def _meta_payload(
    turn: TurnResult, session_id: Optional[int], saved: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    return {
        "session_id": str(session_id) if session_id is not None else None,
        "turn_id": (
            str(saved["id"]) if saved and saved.get("id") is not None else None
        ),
        "route": turn.route,
        "ops": list(turn.ops),
        "project_id": turn.project_id,
        "reason": turn.reason,
        "candidate_count": turn.candidate_count,
        "model": turn.model,
        "degraded": turn.degraded,
    }


def _stream_response(
    session_id: Optional[int],
    question: str,
    user_id: int,
    db: Any,
    history: List[Dict[str, str]],
    client_message_id: Optional[str] = None,
) -> StreamingResponse:
    """SSE: ``data`` deltas, then ``meta``, then ``done`` (``error`` on failure)."""

    async def events():
        final: Optional[TurnResult] = None
        saved: Optional[Dict[str, Any]] = None
        try:
            # A streaming response outlives the request handler, so the
            # request-scoped connection (``db``) is already released by the
            # time this generator runs. Hold a fresh pooled connection for the
            # stream's lifetime: domain ops need it, and so does persistence.
            async with db_connection.database.connection() as conn:
                async for event in stream_turn(
                    question, user_id=user_id, db=conn, history=history
                ):
                    if isinstance(event, Delta):
                        yield _frame("message", {"delta": event.text})
                    elif isinstance(event, Finished):
                        final = event.turn
                if (
                    session_id is not None
                    and final is not None
                    and final.reason != "error"
                ):
                    try:
                        saved = await _append(
                            conn,
                            session_id,
                            user_id,
                            question,
                            final,
                            client_message_id=client_message_id,
                        )
                    except Exception:
                        # Losing the audit row must not lose the answer.
                        logger.exception(
                            f"failed to persist turn for session {session_id}"
                        )
        except Exception:
            logger.exception("turn stream failed")
            yield _frame("error", {"error": "Answer generation failed"})
            yield _frame("done", {})
            return

        if final is None:
            yield _frame("error", {"error": "Answer generation failed"})
            yield _frame("done", {})
            return

        yield _frame("meta", _meta_payload(final, session_id, saved))
        if final.reason == "error":
            yield _frame("error", {"error": "Answer incomplete"})
        yield _frame("done", {})

    return StreamingResponse(
        events(), media_type="text/event-stream", headers=_STREAM_HEADERS
    )


@router.post("/sessions/{session_id}/turns", response_model=None)
async def send_turn(
    session_id: int,
    body: AskTurnDTO,
    user: AuthUserDTO = Depends(login_required),
    db: Database = Depends(get_db),
):
    """Send one turn: answer the question in the context of this session.

    ``stream: true`` returns SSE instead of JSON — the same endpoint, same
    persistence, one protocol for canned and generated answers alike.
    """
    _require_chat_enabled()
    _require_chat_config()
    try:
        await sessions.get_session(session_id, user.id, db)
        prior = await sessions.list_turns(
            session_id,
            user.id,
            db,
            limit=sessions.MAX_CONTEXT_TURNS,
            newest_first=True,
        )
    except sessions.SessionNotFound:
        raise HTTPException(status_code=404, detail="Session not found") from None

    if body.client_message_id and not body.stream:
        existing = await sessions.get_turn_by_client_id(
            session_id, user.id, body.client_message_id, db
        )
        if existing is not None:
            return _turn_dto(existing)

    decision = await check_rate_limit(user.id, db)
    if not decision.allowed:
        return _rate_limited(decision.retry_after)

    question = body.question.strip()
    history = sessions.history_from_turns(list(reversed(prior)))

    if body.stream:
        return _stream_response(
            session_id,
            question,
            user.id,
            db,
            history,
            client_message_id=body.client_message_id,
        )

    result = await run_turn(question, user_id=user.id, db=db, history=history)

    saved: Optional[Dict[str, Any]] = None
    if result.reason != "error":
        saved = await _persist_turn(
            session_id,
            user.id,
            question,
            result,
            db,
            client_message_id=body.client_message_id,
        )

    return _turn_dto(saved) if saved else _from_result(result, question, session_id)


# --- stateless one-shot -------------------------------------------------------


@router.post("/ask", response_model=None)
async def ask(
    body: AskRequest,
    user: AuthUserDTO = Depends(login_required),
    db: Database = Depends(get_db),
):
    """Answer one question with no session and no persistence."""
    _require_chat_enabled()
    _require_chat_config()
    decision = await check_rate_limit(user.id, db)
    if not decision.allowed:
        return _rate_limited(decision.retry_after)

    question = body.question.strip()
    if body.stream:
        return _stream_response(None, question, user.id, db, body.history)

    result = await run_turn(question, user_id=user.id, db=db, history=body.history)
    return _from_result(result, question)
