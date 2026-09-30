from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Union

from databases import Database
from loguru import logger
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from chat.dtos import RagChatResponseDTO
from chat.retrieval.llm_answer import LLMService
from chat.turn.decide import CannedTurn, GenerateTurn
from chat.turn.errors import RagAnswerFailed
from chat.turn.persist import (
    log_turn,
    persist_assistant_turn,
    persist_assistant_turn_stream,
)
from chat.turn.plan import PreparedTurn


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
    decision: CannedTurn,
    elapsed_ms: Callable[[], int],
) -> Union[RagChatResponseDTO, AsyncIterator[str]]:
    """Persist + log a canned answer; return a DTO or SSE body iterator."""
    answer = decision.answer
    citations = decision.citations
    candidate_count = decision.candidate_count
    guardrail = decision.guardrail
    model = decision.model
    meta = {
        "session_id": str(session_id),
        "degraded": decision.degraded,
        "candidate_count": candidate_count,
        "guardrail": guardrail,
        "model": model,
    }
    log_tag = (
        decision.log_guardrail if decision.log_guardrail is not None else guardrail
    )

    if not stream:
        await persist_assistant_turn(
            session_id, answer, citations, candidate_count, db, model=model
        )
        log_turn(
            session_id,
            user_id,
            log_tag,
            candidate_count,
            decision.degraded,
            elapsed_ms(),
            decision.domain_status,
            decision.domain_project_id,
        )
        return RagChatResponseDTO(
            answer=answer,
            degraded=decision.degraded,
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
            logger.exception(f"persist {decision.persist_log} failed")
        log_turn(
            session_id,
            user_id,
            log_tag,
            candidate_count,
            decision.degraded,
            elapsed_ms(),
            decision.domain_status,
            decision.domain_project_id,
        )

    return sse_stream(gen(), meta)


async def emit_generated_turn(
    *,
    db: Database,
    session_id: int,
    user_id: int,
    stream: bool,
    question: str,
    prepared: PreparedTurn,
    decision: GenerateTurn,
    llm: LLMService,
    elapsed_ms: Callable[[], int],
) -> Union[RagChatResponseDTO, AsyncIterator[str]]:
    """Generate, persist and emit the LLM answer (DTO or SSE body)."""
    resp = prepared.resp
    citations = prepared.citations
    guardrail_hint = decision.guardrail_hint
    model = getattr(llm, "model", None)
    candidate_count = int(resp.candidate_count)

    if not stream:
        try:
            # Blocking generation runs in a worker thread, not the loop.
            answer = await run_in_threadpool(
                llm.answer,
                question,
                resp.results,
                history=prepared.history,
                domain_evidence=prepared.domain_block,
            )
        except Exception:
            logger.exception("RAG answer failed")
            raise RagAnswerFailed() from None
        await persist_assistant_turn(
            session_id, answer, citations, candidate_count, db, model=model
        )
        log_turn(
            session_id,
            user_id,
            guardrail_hint,
            candidate_count,
            bool(resp.degraded),
            elapsed_ms(),
            prepared.domain_status,
            prepared.domain_project_id,
        )
        return RagChatResponseDTO(
            answer=answer,
            degraded=bool(resp.degraded),
            candidate_count=candidate_count,
            guardrail=public_guardrail(guardrail_hint),
            model=model,
            session_id=str(session_id),
        )

    meta = {
        "session_id": str(session_id),
        "degraded": bool(resp.degraded),
        "candidate_count": candidate_count,
        "guardrail": public_guardrail(guardrail_hint),
        "model": model,
    }

    async def gen():
        full: List[str] = []
        attempts = 0
        stream_failed = False
        while True:
            try:
                # Sync stream generator is consumed in a worker thread.
                async for delta in iterate_in_threadpool(
                    llm.stream(
                        question,
                        resp.results,
                        history=prepared.history,
                        domain_evidence=prepared.domain_block,
                    )
                ):
                    full.append(delta)
                    yield f"data: {json.dumps({'delta': delta})}\n\n"
                break
            except Exception as e:
                # Single retry for transient failures, only if nothing streamed yet.
                if not full and attempts == 0 and retryable_llm_error(e):
                    attempts += 1
                    logger.warning(f"RAG stream transient failure, retrying once: {e}")
                    await asyncio.sleep(1.0)
                    continue
                logger.exception("RAG stream failed")
                stream_failed = True
                yield f"event: error\ndata: {json.dumps({'error': 'Answer generation failed'})}\n\n"
                break

        answer = "".join(full).strip()
        try:
            # A failed stream may produce no text; never persist an empty turn.
            # Never persist a truncated partial after an error mid-stream.
            if answer and not stream_failed:
                await persist_assistant_turn_stream(
                    session_id, answer, citations, candidate_count, model=model
                )
        except Exception:
            logger.exception("persist assistant message failed")
        log_turn(
            session_id,
            user_id,
            guardrail_hint,
            candidate_count,
            bool(resp.degraded),
            elapsed_ms(),
            prepared.domain_status,
            prepared.domain_project_id,
        )

    return sse_stream(gen(), meta)
