from __future__ import annotations

from chat.eval.run import _summarise_kb, _summarise_refusal, _summarise_router


def test_kb_summary_reports_retrieval_recall_and_mrr() -> None:
    summary = _summarise_kb(
        [
            {
                "answer": "a",
                "f1": 0.5,
                "abstained": False,
                "seconds": 1.0,
                "retrieval_hit": True,
                "retrieval_rr": 1.0,
                "has_expected_docs": True,
                "reason": "ok",
            },
            {
                "answer": "b",
                "f1": 0.1,
                "abstained": False,
                "seconds": 2.0,
                "retrieval_hit": False,
                "retrieval_rr": 0.0,
                "has_expected_docs": True,
                "reason": "ok",
            },
        ]
    )
    assert summary["retrieval_cases"] == 2
    assert summary["retrieval_recall_at_k"] == 0.5
    assert summary["retrieval_mrr"] == 0.5


def test_router_summary_reports_out_of_scope_rate() -> None:
    summary = _summarise_router(
        [
            {
                "expected": {"route": "OUT_OF_SCOPE"},
                "metrics": {"route": True},
                "pass": True,
                "seconds": 1.0,
                "actual": {"route": "OUT_OF_SCOPE"},
            }
        ]
    )
    assert summary["out_of_scope_cases"] == 1
    assert summary["out_of_scope_route"] == 1.0


def test_refusal_summary_reports_canned_rate() -> None:
    summary = _summarise_refusal(
        [
            {
                "metrics": {
                    "pass": True,
                    "route": True,
                    "reason": True,
                    "canned": True,
                },
                "canned": True,
                "seconds": 1.0,
            }
        ]
    )
    assert summary["pass_all"] == 1.0
    assert summary["canned"] == 1.0
    assert summary["generated"] == 0
