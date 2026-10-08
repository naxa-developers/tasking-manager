from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple, Union

from chat.dtos import RagCitationDTO
from chat.retrieval.guardrails import (
    GuardrailDecision,
    is_smalltalk_query,
    refusal_for,
    smalltalk_kind,
)
from chat.retrieval.policy import (
    DOMAIN_TEMPORARY_ANSWER,
    DOMAIN_UNAVAILABLE_ANSWER,
    GREETING_ANSWER,
    LOW_CONFIDENCE_ANSWER,
    NEEDS_PROJECT_ANSWER,
    SMALLTALK_ANSWERS,
    conf_threshold,
    is_low_confidence,
    third_party_user_answer,
)
from chat.retrieval.project_context import clarification_citation
from chat.turn.plan import PreparedTurn


@dataclass(frozen=True)
class CannedTurn:
    """A deterministic answer: everything the emitter needs, no generation."""

    answer: str
    guardrail: str
    citations: Tuple[RagCitationDTO, ...] = ()
    candidate_count: int = 0
    log_guardrail: Optional[str] = None
    degraded: bool = False
    domain_status: Optional[str] = None
    domain_project_id: Optional[int] = None
    persist_log: str = "assistant message"
    # None for deterministic (canned) answers — no generation ran.
    model: Optional[str] = None


@dataclass(frozen=True)
class GenerateTurn:
    """The turn proceeds to LLM generation with the resolved guardrail hint."""

    guardrail_hint: Optional[str] = None


def decide_early_turn(guard: GuardrailDecision, q: str) -> Optional[CannedTurn]:
    """Static gate decisions taken before history/retrieval: unsafe and small-talk."""
    if guard.verdict == "unsafe":
        return CannedTurn(
            answer=refusal_for("unsafe"),
            guardrail=f"{guard.gate}:{guard.verdict}",
            log_guardrail=f"{guard.gate}:{guard.verdict} {guard.reason}",
            persist_log="refusal",
        )
    if is_smalltalk_query(q):
        try:
            kind = smalltalk_kind(q)
        except Exception:
            kind = "greeting"
        return CannedTurn(
            answer=SMALLTALK_ANSWERS.get(kind, GREETING_ANSWER),
            guardrail=kind if kind in SMALLTALK_ANSWERS else "greeting",
            persist_log="small-talk",
        )
    return None


def decide_turn(prepared: PreparedTurn) -> Union[CannedTurn, GenerateTurn]:
    """Pick the answer for a prepared turn: canned copy or LLM generation.

    Mirrors the historic branch order: inherited unsafe, third-party privacy,
    project-id clarification, DOMAIN deny, scope gate, low confidence.
    """
    resp = prepared.resp
    candidate_count = int(resp.candidate_count)
    guardrail_hint = prepared.guardrail_hint

    # Inherited-unsafe: never fall through to the LLM on an unsafe verdict.
    if prepared.scope_verdict == "unsafe":
        return CannedTurn(
            answer=refusal_for("unsafe"),
            guardrail="safety:unsafe",
            log_guardrail=prepared.guardrail_hint or "safety:unsafe",
            candidate_count=candidate_count,
            persist_log="refusal",
        )

    # Third-party profile asks: canned web redirect, no evidence, no LLM.
    if prepared.third_party_user:
        return CannedTurn(
            answer=third_party_user_answer(prepared.third_party_username),
            guardrail="privacy:third-party-user",
            persist_log="third-party user redirect",
        )

    # Missing project id: deterministic clarification, no retrieval/LLM call.
    if prepared.needs_project_id:
        clarify = clarification_citation()
        return CannedTurn(
            answer=NEEDS_PROJECT_ANSWER,
            citations=(
                RagCitationDTO(
                    id=clarify["id"],
                    title=clarify["title"],
                    doc_id=clarify["doc_id"],
                    heading=clarify["heading"],
                    source_refs=clarify["source_refs"],
                    commit=clarify["commit"],
                ),
            ),
            guardrail="domain:needs-project-id",
            persist_log="project clarification",
        )

    domain_ok = prepared.domain_status == "OK" and bool(prepared.domain_block.strip())

    # DOMAIN deny/failure: LLM never called; BOTH routes still answer the KB part.
    if prepared.domain_route_str == "DOMAIN" and prepared.domain_status in (
        "UNAUTHORIZED",
        "NOT_FOUND",
        "TIMEOUT",
        "UNAVAILABLE",
    ):
        temporary = prepared.domain_status in ("TIMEOUT", "UNAVAILABLE")
        return CannedTurn(
            answer=DOMAIN_TEMPORARY_ANSWER if temporary else DOMAIN_UNAVAILABLE_ANSWER,
            guardrail="domain:temporary" if temporary else "domain:no-evidence",
            candidate_count=candidate_count,
            domain_status=prepared.domain_status,
            domain_project_id=prepared.domain_project_id,
            persist_log=(
                "temporary domain message" if temporary else "denied assistant message"
            ),
        )

    # Retrieval-gated scope: strong evidence answers, weak evidence gets the precision prompt.
    if prepared.scope_verdict == "out_of_scope" and not domain_ok:
        if is_low_confidence(resp):
            return CannedTurn(
                answer=refusal_for("out_of_scope"),
                guardrail="scope:precision-prompt",
                log_guardrail=guardrail_hint or "scope:out_of_scope",
                candidate_count=candidate_count,
                persist_log="precision prompt",
            )
        guardrail_hint = "scope:answered-from-evidence"

    # Low-confidence guard: fall back without the LLM unless domain evidence is OK.
    if guardrail_hint is None and not domain_ok and is_low_confidence(resp):
        low_log = (
            f"low_confidence top={resp.results[0].fused_score:.4f} thr={conf_threshold():.3f}"
            if resp.results
            else "low_confidence no_candidates"
        )
        return CannedTurn(
            answer=LOW_CONFIDENCE_ANSWER,
            guardrail="retrieval:low-confidence",
            log_guardrail=low_log,
            candidate_count=candidate_count,
            persist_log="low-confidence assistant message",
        )

    return GenerateTurn(guardrail_hint=guardrail_hint)
