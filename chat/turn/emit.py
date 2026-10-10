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


def _sse_meta(
    session_id: int,
    degraded: bool,
    candidate_count: int,
    guardrail: Optional[str],
    model: Optional[str],
) -> Dict[str, Any]:
    """SSE meta payload; key order is part of the wire contract."""
    return {
        "session_id": str(session_id),
        "degraded": degraded,
        "candidate_count": candidate_count,
        "guardrail": guardrail,
        "model": model,
    }


def _log_turn(
    session_id: int,
    user_id: int,
    tag: Optional[str],
    candidate_count: int,
    degraded: bool,
    elapsed: int,
    domain_status: Optional[str],
    domain_project_id: Optional[int],
) -> None:
    """Shared 8-arg turn log; log_turn stays patchable by module name."""
    log_turn(
        session_id,
        user_id,
        tag,
        candidate_count,
        degraded,
        elapsed,
        domain_status,
        domain_project_id,
    )


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
    if stream:
        return _canned_stream_body(session_id, user_id, decision, elapsed_ms)
    return await _canned_json_response(db, session_id, user_id, decision, elapsed_ms)


async def _canned_json_response(
    db: Database,
    session_id: int,
    user_id: int,
    decision: CannedTurn,
    elapsed_ms: Callable[[], int],
) -> RagChatResponseDTO:
    await persist_assistant_turn(
        session_id,
        decision.answer,
        decision.citations,
        decision.candidate_count,
        db,
        model=decision.model,
    )
    _canned_log(session_id, user_id, decision, elapsed_ms)
    return RagChatResponseDTO(
        answer=decision.answer,
        degraded=decision.degraded,
        candidate_count=decision.candidate_count,
        guardrail=decision.guardrail,
        model=decision.model,
        session_id=str(session_id),
    )


def _canned_stream_body(
    session_id: int,
    user_id: int,
    decision: CannedTurn,
    elapsed_ms: Callable[[], int],
) -> AsyncIterator[str]:
    async def gen() -> AsyncIterator[str]:
        yield f"data: {json.dumps({'delta': decision.answer})}\n\n"
        try:
            await persist_assistant_turn_stream(
                session_id,
                decision.answer,
                decision.citations,
                decision.candidate_count,
                model=decision.model,
            )
        except Exception:
            logger.exception(f"persist {decision.persist_log} failed")
        _canned_log(session_id, user_id, decision, elapsed_ms)

    return sse_stream(
        gen(),
        _sse_meta(
            session_id,
            decision.degraded,
            decision.candidate_count,
            decision.guardrail,
            decision.model,
        ),
    )


def _canned_log(
    session_id: int,
    user_id: int,
    decision: CannedTurn,
    elapsed_ms: Callable[[], int],
) -> None:
    tag = (
        decision.log_guardrail
        if decision.log_guardrail is not None
        else decision.guardrail
    )
    _log_turn(
        session_id,
        user_id,
        tag,
        decision.candidate_count,
        decision.degraded,
        elapsed_ms(),
        decision.domain_status,
        decision.domain_project_id,
    )


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
    if stream:
        return _generated_stream_body(
            session_id, user_id, question, prepared, decision, llm, elapsed_ms
        )
    return await _generated_json_response(
        db, session_id, user_id, question, prepared, decision, llm, elapsed_ms
    )


async def _generated_json_response(
    db: Database,
    session_id: int,
    user_id: int,
    question: str,
    prepared: PreparedTurn,
    decision: GenerateTurn,
    llm: LLMService,
    elapsed_ms: Callable[[], int],
) -> RagChatResponseDTO:
    model = getattr(llm, "model", None)
    candidate_count = int(prepared.resp.candidate_count)
    try:
        # Blocking generation runs in a worker thread, not the loop.
        answer = await run_in_threadpool(
            llm.answer,
            question,
            prepared.resp.results,
            history=prepared.history,
            domain_evidence=prepared.domain_block,
        )
    except Exception:
        logger.exception("RAG answer failed")
        raise RagAnswerFailed() from None
    await persist_assistant_turn(
        session_id, answer, prepared.citations, candidate_count, db, model=model
    )
    _log_turn(
        session_id,
        user_id,
        decision.guardrail_hint,
        candidate_count,
        False,
        elapsed_ms(),
        prepared.domain_status,
        prepared.domain_project_id,
    )
    return RagChatResponseDTO(
        answer=answer,
        degraded=False,
        candidate_count=candidate_count,
        guardrail=public_guardrail(decision.guardrail_hint),
        model=model,
        session_id=str(session_id),
    )


def _generated_stream_body(
    session_id: int,
    user_id: int,
    question: str,
    prepared: PreparedTurn,
    decision: GenerateTurn,
    llm: LLMService,
    elapsed_ms: Callable[[], int],
) -> AsyncIterator[str]:
    resp = prepared.resp
    citations = prepared.citations
    guardrail_hint = decision.guardrail_hint
    model = getattr(llm, "model", None)
    candidate_count = int(resp.candidate_count)

    async def gen() -> AsyncIterator[str]:
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
        _log_turn(
            session_id,
            user_id,
            guardrail_hint,
            candidate_count,
            False,
            elapsed_ms(),
            prepared.domain_status,
            prepared.domain_project_id,
        )

    return sse_stream(
        gen(),
        _sse_meta(
            session_id, False, candidate_count, public_guardrail(guardrail_hint), model
        ),
    )
