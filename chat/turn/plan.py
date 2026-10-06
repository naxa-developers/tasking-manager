from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from loguru import logger
from starlette.concurrency import run_in_threadpool

from chat.constants import MAX_ROUTING_HISTORY
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


def _guardrail_hint(guard: Any) -> str:
    """``gate:verdict reason`` tag; reasons stay server-side."""
    return f"{guard.gate}:{guard.verdict} {guard.reason}"


def _empty_response(mode: str, query: str) -> RetrievalResponse:
    """RetrievalResponse with no KB hits (turns that never call retrieval)."""
    return RetrievalResponse(
        results=[],
        denied_count=0,
        denied_reasons=[],
        candidate_count=0,
        mode=mode,
        query=query,
    )


def _detect_third_party(query: str) -> tuple[bool, Optional[str]]:
    """Third-party profile ask and its username; degrades to (False, None)."""
    try:
        is_third_party = is_third_party_user_query(query)
        username = extract_third_party_username(query) if is_third_party else None
    except Exception:
        return False, None
    return is_third_party, username


def _merge_domain_citations(
    citations: List[RagCitationDTO],
    domain_status: Optional[str],
    pending: List[Dict[str, Any]],
) -> List[RagCitationDTO]:
    """Append domain citations when the domain evidence is authorized."""
    if domain_status != "OK":
        return citations
    for cite in pending:
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
    return citations


def _expand_followup(
    q: str,
    prior: List[Dict[str, Any]],
    guard: Any,
    guardrail_hint: Optional[str],
) -> tuple[str, Any, Optional[str]]:
    """Expand a vague follow-up with the last in-scope question for retrieval.

    History-first order reads naturally and keeps BM25 term proximity stable.
    """
    if guard.verdict != "out_of_scope" or not is_followup_query(q):
        return q, guard, guardrail_hint
    last_user_q = _last_user_message(prior)
    if not last_user_q or classify_query(last_user_q).verdict != "ok":
        return q, guard, guardrail_hint
    retrieval_q = f"{last_user_q} {q}"
    guard = classify_query(retrieval_q)
    guardrail_hint = None  # inherit scope from history
    if guard.verdict != "unsafe":
        # Never let merge word order decide an inherited-unsafe verdict.
        reverse = classify_query(f"{q} {last_user_q}")
        if reverse.verdict == "unsafe":
            guard = reverse
            guardrail_hint = _guardrail_hint(guard)
    return retrieval_q, guard, guardrail_hint


def _strip_smalltalk(
    retrieval_q: str, guard: Any, guardrail_hint: Optional[str]
) -> tuple[str, Any, Optional[str]]:
    """Strip a leading small-talk prefix for retrieval; original q is persisted."""
    try:
        cleaned, had_prefix = strip_smalltalk_prefix(retrieval_q)
    except Exception:
        return retrieval_q, guard, guardrail_hint
    if not had_prefix:
        return retrieval_q, guard, guardrail_hint
    retrieval_q = cleaned
    try:
        guard = classify_query(retrieval_q)
    except Exception:
        pass
    guardrail_hint = (
        _guardrail_hint(guard) if guard.verdict in {"unsafe", "out_of_scope"} else None
    )
    return retrieval_q, guard, guardrail_hint


def _resolve_domain_route(
    retrieval_q: str, prior: List[Dict[str, Any]]
) -> tuple[str, Optional[DomainRoute], bool]:
    """Route the question, folding pending clarifications and inherited ids."""
    # Pending clarification: fold the pending question with the supplied id.
    pending_q = pending_clarification_question(prior)
    if pending_q is not None:
        supplied = resolve_supplied_project_id(retrieval_q)
        if supplied is not None:
            retrieval_q = f"{pending_q} project {supplied}"
    try:
        dron: Optional[DomainRoute] = route_query(retrieval_q)
    except Exception:
        dron = None
    needs_project_id = False
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
    return retrieval_q, dron, needs_project_id


async def _dispatch_evidence(user_id: int, dron: DomainRoute, db: Any) -> Any:
    """Run domain evidence collection; None means keep the KB path alive."""
    try:
        return await collect_evidence(user_id, dron, db)
    except Exception:
        logger.exception("domain dispatch failed; continuing KB-only")
        return None


async def _retrieve_for_turn(
    retrieval_q: str,
    top_k: int,
    dron: Optional[DomainRoute],
    needs_project_id: bool,
) -> RetrievalResponse:
    """Pick the retrieval arm: clarification, DOMAIN-only, or KB (off-loop)."""
    if needs_project_id:
        # No retrieval/embedding call for a clarification turn.
        return _empty_response("clarify", retrieval_q)
    if dron is not None and dron.route == "DOMAIN":
        # DOMAIN-only turn: skip embedding + BM25 entirely.
        return _empty_response("domain-only", retrieval_q)
    # Sync retrieval (embedding HTTP + BM25) runs off the event loop.
    return await run_in_threadpool(retrieve, retrieval_q, top_k=top_k)


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
    guardrail_hint = (
        _guardrail_hint(guard) if guard.verdict in {"unsafe", "out_of_scope"} else None
    )

    top_k = max(TOP_K_MIN, min(TOP_K_MAX, top_k_raw or DEFAULT_TOP_K))

    # Hydrate history from DB unless the caller already did (semantic path).
    if prior is None:
        prior = await RagSession.get_messages(
            session_id, db, limit=MAX_ROUTING_HISTORY, newest_first=True
        )
    history_dicts = _history_dicts(prior)

    # Follow-up expansion and small-talk stripping adjust the retrieval query.
    retrieval_q, guard, guardrail_hint = _expand_followup(
        q, prior, guard, guardrail_hint
    )
    retrieval_q, guard, guardrail_hint = _strip_smalltalk(
        retrieval_q, guard, guardrail_hint
    )

    # Third-party profile asks: deterministic web redirect, never LLM evidence.
    third_party_user, third_party_username = _detect_third_party(retrieval_q)

    await persist_user_turn(session_id, session, q, db)

    if third_party_user:
        # No domain dispatch, no retrieval, no generation for another user's data.
        return PreparedTurn(
            history=history_dicts,
            resp=_empty_response("third-party", retrieval_q),
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
        retrieval_q, dron, needs_project_id = _resolve_domain_route(retrieval_q, prior)
        if dron is not None and dron.route in ("DOMAIN", "BOTH"):
            # DOMAIN/BOTH always carry ops; guard keeps the KB path alive if dispatch breaks.
            outcome = await _dispatch_evidence(user_id, dron, db)
            if outcome is not None:
                domain_route_str = outcome.route
                domain_project_id = outcome.project_id
                domain_status = outcome.status
                domain_block = outcome.block
                pending_citations = [dict(c) for c in outcome.citations]

    resp = await _retrieve_for_turn(retrieval_q, top_k, dron, needs_project_id)
    citations = _merge_domain_citations(
        _build_citations(resp), domain_status, pending_citations
    )

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
