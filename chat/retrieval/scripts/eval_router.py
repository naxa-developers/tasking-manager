#!/usr/bin/env python3
"""Score the LLM router against the labeled routing corpus.

This is live evidence, not part of the offline test suite. It needs the routing
model configured (``RAG_ROUTER_MODEL`` or ``LITELLM_MODEL``) and a reachable
endpoint.

Usage::

    PYTHONPATH=. .venv/bin/python chat/retrieval/scripts/eval_router.py --dry-run
    PYTHONPATH=. .venv/bin/python chat/retrieval/scripts/eval_router.py --out /tmp/router.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from chat.retrieval.domain.llm_router import route_question
from chat.retrieval.domain.references import is_third_party_user_query
from chat.retrieval.guardrails import classify_query, is_smalltalk_query

CORPUS_PATH = Path(__file__).resolve().parents[2] / "eval" / "routing_corpus.jsonl"


def load_cases(path: Path) -> List[Dict[str, Any]]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            case = json.loads(line)
            if not isinstance(case, dict):
                raise ValueError("corpus rows must be JSON objects")
            cases.append(case)
    return cases


def validate_cases(cases: List[Dict[str, Any]]) -> None:
    """Fail fast on a malformed corpus before spending model calls."""
    ids = set()
    required = {
        "id",
        "family",
        "question",
        "expected_route",
        "expected_ops",
        "expected_filters",
        "expected_project_id",
        "expected_needs_project_id",
        "strict",
    }
    for case in cases:
        missing = required - set(case)
        if missing:
            raise ValueError(f"{case.get('id', '?')}: missing {sorted(missing)}")
        if case["id"] in ids:
            raise ValueError(f"duplicate case id: {case['id']}")
        ids.add(case["id"])
        if case["expected_route"] is not None and case["expected_route"] not in (
            "KB",
            "DOMAIN",
            "BOTH",
        ):
            raise ValueError(f"{case['id']}: bad expected_route")
        if not isinstance(case["expected_ops"], list):
            raise ValueError(f"{case['id']}: expected_ops must be a list")
        if not isinstance(case["expected_filters"], dict):
            raise ValueError(f"{case['id']}: expected_filters must be an object")


def history_for(case: Dict[str, Any]) -> List[Dict[str, str]]:
    prior = case.get("prior_question")
    return [{"role": "user", "content": str(prior)}] if prior else []


def guardrail_pass(case: Dict[str, Any]) -> bool:
    question = str(case["question"])
    expected = case.get("expected_guardrail")
    if expected == "smalltalk":
        return is_smalltalk_query(question)
    if expected:
        return classify_query(question).verdict == expected
    expected_third_party = case.get("expected_third_party")
    if expected_third_party is not None:
        return is_third_party_user_query(question) == bool(expected_third_party)
    return False


def route_pass(case: Dict[str, Any], route: Any) -> Dict[str, bool]:
    metrics = {
        "route": route.route == case["expected_route"],
        "ops": set(route.ops) == set(case["expected_ops"]),
        "filters": route.filters == case["expected_filters"],
        "project_id": route.project_id == case["expected_project_id"],
        "needs_project_id": route.needs_project_id
        == bool(case["expected_needs_project_id"]),
    }
    metrics["pass"] = all(metrics.values())
    return metrics


async def evaluate(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results = []
    for case in cases:
        if case.get("expected_route") is None:
            results.append(
                {
                    "id": case["id"],
                    "family": case["family"],
                    "strict": bool(case["strict"]),
                    "kind": "guardrail",
                    "pass": guardrail_pass(case),
                }
            )
            continue
        route = await route_question(str(case["question"]), history=history_for(case))
        metrics = route_pass(case, route)
        results.append(
            {
                "id": case["id"],
                "family": case["family"],
                "strict": bool(case["strict"]),
                "kind": "route",
                "question": case["question"],
                "expected": {
                    "route": case["expected_route"],
                    "ops": case["expected_ops"],
                    "filters": case["expected_filters"],
                    "project_id": case["expected_project_id"],
                    "needs_project_id": case["expected_needs_project_id"],
                },
                "actual": {
                    "route": route.route,
                    "ops": list(route.ops),
                    "filters": route.filters,
                    "project_id": route.project_id,
                    "needs_project_id": route.needs_project_id,
                },
                "metrics": metrics,
                "pass": metrics["pass"],
            }
        )
    return results


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    strict = [row for row in results if row["strict"]]
    route_rows = [row for row in results if row["kind"] == "route"]
    strict_route_rows = [row for row in route_rows if row["strict"]]

    def rate(rows: List[Dict[str, Any]], key: Optional[str] = None) -> float:
        if not rows:
            return 0.0
        if key is None:
            passed = sum(1 for row in rows if row["pass"])
        else:
            passed = sum(1 for row in rows if row["metrics"].get(key))
        return passed / len(rows)

    return {
        "cases": len(results),
        "strict": len(strict),
        "strict_pass": rate(strict),
        "all_pass": rate(results),
        "route_match": rate(route_rows, "route"),
        "ops_match": rate(route_rows, "ops"),
        "filters_match": rate(route_rows, "filters"),
        "project_id_match": rate(route_rows, "project_id"),
        "needs_project_id_match": rate(route_rows, "needs_project_id"),
        "strict_route_pass": rate(strict_route_rows),
    }


def print_summary(summary: Dict[str, Any]) -> None:
    print(
        f"strict pass : {summary['strict_pass']:.3f} ({summary['strict']} cases)\n"
        f"all pass    : {summary['all_pass']:.3f} ({summary['cases']} cases)\n"
        f"route       : {summary['route_match']:.3f}\n"
        f"ops         : {summary['ops_match']:.3f}\n"
        f"filters     : {summary['filters_match']:.3f}\n"
        f"project id  : {summary['project_id_match']:.3f}\n"
        f"needs id    : {summary['needs_project_id_match']:.3f}"
    )


def print_failures(results: List[Dict[str, Any]]) -> None:
    failures = [row for row in results if not row["pass"]]
    if not failures:
        return
    print("\nfailures:")
    for row in failures:
        if row["kind"] == "guardrail":
            print(f"  {row['id']}: guardrail boundary failed")
            continue
        print(f"  {row['id']}: {row['question']}")
        print(f"    expected {row['expected']}")
        print(f"    actual   {row['actual']}")


def dry_run(cases: List[Dict[str, Any]]) -> None:
    validate_cases(cases)
    families = Counter(case["family"] for case in cases)
    strict = sum(1 for case in cases if case["strict"])
    route_cases = sum(1 for case in cases if case["expected_route"] is not None)
    print(f"corpus      : {len(cases)} cases ({strict} strict)")
    print(f"route cases : {route_cases}; guardrail/other: {len(cases) - route_cases}")
    for family, count in sorted(families.items()):
        print(f"  {family}: {count}")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=CORPUS_PATH)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--fail-under",
        type=float,
        default=0.0,
        help="Exit 1 when the strict pass rate is below this value.",
    )
    args = parser.parse_args()

    cases = load_cases(args.corpus)
    validate_cases(cases)
    if args.limit > 0:
        cases = cases[: args.limit]
    if args.dry_run:
        dry_run(cases)
        return 0

    results = await evaluate(cases)
    summary = summarize(results)
    print_summary(summary)
    print_failures(results)

    if args.out is not None:
        args.out.write_text(
            json.dumps({"summary": summary, "results": results}, indent=2),
            encoding="utf-8",
        )
        print(f"\nwrote {args.out}")

    if args.fail_under > 0 and summary["strict_pass"] < args.fail_under:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
