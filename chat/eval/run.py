"""Compare generation models across the three eval sets.

    python -m chat.eval.run kb     --model ollama/qwen3:4b --api-base http://localhost:11434
    python -m chat.eval.run router --model ollama/qwen3:4b --api-base http://localhost:11434
    python -m chat.eval.run domain --model ollama/qwen3:4b --api-base http://localhost:11434 --user-id 10250456
    python -m chat.eval.run compare --a kb-1.7b.json --b kb-4b.json

The model is passed by environment to the package (``LITELLM_MODEL`` /
``LLM_API_BASE``), so the code under test is exactly the production path.

Note on the KB set: its ``expected_docs`` were written against a knowledge-base
layout that no longer exists in the index, so this scores answer quality against
the reference answer, not retrieval recall.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

DATA = Path(__file__).resolve().parent / "data"

ABSTENTION_MARKERS = (
    "couldn't find relevant information",
    "could not find relevant information",
    "couldn't retrieve",
    "could not retrieve",
    "couldn't put an answer together",
    "i don't have that detail",
    "does not contain information",
    "no relevant information",
)


def load(name: str) -> List[Dict[str, Any]]:
    path = DATA / name
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def configure(model: str, api_base: Optional[str], router_model: Optional[str]) -> None:
    """Point the package at the model under test before anything imports config.

    ``GENERATION_API_BASE`` is set explicitly because it outranks ``LLM_API_BASE``
    in the config lookup, and the deployment env file already defines it.
    """
    os.environ["LITELLM_MODEL"] = model
    if api_base:
        os.environ["LLM_API_BASE"] = api_base
        os.environ["GENERATION_API_BASE"] = api_base
        os.environ["RAG_ROUTER_API_BASE"] = api_base
    if router_model:
        os.environ["RAG_ROUTER_MODEL"] = router_model
    else:
        os.environ.pop("RAG_ROUTER_MODEL", None)
    if model.startswith("ollama"):
        # Asymmetric on purpose.
        # Router: thinking off. Its budget is 512 tokens and a reasoning block
        # consumes all of it, leaving empty or truncated JSON.
        os.environ["RAG_ROUTER_EXTRA_BODY"] = '{"think": false}'
        # Generation: thinking ON. think=false removes the separate thinking
        # channel, so Qwen3 emits its reasoning as the answer itself. Left on,
        # Ollama reports thinking separately and `content` stays clean.
        os.environ.pop("RAG_GENERATION_EXTRA_BODY", None)


def is_abstention(text: str) -> bool:
    low = (text or "").lower()
    return any(marker in low for marker in ABSTENTION_MARKERS)


_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> List[str]:
    return [w for w in _WORD.findall((text or "").lower()) if len(w) > 1]


def answer_f1(prediction: str, reference: str) -> float:
    """Token overlap between the answer and the reference answer."""
    pred, ref = Counter(_tokens(prediction)), Counter(_tokens(reference))
    overlap = sum((pred & ref).values())
    if overlap == 0:
        return 0.0
    precision = overlap / max(1, sum(pred.values()))
    recall = overlap / max(1, sum(ref.values()))
    return round(2 * precision * recall / (precision + recall), 4)


def pct(values: Sequence[float], point: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(point * (len(ordered) - 1))))
    return round(ordered[index], 1)


# --- modes -------------------------------------------------------------------


async def run_kb(args) -> Dict[str, Any]:
    from chat.generate import Generator
    from chat.retrieval import retrieve

    questions = load("kb.jsonl")[: args.limit or None]
    generator = Generator()
    rows: List[Dict[str, Any]] = []
    for index, case in enumerate(questions, start=1):
        started = time.monotonic()
        try:
            response = retrieve(case["question"], args.top_k)
            result = generator.answer(case["question"], response.results)
            answer, reason = result.text, result.reason
        except Exception as error:  # noqa: BLE001 - eval: record, never crash
            answer, reason = "", f"exception:{type(error).__name__}"
        elapsed = time.monotonic() - started
        rows.append(
            {
                "id": case["id"],
                "question": case["question"],
                "answer": answer,
                "reason": reason,
                "f1": answer_f1(answer, case.get("reference") or ""),
                "abstained": is_abstention(answer),
                "passages": len(response.results) if "response" in dir() else 0,
                "seconds": round(elapsed, 2),
            }
        )
        if index % 20 == 0:
            print(f"  kb {index}/{len(questions)}", flush=True)
    return {"mode": "kb", "rows": rows, "summary": _summarise_kb(rows)}


def _summarise_kb(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    ok = [r for r in rows if r["answer"]]
    return {
        "cases": len(rows),
        "answered": len(ok),
        "answered_pct": round(100 * len(ok) / max(1, len(rows)), 1),
        "abstentions": sum(1 for r in rows if r["abstained"]),
        "abstention_pct": round(
            100 * sum(1 for r in rows if r["abstained"]) / max(1, len(rows)), 1
        ),
        "f1_mean": round(statistics.mean([r["f1"] for r in ok]) if ok else 0.0, 4),
        "f1_median": round(statistics.median([r["f1"] for r in ok]) if ok else 0.0, 4),
        "latency_mean_s": round(
            statistics.mean([r["seconds"] for r in rows]) if rows else 0.0, 2
        ),
        "latency_p50_s": pct([r["seconds"] for r in rows], 0.5),
        "latency_p95_s": pct([r["seconds"] for r in rows], 0.95),
        "errors": sum(1 for r in rows if r["reason"] != "ok"),
    }


async def run_router(args) -> Dict[str, Any]:
    from chat.router import route_question

    cases = [c for c in load("router.jsonl") if c.get("expected_route")][
        : args.limit or None
    ]
    rows: List[Dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        history = (
            [{"role": "user", "content": case["prior_question"]}]
            if case.get("prior_question")
            else []
        )
        started = time.monotonic()
        decision = await route_question(case["question"], history=history)
        elapsed = time.monotonic() - started
        metrics = {
            "route": decision.route == case["expected_route"],
            "ops": set(decision.ops) == set(case["expected_ops"]),
            "filters": decision.filters == case["expected_filters"],
            "project_id": decision.project_id == case["expected_project_id"],
            "needs_project_id": decision.degraded
            == bool(case["expected_needs_project_id"]),
        }
        metrics["pass"] = all(metrics.values())
        rows.append(
            {
                "id": case["id"],
                "family": case["family"],
                "question": case["question"],
                "expected": {
                    "route": case["expected_route"],
                    "ops": case["expected_ops"],
                    "project_id": case["expected_project_id"],
                },
                "actual": {
                    "route": decision.route,
                    "ops": list(decision.ops),
                    "project_id": decision.project_id,
                    "degraded": decision.degraded,
                },
                "metrics": metrics,
                "pass": metrics["pass"],
                "seconds": round(elapsed, 2),
            }
        )
        if index % 20 == 0:
            print(f"  router {index}/{len(cases)}", flush=True)
    return {"mode": "router", "rows": rows, "summary": _summarise_router(rows)}


def _summarise_router(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    def rate(key: Optional[str] = None) -> float:
        if not rows:
            return 0.0
        passed = (
            sum(1 for r in rows if r["pass"])
            if key is None
            else sum(1 for r in rows if r["metrics"].get(key))
        )
        return round(passed / len(rows), 3)

    return {
        "cases": len(rows),
        "pass_all": rate(),
        "route": rate("route"),
        "ops": rate("ops"),
        "filters": rate("filters"),
        "project_id": rate("project_id"),
        "needs_project_id": rate("needs_project_id"),
        "latency_p50_s": pct([r["seconds"] for r in rows], 0.5),
        "latency_p95_s": pct([r["seconds"] for r in rows], 0.95),
        "errors": sum(1 for r in rows if r["actual"]["route"] is None),
    }


async def run_domain(args) -> Dict[str, Any]:
    from databases import Database

    from backend.config import settings
    from chat.pipeline import run_turn

    cases = load("domain.jsonl")[: args.limit or None]
    db = Database(settings.SQLALCHEMY_DATABASE_URI.unicode_string())
    await db.connect()
    rows: List[Dict[str, Any]] = []
    try:
        for index, case in enumerate(cases, start=1):
            started = time.monotonic()
            try:
                turn = await run_turn(case["question"], user_id=args.user_id, db=db)
                answer, route, ops = turn.answer, turn.route, list(turn.ops)
                reason, project_id = turn.reason, turn.project_id
            except Exception as error:  # noqa: BLE001
                answer, route, ops = "", "ERROR", []
                reason, project_id = f"exception:{type(error).__name__}", None
            elapsed = time.monotonic() - started
            rows.append(
                {
                    "id": case["id"],
                    "question": case["question"],
                    "answer": answer,
                    "route": route,
                    "ops": ops,
                    "project_id": project_id,
                    "reason": reason,
                    "abstained": is_abstention(answer),
                    "seconds": round(elapsed, 2),
                }
            )
            if index % 8 == 0:
                print(f"  domain {index}/{len(cases)}", flush=True)
    finally:
        await db.disconnect()
    return {"mode": "domain", "rows": rows, "summary": _summarise_domain(rows)}


def _summarise_domain(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "cases": len(rows),
        "answered": sum(1 for r in rows if r["answer"]),
        "abstentions": sum(1 for r in rows if r["abstained"]),
        "errors": sum(
            1
            for r in rows
            if r["reason"] == "error" or str(r["reason"]).startswith("exception")
        ),
        "empty_answers": sum(1 for r in rows if not r["answer"].strip()),
        "route_counts": dict(Counter(r["route"] for r in rows)),
        "latency_mean_s": round(
            statistics.mean([r["seconds"] for r in rows]) if rows else 0.0, 2
        ),
        "latency_p50_s": pct([r["seconds"] for r in rows], 0.5),
        "latency_p95_s": pct([r["seconds"] for r in rows], 0.95),
    }


# --- compare ------------------------------------------------------------------


def compare(a_path: str, b_path: str) -> None:
    a = json.loads(Path(a_path).read_text())
    b = json.loads(Path(b_path).read_text())
    print(f"{'metric':<24}{a.get('model','A'):>18}{b.get('model','B'):>18}")
    for key in sorted(set(a["summary"]) | set(b["summary"])):
        left, right = a["summary"].get(key), b["summary"].get(key)
        if isinstance(left, dict) or isinstance(right, dict):
            continue
        print(f"{key:<24}{str(left):>18}{str(right):>18}")


# --- entry point --------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("kb", "router", "domain", "compare"))
    parser.add_argument("--model", default="ollama/qwen3:4b")
    parser.add_argument("--router-model", default=None)
    parser.add_argument("--api-base", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--user-id", type=int, default=None)
    parser.add_argument("--a", default=None)
    parser.add_argument("--b", default=None)
    args = parser.parse_args(argv)

    if args.mode == "compare":
        compare(args.a, args.b)
        return 0

    configure(args.model, args.api_base, args.router_model)
    started = time.monotonic()
    result = asyncio.run(
        {"kb": run_kb, "router": run_router, "domain": run_domain}[args.mode](args)
    )
    result["model"] = args.model
    result["api_base"] = args.api_base
    result["wall_seconds"] = round(time.monotonic() - started, 1)

    print(json.dumps(result["summary"], indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2))
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
