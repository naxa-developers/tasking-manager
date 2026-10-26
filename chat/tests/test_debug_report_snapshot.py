"""Snapshot tests for render_human: byte-identical sectioned output.


Recorded from the pre-refactor renderer; the per-section split must not
change a single byte, and the ``sections`` filter keeps its order.
"""

from chat.retrieval.debug_report import render_human

RICH_REPORT = {
    "meta": {
        "question": "how do I lock a task?",
        "user_id": 7,
        "top_k": 5,
        "history_messages": 4,
        "history_turns": 2,
        "model": "qwen-test",
        "temperature": 0.2,
        "max_tokens": 512,
        "finish_reason": "stop",
    },
    "decisions": {
        "guardrail": {
            "verdict": "ok",
            "gate": "scope",
            "reason": "Matched strong scope keyword 'mapping'.",
        },
        "smalltalk": False,
        "third_party_user": False,
        "needs_project_id": False,
        "route": "BOTH",
        "ops": ["stats"],
        "project_id": 5,
        "filters": {"status": "published"},
    },
    "kb": {
        "ran": True,
        "mode": "hybrid",
        "candidate_count": 2,
        "timing_ms": {"vector": 12.5, "bm25": 3.25},
        "top_score": 0.032,
        "threshold": 0.0161,
        "low_confidence": False,
        "results": [
            {
                "node_id": "kb-1",
                "title": "Locking",
                "doc_id": "mapper/lock",
                "fused_score": 0.032,
                "vector_rank": 1,
                "bm25_rank": None,
                "source_refs": [{"path": "docs/lock.md"}],
                "snippet": "Lock the task before mapping.",
            },
            {
                "node_id": "kb-2",
                "title": "Unlocking",
                "doc_id": "mapper/unlock",
                "fused_score": 0.02,
                "vector_rank": None,
                "bm25_rank": 2,
                "snippet": "Unlock only when done.",
            },
        ],
    },
    "domain": {
        "ran": True,
        "status": "OK",
        "ops": ["stats"],
        "block": "Project 5: 10 tasks",
    },
    "prompt": {
        "ran": True,
        "budget": 3200,
        "system_tokens": 518,
        "user_tokens": 200,
        "system": "sys line 1\nsys line 2",
        "user": "user line 1\nuser line 2",
    },
    "answer": {
        "canned": "Canned answer text",
        "ran": False,
        "reason": "deterministic branch",
    },
}

MINIMAL_REPORT = {
    "meta": {
        "question": "q",
        "user_id": 1,
        "top_k": 5,
        "history_messages": 0,
        "history_turns": 0,
        "model": "m",
        "temperature": 0.0,
        "max_tokens": 512,
        "finish_reason": None,
    },
    "decisions": {
        "guardrail": {"verdict": "ok", "gate": "scope", "reason": "r"},
        "smalltalk": False,
        "third_party_user": False,
        "needs_project_id": False,
        "route": "KB",
        "ops": [],
        "project_id": None,
        "filters": {},
    },
    "kb": {"ran": False},
    "domain": {"ran": False, "skipped": None},
    "prompt": {"ran": False},
    "answer": {"ran": False, "reason": "generation not requested"},
}

EXPECTED_RICH = """==============================================================================
TMBot turn debug
==============================================================================
question : how do I lock a task?
user_id  : 7   top_k=5   history_turns=2   history_messages=4
model    : qwen-test   temperature=0.2   max_tokens=512   finish_reason=stop

-- decisions -----------------------------------------------------------------
guardrail : ok (scope) — Matched strong scope keyword 'mapping'.
flags     : smalltalk=False third_party=False needs_project_id=False
route     : BOTH   ops=['stats']   project_id=5   filters={'status': 'published'}

-- kb retrieval --------------------------------------------------------------
mode=hybrid candidates=2 timing_ms={'vector': 12.5, 'bm25': 3.25}
top_score=0.032 threshold=0.0161 low_confidence=False
[1] kb-1  fused=0.032 vector_rank=1 bm25_rank=None
    title='Locking'  doc='mapper/lock'
    source=[{'path': 'docs/lock.md'}]
    Lock the task before mapping.
[2] kb-2  fused=0.02 vector_rank=None bm25_rank=2
    title='Unlocking'  doc='mapper/unlock'
    Unlock only when done.

-- domain evidence ------------------------------------------------------------
status=OK ops=['stats']
    Project 5: 10 tasks

-- exact LLM prompt ----------------------------------------------------------
budget=3200 tokens system=518 user=200
[system]
    sys line 1
    sys line 2
[user]
    user line 1
    user line 2

-- answer --------------------------------------------------------------------
deterministic (no LLM call):
    Canned answer text
"""

EXPECTED_SUBSET = """==============================================================================
TMBot turn debug
==============================================================================
question : how do I lock a task?
user_id  : 7   top_k=5   history_turns=2   history_messages=4
model    : qwen-test   temperature=0.2   max_tokens=512   finish_reason=stop

-- kb retrieval --------------------------------------------------------------
mode=hybrid candidates=2 timing_ms={'vector': 12.5, 'bm25': 3.25}
top_score=0.032 threshold=0.0161 low_confidence=False
[1] kb-1  fused=0.032 vector_rank=1 bm25_rank=None
    title='Locking'  doc='mapper/lock'
    source=[{'path': 'docs/lock.md'}]
    Lock the task before mapping.
[2] kb-2  fused=0.02 vector_rank=None bm25_rank=2
    title='Unlocking'  doc='mapper/unlock'
    Unlock only when done.

-- answer --------------------------------------------------------------------
deterministic (no LLM call):
    Canned answer text
"""

EXPECTED_MINIMAL = """==============================================================================
TMBot turn debug
==============================================================================
question : q
user_id  : 1   top_k=5   history_turns=0   history_messages=0
model    : m   temperature=0.0   max_tokens=512   finish_reason=None

-- decisions -----------------------------------------------------------------
guardrail : ok (scope) — r
flags     : smalltalk=False third_party=False needs_project_id=False
route     : KB   ops=[]   project_id=None   filters={}

-- kb retrieval --------------------------------------------------------------
skipped (no KB retrieval on this route)

-- domain evidence ------------------------------------------------------------
skipped: no domain ops on this route

-- exact LLM prompt ----------------------------------------------------------
no prompt built (no evidence)

-- answer --------------------------------------------------------------------
not generated (generation not requested)
"""


def test_render_human_rich_snapshot():
    assert render_human(RICH_REPORT) == EXPECTED_RICH


def test_render_human_section_filter_snapshot():
    text = render_human(RICH_REPORT, sections=("kb", "answer"))
    assert text == EXPECTED_SUBSET
    assert text.count("-- ") == 2  # only the selected sections render


def test_render_human_not_ran_snapshot():
    assert render_human(MINIMAL_REPORT) == EXPECTED_MINIMAL


def test_default_sections_cover_all_section_headers():
    text = render_human(RICH_REPORT)
    for marker in (
        "-- decisions",
        "-- kb retrieval",
        "-- domain evidence",
        "-- exact LLM prompt",
        "-- answer",
    ):
        assert marker in text
