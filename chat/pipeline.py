"""The turn pipeline: six stages, one path.

    question -> injection guard -> route -> retrieve -> gate -> generate

The decision (guard, route, retrieve, gate) is separated from the emission
(generate or canned copy) so that both kinds of answer reach the client through
the same protocol. ``run_turn`` returns a finished turn; ``stream_turn`` yields
deltas and then the finished turn.

There is no session machinery here. Callers pass the conversation history they
want considered.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence, Union

from loguru import logger
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from chat import copy
from chat.domain.dispatch import DomainOutcome, collect
from chat.env import env_int
from chat.generate import Answer, Generator
from chat.guard import detect_injection
from chat.retrieval import RetrievalResponse, ScoredNode, retrieve
from chat.retrieval_gate import gate_decision
from chat.router import RouteDecision, route_question

_TEMPORARY_STATUSES = frozenset({"TIMEOUT", "UNAVAILABLE"})


@dataclass(frozen=True)
class Turn:
    """Everything one turn produced, for the caller to render or audit."""

    answer: str
    route: str
    ops: tuple = ()
    project_id: Optional[int] = None
    citations: List[Dict[str, Any]] = field(default_factory=list)
    candidate_count: int = 0
    model: Optional[str] = None
    # "ok" | "blocked" | "out_of_scope" | "low_confidence"
    # | "domain_unavailable" | "domain_temporary" | "error"
    reason: str = "ok"
    degraded: bool = False


@dataclass(frozen=True)
class Prepared:
    """A routed, fetched turn with no answer yet.

    ``canned`` is set when the turn must not call the model at all — a blocked
    input, or a route whose evidence never arrived.
    """

    question: str
    route: str
    ops: tuple = ()
    project_id: Optional[int] = None
    chunks: Sequence[ScoredNode] = ()
    domain_block: str = ""
    citations: List[Dict[str, Any]] = field(default_factory=list)
    candidate_count: int = 0
    history: tuple = ()
    canned: Optional[str] = None
    reason: str = "ok"
    degraded: bool = False


@dataclass(frozen=True)
class Delta:
    """Incremental answer text."""

    text: str


@dataclass(frozen=True)
class Finished:
    """The completed turn; always the last event of a stream."""

    turn: Turn


StreamEvent = Union[Delta, Finished]


def top_k() -> Optional[int]:
    """Cap fused passages before prompt fitting (``RAG_RETRIEVAL_TOP_K``, 0 = all)."""
    value = env_int("RAG_RETRIEVAL_TOP_K", 5)
    return value if value > 0 else None


def kb_citations(response: RetrievalResponse) -> List[Dict[str, Any]]:
    """Citation records for the retrieved passages, free of internal scores."""
    citations: List[Dict[str, Any]] = []
    for scored in response.results:
        meta = scored.node.metadata or {}
        provenance = meta.get("provenance") or {}
        citations.append(
            {
                "id": scored.node.id_,
                "title": meta.get("title") or "",
                "doc_id": meta.get("doc_id") or "",
                "heading": meta.get("node_heading")
                or meta.get("node_heading_path")
                or "",
                "source_refs": meta.get("source_refs") or meta.get("sources") or [],
                "commit": provenance.get("commit") or meta.get("frozen_commit"),
                "scope": "kb",
            }
        )
    return citations


async def _retrieve(question: str) -> RetrievalResponse:
    """Hybrid retrieval off the event loop; a failure degrades to no passages."""
    try:
        return await run_in_threadpool(retrieve, question, top_k())
    except Exception:
        logger.exception("kb retrieval failed; continuing without passages")
        return RetrievalResponse(
            results=[], candidate_count=0, mode="unavailable", query=question
        )


async def _domain(
    decision: RouteDecision, user_id: Optional[int], db: Any
) -> Optional[DomainOutcome]:
    if user_id is None or db is None or not decision.wants_domain:
        return None
    try:
        return await collect(
            user_id, decision.ops, decision.project_id, decision.filters, db
        )
    except Exception:
        logger.exception("domain collection failed; continuing without evidence")
        return None


def _canned_for_domain(outcome: Optional[DomainOutcome]) -> tuple[str, str]:
    """Copy and reason for a DOMAIN turn that produced no usable evidence."""
    status = outcome.status if outcome is not None else None
    if status in _TEMPORARY_STATUSES:
        return copy.DOMAIN_TEMPORARY_ANSWER, "domain_temporary"
    return copy.DOMAIN_UNAVAILABLE_ANSWER, "domain_unavailable"


async def _no_response(question: str) -> RetrievalResponse:
    """Placeholder for a route that does not retrieve."""
    return RetrievalResponse(
        results=[], candidate_count=0, mode="skipped", query=question
    )


async def prepare_turn(
    question: str,
    *,
    user_id: Optional[int] = None,
    db: Any = None,
    history: Optional[Sequence[Dict[str, str]]] = None,
) -> Prepared:
    """Run the stages that decide what this turn needs, up to the answer."""
    text = (question or "").strip()
    history_list = tuple(history or [])

    if not text:
        return Prepared(
            question=text,
            route="KB",
            history=history_list,
            canned=copy.LOW_CONFIDENCE_ANSWER,
            reason="low_confidence",
        )

    # Stage 1 — the only deterministic decision.
    if detect_injection(text):
        logger.info("turn blocked by injection guard")
        return Prepared(
            question=text,
            route="BLOCKED",
            history=history_list,
            canned=copy.BLOCKED_ANSWER,
            reason="blocked",
        )

    # Stage 2 — the model decides how to answer.
    decision = await route_question(text, history=history_list)
    if decision.is_out_of_scope:
        # A question outside the Tasking Manager is answered deterministically
        # and never reaches retrieval, a domain op, or generation.
        return Prepared(
            question=text,
            route=decision.route,
            history=history_list,
            canned=copy.OUT_OF_SCOPE_ANSWER,
            reason="out_of_scope",
        )
    if user_id is None and decision.wants_domain:
        # Personal and project evidence both need an authenticated asker.
        decision = RouteDecision(route="KB")

    # Stage 3 — gather what the route calls for, concurrently when it wants both.
    kb_response, domain_outcome = await asyncio.gather(
        _retrieve(text) if decision.wants_kb else _no_response(text),
        _domain(decision, user_id, db),
    )

    kb_gate = gate_decision(kb_response, text)
    kb_ok = kb_gate.allow
    chunks = kb_response.results if kb_ok else ()
    domain_block = domain_outcome.block if domain_outcome is not None else ""
    if decision.wants_kb and not kb_ok:
        logger.info(
            "kb gate rejected: reason={} dense={} coverage={} threshold={}",
            kb_gate.reason,
            kb_gate.dense_top1,
            round(kb_gate.coverage, 3),
            kb_gate.dense_threshold,
        )

    # A DOMAIN turn with no usable evidence has a precise answer; don't ask the
    # model to invent one from an empty prompt.
    if decision.route == "DOMAIN" and not domain_block:
        answer, reason = _canned_for_domain(domain_outcome)
        return Prepared(
            question=text,
            route=decision.route,
            ops=decision.ops,
            project_id=decision.project_id,
            history=history_list,
            canned=answer,
            reason=reason,
            degraded=True,
        )

    if not chunks and not domain_block:
        return Prepared(
            question=text,
            route=decision.route,
            ops=decision.ops,
            project_id=decision.project_id,
            history=history_list,
            canned=copy.LOW_CONFIDENCE_ANSWER,
            reason="low_confidence",
            candidate_count=kb_response.candidate_count,
        )

    citations = kb_citations(kb_response) if kb_ok else []
    if domain_outcome is not None:
        citations.extend(domain_outcome.citations)

    return Prepared(
        question=text,
        route=decision.route,
        ops=decision.ops,
        project_id=decision.project_id,
        chunks=chunks,
        domain_block=domain_block,
        citations=citations,
        candidate_count=kb_response.candidate_count,
        history=history_list,
        degraded=decision.degraded
        or (decision.route == "BOTH" and not kb_ok),
    )


def _turn(
    prepared: Prepared,
    answer: str,
    *,
    model: Optional[str] = None,
    reason: Optional[str] = None,
    degraded: Optional[bool] = None,
) -> Turn:
    return Turn(
        answer=answer,
        route=prepared.route,
        ops=prepared.ops,
        project_id=prepared.project_id,
        citations=list(prepared.citations),
        candidate_count=prepared.candidate_count,
        model=model,
        reason=reason or prepared.reason,
        degraded=prepared.degraded if degraded is None else degraded,
    )


async def run_turn(
    question: str,
    *,
    user_id: Optional[int] = None,
    db: Any = None,
    history: Optional[Sequence[Dict[str, str]]] = None,
    generator: Optional[Generator] = None,
) -> Turn:
    """Run one turn end to end and return the finished answer."""
    prepared = await prepare_turn(question, user_id=user_id, db=db, history=history)
    if prepared.canned is not None:
        return _turn(prepared, prepared.canned)

    generator = generator or Generator()
    result: Answer = await run_in_threadpool(
        generator.answer,
        prepared.question,
        prepared.chunks,
        domain_block=prepared.domain_block,
        history=list(prepared.history),
    )
    if result.reason == "error" or not result.text:
        return _turn(
            prepared,
            copy.GENERATION_FAILED_ANSWER,
            model=result.model,
            reason="error",
            degraded=True,
        )
    return _turn(prepared, result.text, model=result.model)


async def stream_turn(
    question: str,
    *,
    user_id: Optional[int] = None,
    db: Any = None,
    history: Optional[Sequence[Dict[str, str]]] = None,
    generator: Optional[Generator] = None,
) -> AsyncIterator[StreamEvent]:
    """Run one turn, yielding deltas and then the finished turn.

    A canned answer is yielded as a single delta, so the client needs one code
    path whether or not the model was called.
    """
    prepared = await prepare_turn(question, user_id=user_id, db=db, history=history)

    if prepared.canned is not None:
        yield Delta(prepared.canned)
        yield Finished(_turn(prepared, prepared.canned))
        return

    generator = generator or Generator()
    parts: List[str] = []
    try:
        async for piece in iterate_in_threadpool(
            generator.stream(
                prepared.question,
                prepared.chunks,
                domain_block=prepared.domain_block,
                history=list(prepared.history),
            )
        ):
            parts.append(piece)
            yield Delta(piece)
    except Exception:
        logger.exception("generation stream failed")
        if not parts:
            # Nothing reached the client, so a canned answer is still honest.
            yield Delta(copy.GENERATION_FAILED_ANSWER)
            yield Finished(
                _turn(
                    prepared,
                    copy.GENERATION_FAILED_ANSWER,
                    model=getattr(generator, "model", None),
                    reason="error",
                    degraded=True,
                )
            )
            return
        # Text already reached the client; finish with it and mark it incomplete.
        answer = "".join(parts).strip()
        yield Finished(
            _turn(
                prepared,
                answer,
                model=getattr(generator, "model", None),
                reason="error",
                degraded=True,
            )
        )
        return

    answer = "".join(parts).strip()
    if not answer:
        yield Delta(copy.GENERATION_FAILED_ANSWER)
        yield Finished(
            _turn(
                prepared,
                copy.GENERATION_FAILED_ANSWER,
                model=getattr(generator, "model", None),
                reason="error",
                degraded=True,
            )
        )
        return
    yield Finished(_turn(prepared, answer, model=getattr(generator, "model", None)))
