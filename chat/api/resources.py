from __future__ import annotations

from typing import Any, Dict, Optional

from databases import Database
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from loguru import logger

from backend.db import get_db
from backend.models.dtos.user_dto import AuthUserDTO
from backend.services.users.authentication_service import login_required
from chat.dtos import (
    RagChatRequestDTO,
    RagChatResponseDTO,
    RagSessionCreateDTO,
    RagSessionDTO,
    RagSessionUpdateDTO,
)
from chat.health import rag_health as build_health, rag_readiness as build_readiness
from chat.retrieval.query_kb import RetrievalUnavailable
from chat.rate_limit import check_chat_rate_limit
from chat.service import RagAnswerFailed, RagService

router = APIRouter(
    prefix="/rag",
    tags=["rag"],
    responses={404: {"description": "Not found"}},
)

_STREAM_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _error_response(
    error: str,
    sub_code: str,
    status_code: int,
    detail: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> JSONResponse:
    """Canonical error body: Error, optional detail, SubCode (key order kept)."""
    content: Dict[str, Any] = {"Error": error}
    if detail is not None:
        content["detail"] = detail
    content["SubCode"] = sub_code
    return JSONResponse(content=content, status_code=status_code, headers=headers)


def _rag_unavailable() -> JSONResponse:
    logger.warning(f"RAG unavailable: {RagService.unavailable_reason()}")
    return _error_response(
        "RAG not configured",
        "RAGUnavailable",
        503,
        detail="RAG is not available on this deployment.",
    )


def _rag_rate_limited(retry_after: int) -> JSONResponse:
    return _error_response(
        "Rate limit exceeded",
        "RAGRateLimited",
        429,
        detail=f"Too many chat messages. Try again in {retry_after} seconds.",
        headers={"Retry-After": str(retry_after)},
    )


@router.get("/health")
async def rag_health(db: Database = Depends(get_db)) -> Any:
    payload = await build_health(db)
    status_code = 200 if payload.get("status") in ("ok", "degraded") else 503
    return JSONResponse(content=payload, status_code=status_code)


@router.get("/ready")
async def rag_ready(db: Database = Depends(get_db)) -> Any:
    payload = await build_readiness(db)
    status_code = 200 if payload.get("status") == "ready" else 503
    return JSONResponse(content=payload, status_code=status_code)


@router.post("/sessions", response_model=RagSessionDTO)
async def create_session(
    body: RagSessionCreateDTO,
    user: AuthUserDTO = Depends(login_required),
    db: Database = Depends(get_db),
):
    return await RagService.create_session(user.id, body.title or "New chat", db)


@router.get("/sessions")
async def list_sessions(
    user: AuthUserDTO = Depends(login_required),
    db: Database = Depends(get_db),
    limit: int = 20,
    offset: int = 0,
):
    sessions = await RagService.list_sessions(user.id, limit, offset, db)
    return {"sessions": sessions}


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: int,
    user: AuthUserDTO = Depends(login_required),
    db: Database = Depends(get_db),
):
    session, messages = await RagService.get_session_messages(session_id, user.id, db)
    return {"session": session, "messages": messages}


@router.patch("/sessions/{session_id}", response_model=RagSessionDTO)
async def update_session(
    session_id: int,
    body: RagSessionUpdateDTO,
    user: AuthUserDTO = Depends(login_required),
    db: Database = Depends(get_db),
):
    return await RagService.update_session_title(session_id, user.id, body.title, db)


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: int,
    user: AuthUserDTO = Depends(login_required),
    db: Database = Depends(get_db),
):
    deleted = await RagService.delete_session(session_id, user.id, db)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"deleted": True}


@router.post("/sessions/{session_id}/chat")
async def session_chat(
    session_id: int,
    req: RagChatRequestDTO,
    user: AuthUserDTO = Depends(login_required),
    db: Database = Depends(get_db),
):
    if not RagService.is_available():
        return _rag_unavailable()
    q = (req.question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="question required")
    decision = await check_chat_rate_limit(user.id, db)
    if not decision.allowed:
        return _rag_rate_limited(decision.retry_after)
    try:
        result = await RagService.chat(
            session_id,
            user.id,
            q,
            req.stream is not False,
            db,
        )
    except RagAnswerFailed:
        return _error_response("Answer generation failed", "RAGAnswerFailed", 503)
    except RetrievalUnavailable as exc:
        if exc.kind == "too_large":
            return _error_response(
                "This message is too long for search — please shorten it.",
                "RAGQuestionTooLong",
                422,
            )
        return _error_response(
            "Knowledge base search is temporarily unavailable. Please try again.",
            "RAGRetrievalFailed",
            503,
        )
    if isinstance(result, RagChatResponseDTO):
        return result
    return StreamingResponse(
        result, media_type="text/event-stream", headers=_STREAM_HEADERS
    )
