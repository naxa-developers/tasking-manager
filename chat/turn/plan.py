from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger
from starlette.concurrency import run_in_threadpool

from chat.dtos import RagCitationDTO
from chat.env import env_int
from chat.models import RagSession
from chat.retrieval.domain.dispatch import collect_evidence
from chat.retrieval.domain.llm_router import DomainRoute, route_question
from chat.retrieval.domain.references import (
    extract_third_party_username,
    is_third_party_user_query,
)
from chat.retrieval.guardrails import (
    classify_query,
    is_followup_query,
    strip_smalltalk_prefix,
)
from chat.retrieval.project_context import (
    pending_clarification_question,
    resolve_supplied_project_id,
)
from chat.retrieval.query_kb import RetrievalResponse, retrieve
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


def guardrail_hint(guard: Any) -> str:
    """``gate:verdict reason`` tag; reasons stay server-side."""
    return f"{guard.gate}:{guard.verdict} {guard.reason}"


def initial_guardrail_hint(guard: Any) -> Optional[str]:
    """Hint for a fresh turn: only unsafe/out-of-scope verdicts carry one."""
    return (
        guardrail_hint(guard) if guard.verdict in {"unsafe", "out_of_scope"} else None
    )


def empty_response(mode: str, query: str) -> RetrievalResponse:
    """RetrievalResponse with no KB hits (turns that never call retrieval)."""
    return RetrievalResponse(
        results=[],
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
    hint: Optional[str],
) -> tuple[str, Any, Optional[str]]:
    """Expand a vague follow-up with the last in-scope question for retrieval.

    History-first order reads naturally and keeps BM25 term proximity stable.
    """
    if guard.verdict != "out_of_scope" or not is_followup_query(q):
        return q, guard, hint
    last_user_q = _last_user_message(prior)
    if not last_user_q or classify_query(last_user_q).verdict != "ok":
        return q, guard, hint
    retrieval_q = f"{last_user_q} {q}"
    guard = classify_query(retrieval_q)
    hint = None  # inherit scope from history
    if guard.verdict != "unsafe":
        # Never let merge word order decide an inherited-unsafe verdict.
        reverse = classify_query(f"{q} {last_user_q}")
        if reverse.verdict == "unsafe":
            guard = reverse
            hint = guardrail_hint(guard)
    return retrieval_q, guard, hint


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
    guardrail_hint = initial_guardrail_hint(guard)
    return retrieval_q, guard, guardrail_hint


def _with_project(text: str, project_id: int) -> str:
    """Append ``project {id}`` so the router/fetchers can scope the question."""
    return f"{text} project {project_id}"


async def _resolve_domain_route(
    retrieval_q: str, prior: List[Dict[str, Any]]
) -> tuple[str, Optional[DomainRoute], bool]:
    """Route the question, folding a pending clarification reply into it.

    The router grounds project ids from the current question and prior user
    turns, so a fold is not re-routed through the model.
    """
    pending_q = pending_clarification_question(prior)
    if pending_q is not None:
        supplied = resolve_supplied_project_id(retrieval_q)
        if supplied is not None:
            retrieval_q = _with_project(pending_q, supplied)
    domain_route: Optional[DomainRoute] = await route_question(
        retrieval_q, history=prior
    )
    needs_project_id = bool(domain_route is not None and domain_route.needs_project_id)
    if needs_project_id:
        domain_route = None
    return retrieval_q, domain_route, needs_project_id


async def _dispatch_evidence(user_id: int, domain_route: DomainRoute, db: Any) -> Any:
    """Run domain evidence collection; None means keep the KB path alive."""
    try:
        return await collect_evidence(user_id, domain_route, db)
    except Exception:
        logger.exception("domain dispatch failed; continuing KB-only")
        return None


def _retrieval_top_k() -> Optional[int]:
    """Cap fused results before prompt fitting (0 = uncapped)."""
    value = env_int("RAG_RETRIEVAL_TOP_K", 5)
    return value if value > 0 else None


async def _retrieve_for_turn(
    retrieval_q: str,
    domain_route: Optional[DomainRoute],
    needs_project_id: bool,
) -> RetrievalResponse:
    """Pick the retrieval arm: clarification, DOMAIN-only, or KB (off-loop)."""
    if needs_project_id:
        # No retrieval/embedding call for a clarification turn.
        return empty_response("clarify", retrieval_q)
    if domain_route is not None and domain_route.route == "DOMAIN":
        # DOMAIN-only turn: skip embedding + BM25 entirely.
        return empty_response("domain-only", retrieval_q)
    # Sync retrieval (embedding HTTP + BM25) runs off the event loop.
    return await run_in_threadpool(retrieve, retrieval_q, _retrieval_top_k())


@dataclass(frozen=True)
class _DomainArm:
    """Domain-routing outcome; retrieval continues on the (folded) query."""

    retrieval_q: str
    domain_route: Optional[DomainRoute]
    needs_project_id: bool
    status: Optional[str] = None
    route_str: Optional[str] = None
    project_id: Optional[int] = None
    block: str = ""
    pending_citations: List[Dict[str, Any]] = field(default_factory=list)


async def _run_domain_arm(
    user_id: Optional[int],
    retrieval_q: str,
    prior: List[Dict[str, Any]],
    db: Any,
) -> _DomainArm:
    """Resolve the domain route and collect evidence when a route matched."""
    if user_id is None:
        return _DomainArm(
            retrieval_q=retrieval_q, domain_route=None, needs_project_id=False
        )
    retrieval_q, domain_route, needs_project_id = await _resolve_domain_route(
        retrieval_q, prior
    )
    arm = _DomainArm(
        retrieval_q=retrieval_q,
        domain_route=domain_route,
        needs_project_id=needs_project_id,
    )
    if domain_route is None or domain_route.route not in ("DOMAIN", "BOTH"):
        return arm
    # DOMAIN/BOTH always carry ops; a failed dispatch keeps the KB path alive.
    outcome = await _dispatch_evidence(user_id, domain_route, db)
    if outcome is None:
        return arm
    return _DomainArm(
        retrieval_q=retrieval_q,
        domain_route=domain_route,
        needs_project_id=needs_project_id,
        status=outcome.status,
        route_str=outcome.route,
        project_id=outcome.project_id,
        block=outcome.block,
        pending_citations=[dict(c) for c in outcome.citations],
    )


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
    session: Any,
    db: Any,
    guard: Any,
    user_id: Optional[int] = None,
    prior: Optional[List[Dict[str, Any]]] = None,
) -> PreparedTurn:
    """Validate, persist the user turn, hydrate history, and run retrieval."""
    session_id = session["id"]
    guardrail_hint = initial_guardrail_hint(guard)

    # Hydrate history from DB unless the caller already provided it.
    if prior is None:
        prior = await RagSession.get_messages(session_id, db, newest_first=True)
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
        return _third_party_turn(
            history_dicts, retrieval_q, guard, guardrail_hint, third_party_username
        )

    # Domain routing: one LLM call returns a validated DomainRoute.
    # Auth always runs inside the tool.
    arm = await _run_domain_arm(user_id, retrieval_q, prior, db)
    resp = await _retrieve_for_turn(
        arm.retrieval_q, arm.domain_route, arm.needs_project_id
    )
    return _assembled_turn(history_dicts, resp, guard, guardrail_hint, arm)


def _third_party_turn(
    history: List[Dict[str, str]],
    retrieval_q: str,
    guard: Any,
    guardrail_hint: Optional[str],
    username: Optional[str],
) -> PreparedTurn:
    """Canned web-profile redirect turn; no domain dispatch or retrieval."""
    return PreparedTurn(
        history=history,
        resp=empty_response("third-party", retrieval_q),
        citations=[],
        guardrail_hint=guardrail_hint,
        scope_verdict=guard.verdict,
        domain_block="",
        domain_status=None,
        domain_project_id=None,
        domain_route_str=None,
        third_party_user=True,
        third_party_username=username,
    )


def _assembled_turn(
    history: List[Dict[str, str]],
    resp: RetrievalResponse,
    guard: Any,
    guardrail_hint: Optional[str],
    arm: _DomainArm,
) -> PreparedTurn:
    """Merge KB citations with the domain arm into the prepared turn."""
    citations = _merge_domain_citations(
        _build_citations(resp), arm.status, arm.pending_citations
    )
    return PreparedTurn(
        history=history,
        resp=resp,
        citations=citations,
        guardrail_hint=guardrail_hint,
        scope_verdict=guard.verdict,
        domain_block=arm.block,
        domain_status=arm.status,
        domain_project_id=arm.project_id,
        domain_route_str=arm.route_str,
        needs_project_id=arm.needs_project_id,
    )
