from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from loguru import logger
from starlette.concurrency import run_in_threadpool

from chat.dtos import RagCitationDTO
from chat.models import RagSession
from chat.retrieval.domain.dispatch import collect_evidence
from chat.retrieval.domain.routing import (
    DomainRoute,
    extract_third_party_username,
    is_third_party_user_query,
    route_query,
)
from chat.retrieval.guardrails import (
    classify_query,
    is_followup_query,
    strip_smalltalk_prefix,
)
from chat.retrieval.project_context import (
    latest_explicit_project_id,
    pending_clarification_question,
    resolve_supplied_project_id,
)
from chat.retrieval.query_kb import (
    DEFAULT_TOP_K,
    TOP_K_MAX,
    TOP_K_MIN,
    RetrievalResponse,
    retrieve,
)
from chat.turn.persist import persist_user_turn

# Server-side history lookback for the deterministic layer (not the LLM cap).
MAX_ROUTING_HISTORY = 10


def _build_citations(resp: Any) -> List[RagCitationDTO]:
    citations: List[RagCitationDTO] = []
    for scored in resp.results:
        meta = scored.node.metadata or {}
        prov = meta.get("provenance") or {}
        citations.append(
            RagCitationDTO(
                id=scored.node.id_,
                title=meta.get("title") or "",
                doc_id=meta.get("doc_id") or "",
                heading=meta.get("node_heading") or meta.get("node_heading_path") or "",
                source_refs=meta.get("source_refs") or meta.get("sources") or [],
                commit=prov.get("commit") or meta.get("frozen_commit"),
            )
        )
    return citations


def _history_dicts(messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    return [
        {"role": m["role"], "content": m["content"]}
        for m in messages
        if m.get("role") in {"user", "assistant"}
    ]


def _last_user_message(prior: List[Dict[str, Any]]) -> Optional[str]:
    """Most recent user question in the hydrated window."""
    for m in reversed(prior):
        if m.get("role") == "user":
            return m.get("content", "")
    return None


@dataclass(frozen=True)
class PreparedTurn:
    """Everything one chat turn needs after guardrails + retrieval."""

    history: List[Dict[str, str]]
    resp: Any
    citations: List[RagCitationDTO]
    guardrail_hint: Optional[str]
    scope_verdict: str
    domain_block: str
    domain_status: Optional[str]
    domain_project_id: Optional[int]
    domain_route_str: Optional[str]
    needs_project_id: bool = False
    third_party_user: bool = False
    third_party_username: Optional[str] = None


async def prepare_turn(
    q: str,
    top_k_raw: int,
    session: Any,
    db: Any,
    guard: Any,
    user_id: Optional[int] = None,
    prior: Optional[List[Dict[str, Any]]] = None,
) -> PreparedTurn:
    """Validate, persist the user turn, hydrate history, and run retrieval."""
    session_id = session["id"]
    guardrail_hint = None
    if guard.verdict in {"unsafe", "out_of_scope"}:
        guardrail_hint = f"{guard.gate}:{guard.verdict} {guard.reason}"

    top_k = max(TOP_K_MIN, min(TOP_K_MAX, top_k_raw or DEFAULT_TOP_K))

    # Hydrate history from DB unless the caller already did (semantic path).
    if prior is None:
        prior = await RagSession.get_messages(
            session_id, db, limit=MAX_ROUTING_HISTORY, newest_first=True
        )
    history_dicts = _history_dicts(prior)

    retrieval_q = q
    # Follow-up handling: vague q + TM context in history -> expand it.
    # History-first order reads naturally and keeps BM25 term proximity stable.
    if guard.verdict == "out_of_scope" and is_followup_query(q):
        last_user_q = _last_user_message(prior)
        if last_user_q and classify_query(last_user_q).verdict == "ok":
            retrieval_q = f"{last_user_q} {q}"
            guardrail_hint = None  # inherit scope from history
            guard = classify_query(retrieval_q)
            if guard.verdict != "unsafe":
                # Never let merge word order decide an inherited-unsafe verdict.
                reverse = classify_query(f"{q} {last_user_q}")
                if reverse.verdict == "unsafe":
                    guard = reverse
                    guardrail_hint = f"{guard.gate}:{guard.verdict} {guard.reason}"

    # Strip a leading small-talk prefix for retrieval; original q is persisted.
    try:
        _cleaned, _had_prefix = strip_smalltalk_prefix(retrieval_q)
    except Exception:
        _cleaned, _had_prefix = retrieval_q, False
    if _had_prefix:
        retrieval_q = _cleaned
        try:
            guard = classify_query(retrieval_q)
        except Exception:
            pass
        if guard.verdict in {"unsafe", "out_of_scope"}:
            guardrail_hint = f"{guard.gate}:{guard.verdict} {guard.reason}"
        else:
            guardrail_hint = None

    # Third-party profile asks: deterministic web redirect, never LLM evidence.
    try:
        third_party_user = is_third_party_user_query(retrieval_q)
        third_party_username = (
            extract_third_party_username(retrieval_q) if third_party_user else None
        )
    except Exception:
        third_party_user = False
        third_party_username = None

    await persist_user_turn(session_id, session, q, db)

    if third_party_user:
        # No domain dispatch, no retrieval, no generation for another user's data.
        return PreparedTurn(
            history=history_dicts,
            resp=RetrievalResponse(
                results=[],
                denied_count=0,
                denied_reasons=[],
                candidate_count=0,
                mode="third-party",
                query=retrieval_q,
            ),
            citations=[],
            guardrail_hint=guardrail_hint,
            scope_verdict=guard.verdict,
            domain_block="",
            domain_status=None,
            domain_project_id=None,
            domain_route_str=None,
            third_party_user=True,
            third_party_username=third_party_username,
        )

    # Domain routing: validated classifier intents on the semantic path, the
    # deterministic router otherwise. Auth always runs inside the tool.
    domain_block = ""
    domain_status: Optional[str] = None
    domain_project_id: Optional[int] = None
    domain_route_str: Optional[str] = None
    pending_citations: List[Dict[str, Any]] = []
    needs_project_id = False
    dron: Optional[DomainRoute] = None
    if user_id is not None:
        # Pending clarification: fold the pending question with the supplied id.
        pending_q = pending_clarification_question(prior)
        if pending_q is not None:
            supplied = resolve_supplied_project_id(retrieval_q)
            if supplied is not None:
                retrieval_q = f"{pending_q} project {supplied}"
        try:
            dron = route_query(retrieval_q)
        except Exception:
            dron = None
        if dron is not None and dron.needs_project_id:
            # Never guess an id: use this turn's text, else the latest explicit id.
            supplied = resolve_supplied_project_id(retrieval_q)
            if supplied is not None:
                retrieval_q = f"{retrieval_q} project {supplied}"
                dron = route_query(retrieval_q)
            if dron.needs_project_id:
                inherited = latest_explicit_project_id(prior)
                if inherited is not None:
                    retrieval_q = f"{retrieval_q} project {inherited}"
                    dron = route_query(retrieval_q)
            if dron.needs_project_id:
                needs_project_id = True
                dron = None
        if dron is not None and dron.route in ("DOMAIN", "BOTH"):
            # DOMAIN/BOTH always carry ops; guard keeps the KB path alive if dispatch breaks.
            try:
                outcome = await collect_evidence(user_id, dron, db)
            except Exception:
                logger.exception("domain dispatch failed; continuing KB-only")
                outcome = None
            if outcome is not None:
                domain_route_str = outcome.route
                domain_project_id = outcome.project_id
                domain_status = outcome.status
                domain_block = outcome.block
                pending_citations = [dict(c) for c in outcome.citations]

    if needs_project_id:
        # No retrieval/embedding call for a clarification turn.
        resp = RetrievalResponse(
            results=[],
            denied_count=0,
            denied_reasons=[],
            candidate_count=0,
            mode="clarify",
            query=retrieval_q,
        )
    elif dron is not None and dron.route == "DOMAIN":
        # DOMAIN-only turn: skip embedding + BM25 entirely.
        resp = RetrievalResponse(
            results=[],
            denied_count=0,
            denied_reasons=[],
            candidate_count=0,
            mode="domain-only",
            query=retrieval_q,
        )
    else:
        # Sync retrieval (embedding HTTP + BM25) runs off the event loop.
        resp = await run_in_threadpool(retrieve, retrieval_q, top_k=top_k)
    citations = _build_citations(resp)
    if domain_status == "OK":
        for cite in pending_citations:
            try:
                citations.append(
                    RagCitationDTO(
                        id=cite["id"],
                        title=cite["title"],
                        doc_id=cite["doc_id"],
                        heading=cite["heading"],
                        source_refs=cite["source_refs"],
                        commit=cite.get("commit"),
                    )
                )
            except Exception:
                continue

    return PreparedTurn(
        history=history_dicts,
        resp=resp,
        citations=citations,
        guardrail_hint=guardrail_hint,
        scope_verdict=guard.verdict,
        domain_block=domain_block,
        domain_status=domain_status,
        domain_project_id=domain_project_id,
        domain_route_str=domain_route_str,
        needs_project_id=needs_project_id,
    )
