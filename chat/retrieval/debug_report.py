"""Build a full audit report for one TMBot turn.

Mirrors the branch selection in ``chat/service.py`` (guardrails -> routing ->
domain/KB evidence -> canned vs LLM) so a debugging run reproduces production
decisions without persisting a session. Used by
``chat/retrieval/scripts/debug_turn.py`` and covered by
``chat/tests/test_debug_report.py``.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from chat.retrieval.config import get_generation_config
from chat.retrieval.domain.dispatch import collect_evidence
from chat.retrieval.domain.routing import (
    DomainRoute,
    extract_third_party_username,
    is_third_party_user_query,
    route_query,
)
from chat.retrieval.guardrails import (
    GuardrailDecision,
    classify_query,
    is_smalltalk_query,
    smalltalk_kind,
)
from chat.retrieval.llm_answer import LLMService, _count_tokens, _prompt_token_budget
from chat.retrieval.policy import conf_threshold, is_low_confidence
from chat.retrieval.query_kb import RetrievalResponse, retrieve
from chat.turn.decide import CannedTurn, decide_early_turn, decide_turn
from chat.turn.plan import PreparedTurn, empty_response, initial_guardrail_hint

SECTIONS: Tuple[str, ...] = ("decisions", "kb", "domain", "prompt", "answer")


def resolve_sections(raw: str) -> Tuple[str, ...]:
    """Parse a ``--show`` value; empty or ``all`` selects every section."""
    items = [part.strip().lower() for part in (raw or "").split(",") if part.strip()]
    if not items or "all" in items:
        return SECTIONS
    unknown = [part for part in items if part not in SECTIONS]
    if unknown:
        raise ValueError(
            "unknown section(s): "
            + ", ".join(unknown)
            + "; choose from "
            + ", ".join(SECTIONS)
            + " or all"
        )
    return tuple(dict.fromkeys(items))


def _snippet(text: Optional[str], limit: int) -> str:
    snippet = " ".join((text or "").split())
    if limit > 0 and len(snippet) > limit:
        snippet = snippet[:limit].rsplit(" ", 1)[0] + "…"
    return snippet


def scored_to_dict(scored: Any, snippet_chars: int = 360) -> Dict[str, Any]:
    """Allowlisted view of one retrieved KB chunk (no raw node objects)."""
    meta = scored.node.metadata or {}
    provenance = meta.get("provenance") or {}
    return {
        "node_id": scored.node.id_,
        "title": meta.get("title", ""),
        "doc_id": meta.get("doc_id", ""),
        "heading": meta.get("node_heading") or meta.get("node_heading_path") or "",
        "fused_score": round(float(scored.fused_score), 4),
        "vector_rank": scored.vector_rank,
        "bm25_rank": scored.bm25_rank,
        "needs_verification": bool(meta.get("needs_verification")),
        "source_refs": meta.get("source_refs") or meta.get("sources") or [],
        "commit": provenance.get("commit") or meta.get("frozen_commit"),
        "snippet": _snippet(getattr(scored.node, "text", ""), snippet_chars),
    }


def build_decisions(question: str, route: DomainRoute) -> Dict[str, Any]:
    """Deterministic guardrail + routing decision for one question."""
    guard = classify_query(question)
    smalltalk = is_smalltalk_query(question)
    third_party = is_third_party_user_query(question)
    return {
        "guardrail": {
            "verdict": guard.verdict,
            "gate": guard.gate,
            "reason": guard.reason,
        },
        "smalltalk": smalltalk,
        "smalltalk_kind": smalltalk_kind(question) if smalltalk else None,
        "third_party_user": third_party,
        "third_party_username": (
            extract_third_party_username(question) if third_party else None
        ),
        "route": route.route,
        "ops": list(route.ops),
        "project_id": route.project_id,
        "needs_project_id": route.needs_project_id,
        "filters": dict(route.filters),
    }


def kb_to_dict(
    resp: Optional[RetrievalResponse], snippet_chars: int = 360
) -> Dict[str, Any]:
    """Retrieval summary + ranked chunks; ``ran`` is False when skipped."""
    if resp is None:
        return {"ran": False}
    top = resp.results[0].fused_score if resp.results else None
    return {
        "ran": True,
        "mode": resp.mode,
        "query": resp.query,
        "candidate_count": resp.candidate_count,
        "denied_count": resp.denied_count,
        "degraded": resp.degraded,
        "degraded_reason": resp.degraded_reason,
        "timing_ms": resp.timing_ms,
        "threshold": conf_threshold(),
        "top_score": round(float(top), 4) if top is not None else None,
        "low_confidence": is_low_confidence(resp),
        "results": [scored_to_dict(scored, snippet_chars) for scored in resp.results],
    }


def domain_to_dict(
    route: DomainRoute, outcome: Any, skipped: str = ""
) -> Dict[str, Any]:
    """Domain op status + the exact evidence block sent to the LLM."""
    if outcome is None:
        return {"ran": False, "ops": list(route.ops), "skipped": skipped or None}
    return {
        "ran": True,
        "status": outcome.status,
        "ops": list(route.ops),
        "project_id": outcome.project_id,
        "block": outcome.block,
        "citations": [dict(citation) for citation in outcome.citations],
    }


def prompt_to_dict(
    llm: LLMService,
    question: str,
    results: List[Any],
    history: Optional[List[Dict[str, str]]],
    domain_block: str,
) -> Dict[str, Any]:
    """Exact system + user prompt the LLM would receive."""
    system_prompt, user_prompt = llm._build_messages(
        question, results, history=history, domain_evidence=domain_block
    )
    return {
        "ran": user_prompt is not None,
        "budget": _prompt_token_budget(),
        "system_tokens": _count_tokens(system_prompt),
        "user_tokens": _count_tokens(user_prompt) if user_prompt else 0,
        "system": system_prompt,
        "user": user_prompt,
    }


def canned_answer(
    question: str,
    guard: GuardrailDecision,
    decisions: Dict[str, Any],
    outcome: Any,
    resp: Optional[RetrievalResponse],
) -> Optional[str]:
    """The deterministic answer production would return, if any (no LLM).

    Delegates to the production turn decisions (``decide_early_turn`` /
    ``decide_turn``) so a debugging run cannot drift from the service path.
    """
    early = decide_early_turn(guard, question)
    if early is not None:
        return early.answer
    prepared = PreparedTurn(
        history=[],
        resp=resp if resp is not None else empty_response("debug-skip", question),
        citations=[],
        guardrail_hint=initial_guardrail_hint(guard),
        scope_verdict=guard.verdict,
        domain_block=outcome.block if outcome is not None else "",
        domain_status=outcome.status if outcome is not None else None,
        domain_project_id=outcome.project_id if outcome is not None else None,
        domain_route_str=outcome.route if outcome is not None else None,
        needs_project_id=bool(decisions["needs_project_id"]),
        third_party_user=bool(decisions["third_party_user"]),
        third_party_username=decisions["third_party_username"],
    )
    decision = decide_turn(prepared)
    return decision.answer if isinstance(decision, CannedTurn) else None


def _generation_meta(llm: LLMService) -> Dict[str, Any]:
    model = llm.model
    temperature = None
    max_tokens = None
    try:
        config = get_generation_config()
        model = model or config.model
        temperature = config.temperature
        max_tokens = config.max_tokens
    except Exception:
        pass
    return {"model": model, "temperature": temperature, "max_tokens": max_tokens}


async def gather_turn(
    db: Any,
    question: str,
    user_id: Optional[int] = None,
    top_k: int = 5,
    history: Optional[List[Dict[str, str]]] = None,
    snippet_chars: int = 360,
    generate: bool = True,
) -> Dict[str, Any]:
    """Run one turn through the production decision path, capturing every layer."""
    route = route_query(question)
    decisions = build_decisions(question, route)

    resp: Optional[RetrievalResponse] = None
    outcome: Any = None
    skipped = ""
    if not (decisions["third_party_user"] or decisions["needs_project_id"]):
        if route.route in ("DOMAIN", "BOTH") and route.ops:
            if user_id is None:
                skipped = "no --user-id supplied; domain ops need an authenticated user"
            else:
                outcome = await collect_evidence(user_id, route, db)
        if route.route != "DOMAIN":
            resp = retrieve(question, top_k=top_k)

    domain_block = outcome.block if outcome is not None else ""
    if outcome is not None:
        decisions["domain_status"] = outcome.status
    kb = kb_to_dict(resp, snippet_chars)
    domain = domain_to_dict(route, outcome, skipped)
    results = list(resp.results) if resp is not None else []

    llm = LLMService()
    has_evidence = bool(results or domain_block.strip())
    prompt = (
        prompt_to_dict(llm, question, results, history, domain_block)
        if has_evidence
        else {"ran": False}
    )

    guard = GuardrailDecision(**decisions["guardrail"])
    canned = canned_answer(question, guard, decisions, outcome, resp)

    answer: Dict[str, Any] = {"ran": False}
    if canned is not None:
        answer = {"ran": False, "canned": canned, "reason": "deterministic branch"}
    elif not generate:
        answer = {"ran": False, "reason": "generation not requested"}
    elif prompt.get("user"):
        started = time.monotonic()
        text = llm.answer(
            question, results, history=history, domain_evidence=domain_block
        )
        answer = {
            "ran": True,
            "text": text,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            **_generation_meta(llm),
        }

    return {
        "meta": {
            "question": question,
            "user_id": user_id,
            "top_k": top_k,
            "history_turns": len(history or []),
            **_generation_meta(llm),
        },
        "decisions": decisions,
        "kb": kb,
        "domain": domain,
        "prompt": prompt,
        "answer": answer,
    }


def to_json(report: Dict[str, Any]) -> str:
    """Stable JSON rendering (all sections, indent=2)."""
    import json

    return json.dumps(report, indent=2, default=str)


def _indent(text: str, prefix: str = "    ") -> str:
    return "\n".join(
        prefix + line if line else line for line in (text or "").splitlines()
    )


def render_human(report: Dict[str, Any], sections: Tuple[str, ...] = SECTIONS) -> str:
    """Sectioned human-readable rendering for terminals and review notes."""
    meta = report.get("meta", {})
    lines: List[str] = [
        "=" * 78,
        "TMBot turn debug",
        "=" * 78,
        f"question : {meta.get('question')}",
        f"user_id  : {meta.get('user_id')}   top_k={meta.get('top_k')}   history_turns={meta.get('history_turns')}",
        f"model    : {meta.get('model')}   temperature={meta.get('temperature')}   max_tokens={meta.get('max_tokens')}",
    ]

    if "decisions" in sections:
        decisions = report.get("decisions", {})
        guard = decisions.get("guardrail", {})
        lines += [
            "",
            "-- decisions " + "-" * 65,
            f"guardrail : {guard.get('verdict')} ({guard.get('gate')}) — {guard.get('reason')}",
            f"flags     : smalltalk={decisions.get('smalltalk')} third_party={decisions.get('third_party_user')} needs_project_id={decisions.get('needs_project_id')}",
            f"route     : {decisions.get('route')}   ops={decisions.get('ops')}   project_id={decisions.get('project_id')}   filters={decisions.get('filters')}",
        ]

    if "kb" in sections:
        kb = report.get("kb", {})
        lines += ["", "-- kb retrieval " + "-" * 62]
        if not kb.get("ran"):
            lines.append("skipped (no KB retrieval on this route)")
        else:
            lines.append(
                f"mode={kb.get('mode')} candidates={kb.get('candidate_count')} "
                f"denied={kb.get('denied_count')} degraded={kb.get('degraded')} "
                f"timing_ms={kb.get('timing_ms')}"
            )
            lines.append(
                f"top_score={kb.get('top_score')} threshold={kb.get('threshold')} "
                f"low_confidence={kb.get('low_confidence')}"
            )
            for idx, item in enumerate(kb.get("results", []), start=1):
                lines.append(
                    f"[{idx}] {item.get('node_id')}  fused={item.get('fused_score')} "
                    f"vector_rank={item.get('vector_rank')} bm25_rank={item.get('bm25_rank')}"
                )
                lines.append(
                    f"    title={item.get('title')!r}  doc={item.get('doc_id')!r}"
                )
                if item.get("source_refs"):
                    lines.append(f"    source={item.get('source_refs')}")
                lines.append(f"    {item.get('snippet')}")

    if "domain" in sections:
        domain = report.get("domain", {})
        lines += ["", "-- domain evidence " + "-" * 60]
        if not domain.get("ran"):
            lines.append(
                f"skipped: {domain.get('skipped') or 'no domain ops on this route'}"
            )
        else:
            lines.append(f"status={domain.get('status')} ops={domain.get('ops')}")
            lines.append(_indent(domain.get("block") or "(empty block)"))

    if "prompt" in sections:
        prompt = report.get("prompt", {})
        lines += ["", "-- exact LLM prompt " + "-" * 58]
        if not prompt.get("ran"):
            lines.append("no prompt built (no evidence)")
        else:
            lines.append(
                f"budget={prompt.get('budget')} tokens system={prompt.get('system_tokens')} "
                f"user={prompt.get('user_tokens')}"
            )
            lines.append("[system]")
            lines.append(_indent(prompt.get("system") or ""))
            lines.append("[user]")
            lines.append(_indent(prompt.get("user") or ""))

    if "answer" in sections:
        answer = report.get("answer", {})
        lines += ["", "-- answer " + "-" * 68]
        if answer.get("canned"):
            lines.append("deterministic (no LLM call):")
            lines.append(_indent(answer.get("canned") or ""))
        elif answer.get("ran"):
            lines.append(
                f"model={answer.get('model')} elapsed_ms={answer.get('elapsed_ms')}"
            )
            lines.append(_indent(answer.get("text") or ""))
        else:
            lines.append(f"not generated ({answer.get('reason')})")

    lines.append("")
    return "\n".join(lines)
