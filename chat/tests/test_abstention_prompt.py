"""Prompt-contract tests for abstention calibration and totals (P2).

These pin the _SYSTEM_PROMPT rules that keep the small model grounded:
totals stated before examples, every evidence value covered, no refusal
when evidence is present. If the prompt is ever trimmed, these fail loudly.
"""

from chat.retrieval.domain.mywork import LockedTaskGroup, MyWorkEvidence
from chat.retrieval.llm_answer import _SYSTEM_PROMPT


def test_totals_rule_present():
    assert "matching_projects_total" in _SYSTEM_PROMPT
    assert "before listing any examples" in _SYSTEM_PROMPT


def test_cover_every_value_rule_present():
    assert "Cover every value the evidence provides" in _SYSTEM_PROMPT


def test_no_refusal_copy_in_system_prompt():
    """Regression: the 1.7B model echoed refusal copy verbatim (113/219 in-scope
    questions in the audit); the prompt must not quote user-visible refusals."""
    assert "Could you be more precise" not in _SYSTEM_PROMPT
    assert "I can't help with that" not in _SYSTEM_PROMPT
    assert "UNSAFE_REQUEST" in _SYSTEM_PROMPT


def test_mywork_block_leads_with_direct_answer():
    evidence = MyWorkEvidence(
        status="OK",
        user_id=10022716,
        groups=(
            LockedTaskGroup(
                project_id=19, task_status="LOCKED_FOR_MAPPING", task_ids=(11,)
            ),
        ),
    )
    block = evidence.to_prompt_block()
    assert "you currently have 1 task locked: task #11 in project 19" in block


def test_mywork_empty_block_states_no_locked_task():
    evidence = MyWorkEvidence(status="OK", user_id=10022716, groups=())
    assert "you currently have no task locked" in evidence.to_prompt_block()
