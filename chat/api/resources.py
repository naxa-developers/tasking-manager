from __future__ import annotations

from typing import Any

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
from chat.retrieval.query_kb import DEFAULT_TOP_K
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


def _rag_unavailable() -> JSONResponse:
    logger.warning(f"RAG unavailable: {RagService.unavailable_reason()}")
    return JSONResponse(
        content={
            "Error": "RAG not configured",
            "detail": "RAG is not available on this deployment.",
            "SubCode": "RAGUnavailable",
        },
        status_code=503,
    )


@router.get("/health")
async def rag_health(db: Database = Depends(get_db)) -> Any:
    payload = await RagService.health(db)
    status_code = 200 if payload.get("status") in ("ok", "degraded") else 503
    return JSONResponse(content=payload, status_code=status_code)


@router.get("/ready")
async def rag_ready(db: Database = Depends(get_db)) -> Any:
    payload = await RagService.readiness(db)
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
    try:
        result = await RagService.chat(
            session_id,
            user.id,
            q,
            # Server-owned retrieval depth: req.top_k is deprecated/ignored.
            DEFAULT_TOP_K,
            req.stream is not False,
            db,
        )
    except RagAnswerFailed:
        return JSONResponse(
            content={
                "Error": "Answer generation failed",
                "SubCode": "RAGAnswerFailed",
            },
            status_code=503,
        )
    if isinstance(result, RagChatResponseDTO):
        return result
    return StreamingResponse(
        result, media_type="text/event-stream", headers=_STREAM_HEADERS
    )
