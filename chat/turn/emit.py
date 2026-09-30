from __future__ import annotations

import json
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Union

from databases import Database
from loguru import logger

from chat.dtos import RagChatResponseDTO, RagCitationDTO
from chat.turn.persist import (
    log_turn,
    persist_assistant_turn,
    persist_assistant_turn_stream,
)


def public_guardrail(hint: Optional[str]) -> Optional[str]:
    """Client-facing guardrail tag: gate:verdict only; reasons stay server-side."""
    if not hint:
        return None
    head = hint.split(" ", 1)[0]
    parts = head.split(":", 1)
    return ":".join(parts[:2]) if len(parts) == 2 else head


def retryable_llm_error(exc: Exception) -> bool:
    """True for transient LLM failures worth a single retry (429 / 5xx)."""
    status = getattr(exc, "status_code", None)
    if status in (429, 500, 502, 503, 504):
        return True
    name = type(exc).__name__
    return any(
        k in name
        for k in (
            "RateLimit",
            "Timeout",
            "APIConnection",
            "InternalServer",
            "ServiceUnavailable",
        )
    )


def sse_stream(gen: AsyncIterator[str], meta: Dict[str, Any]) -> AsyncIterator[str]:
    """Wrap a chunk/delta generator with trailing meta + done events."""

    async def inner() -> AsyncIterator[str]:
        async for item in gen:
            yield item
        yield f"event: meta\ndata: {json.dumps(meta)}\n\n"
        yield "event: done\ndata: {}\n\n"

    return inner()


async def emit_canned_turn(
    *,
    db: Database,
    session_id: int,
    user_id: int,
    stream: bool,
    answer: str,
    citations: List[RagCitationDTO],
    candidate_count: int,
    guardrail: str,
    elapsed_ms: Callable[[], int],
    log_guardrail: Optional[str] = None,
    degraded: bool = False,
    domain_status: Optional[str] = None,
    domain_project_id: Optional[int] = None,
    persist_log: str = "assistant message",
    # None for deterministic (canned) answers — no generation ran.
    model: Optional[str] = None,
) -> Union[RagChatResponseDTO, AsyncIterator[str]]:
    """Persist + log a canned answer; return a DTO or SSE body iterator."""
    meta = {
        "session_id": str(session_id),
        "degraded": degraded,
        "candidate_count": candidate_count,
        "guardrail": guardrail,
        "model": model,
    }
    log_tag = log_guardrail if log_guardrail is not None else guardrail

    if not stream:
        await persist_assistant_turn(
            session_id, answer, citations, candidate_count, db, model=model
        )
        log_turn(
            session_id,
            user_id,
            log_tag,
            candidate_count,
            degraded,
            elapsed_ms(),
            domain_status,
            domain_project_id,
        )
        return RagChatResponseDTO(
            answer=answer,
            degraded=degraded,
            candidate_count=candidate_count,
            guardrail=guardrail,
            model=model,
            session_id=str(session_id),
        )

    async def gen():
        yield f"data: {json.dumps({'delta': answer})}\n\n"
        try:
            await persist_assistant_turn_stream(
                session_id, answer, citations, candidate_count, model=model
            )
        except Exception:
            logger.exception(f"persist {persist_log} failed")
        log_turn(
            session_id,
            user_id,
            log_tag,
            candidate_count,
            degraded,
            elapsed_ms(),
            domain_status,
            domain_project_id,
        )

    return sse_stream(gen(), meta)
