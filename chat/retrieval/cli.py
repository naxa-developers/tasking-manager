#!/usr/bin/env python3
from __future__ import annotations

import argparse
import textwrap
from typing import List, Optional

from chat.retrieval.config import get_embedding_config
from chat.retrieval.domain.routing import route_query
from chat.retrieval.guardrails import classify_query, refusal_for
from chat.retrieval.llm_answer import LLMService
from chat.retrieval.policy import conf_threshold, is_low_confidence
from chat.retrieval.query_kb import retrieve


def _provider_label() -> str:
    cfg = get_embedding_config()
    if not cfg.api_key:
        return "no-key (fallback extractive)"
    return f"llm/{cfg.model}"


def _print_answer(answer: str, width: int = 88) -> None:
    print("\n--- Answer ---")
    for line in answer.splitlines():
        if not line.strip():
            print()
            continue
        bullet = line.startswith("- ")
        print(textwrap.fill(line, width=width, subsequent_indent="  " if bullet else ""))
    print()


def _print_evidence(resp, show_scores: bool = True) -> None:
    if not resp.results:
        print("(No evidence matched — try rephrasing.)")
        return
    print("--- Retrieved evidence (developer citations) ---")
    for idx, scored in enumerate(resp.results, start=1):
        meta = scored.node.metadata or {}
        title = meta.get("title", meta.get("doc_id", ""))
        nv = ""
        if meta.get("needs_verification"):
            nv = f"  [needs_verification: {', '.join(meta.get('needs_verification_ids') or [])}]"
        score_part = f"  fused={scored.fused_score:.4f}" if show_scores else ""
        source_refs = meta.get("source_refs") or meta.get("sources") or []
        src_line = ""
        if source_refs:
            refs = []
            for s in source_refs[:2]:
                if isinstance(s, dict):
                    # Normalized shape is [{type, path}]; legacy shapes tolerated.
                    refs.append(
                        s.get("path")
                        or s.get("symbol")
                        or next(
                            (
                                str(v)
                                for k, v in s.items()
                                if k not in {"path", "symbol"}
                            ),
                            "",
                        )
                    )
                else:
                    refs.append(str(s)[:60])
            src_line = f"  source: {' | '.join(r for r in refs if r)}"
        commit = (meta.get("provenance") or {}).get("commit") or meta.get("frozen_commit") or ""
        commit_line = f"  commit:{str(commit)[:12]}" if commit else ""
        print(f"[{idx}] {scored.node.id_}{score_part}")
        print(f"    title={title!r}{nv}")
        if src_line:
            print(f"   {src_line}{commit_line}")
        snippet = scored.node.text.strip().replace("\n", " ")
        if len(snippet) > 360:
            snippet = snippet[:360].rsplit(" ", 1)[0] + "…"
        print(f"    {snippet}")
    print()


def run_single_question(
    question: str,
    top_k: int,
    show_evidence: bool,
    history: Optional[List[dict]] = None,
) -> int:
    # Guardrails — before retrieval (safety/scope only)
    decision = classify_query(question)
    if decision.verdict != "ok":
        refusal = refusal_for(decision.verdict)
        print(f"TMBot  TopK: {top_k}  Provider: {_provider_label()}")
        print(f"Guardrail: {decision.verdict} ({decision.gate}) — {decision.reason}")
        _print_answer(refusal)
        return 0

    route = route_query(question)
    if route.route in ("DOMAIN", "BOTH"):
        # Offline CLI has no authenticated DB; live domain ops need /api/v2/rag chat.
        print("(Live project stats unavailable in offline CLI — use authenticated /api/v2/rag chat.)")

    resp = retrieve(question, top_k=top_k)

    if is_low_confidence(resp):
        top_score = f"{resp.results[0].fused_score:.4f}" if resp.results else "n/a"
        low_msg = (
            "I don't have that in my knowledge base. No passage was retrieved with "
            f"high confidence (top fused score {top_score} < {conf_threshold():.3f}). "
            "Try rephrasing with Tasking Manager–specific terms."
        )
        if not resp.results:
            low_msg = (
                "I couldn't find relevant evidence for that question. It may be out of scope "
                "for the Tasking Manager knowledge base."
            )
        print(f"TMBot  TopK: {top_k}  Provider: {_provider_label()}")
        if resp.degraded:
            print(f"Degraded: {resp.degraded_reason}")
        _print_answer(low_msg)
        print(f"(candidates={resp.candidate_count}  returned={len(resp.results)}  low_confidence top={top_score} thr={conf_threshold():.3f}  {resp.timing_ms})")
        return 0

    llm = LLMService()
    # History passes through untouched; the CLI renders it locally, one LLM call.
    # Generation errors propagate from LLMService — surface them as a clean exit.
    try:
        answer = llm.answer(question, resp.results, history=history)
    except Exception as e:
        print(f"TMBot  TopK: {top_k}  Provider: {_provider_label()}")
        print(f"Generation failed: {type(e).__name__}: {e}")
        return 1

    print(f"TMBot  TopK: {top_k}  Provider: {_provider_label()}")
    if resp.degraded:
        print(f"Degraded: {resp.degraded_reason}")
    _print_answer(answer)
    if show_evidence:
        _print_evidence(resp)
    print(f"(candidates={resp.candidate_count}  returned={len(resp.results)}  {resp.timing_ms})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Tasking Manager Knowledge Assistant — single-voice TMBot CLI (one-shot + conversation, no REPL)")
    parser.add_argument("--question", required=True, help="Question to ask (one-shot)")
    parser.add_argument("--top-k", type=int, default=5, help="Evidence passages to retrieve")
    parser.add_argument(
        "--history",
        default=None,
        help="Optional JSON array of prior {role,content} turns for conversational context (no extra embedding/LLM call — just context for the single answer).",
    )
    parser.add_argument("--no-evidence", action="store_true", help="Hide evidence citations")
    args = parser.parse_args()

    history = None
    if args.history:
        import json

        try:
            history = json.loads(args.history)
            if not isinstance(history, list):
                raise ValueError("history must be a JSON array")
        except Exception as e:
            parser.error(f"Invalid --history JSON: {e}")

    return run_single_question(args.question, args.top_k, show_evidence=not args.no_evidence, history=history)


if __name__ == "__main__":
    raise SystemExit(main())
