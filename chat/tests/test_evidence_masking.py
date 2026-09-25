"""Prompt-block privacy invariants (P3).

A ``user_id`` subject is audit metadata, never prompt content: no rendered
block may contain a ``user_id: <digits>`` line. The id stays available in
citations. Project context (``project_id``) is still rendered, since the
LLM needs it to attribute the numbers.
"""

import re

from chat.retrieval.domain.evidence import EvidenceBase
from chat.retrieval.domain.stats import DomainEvidence
from chat.retrieval.domain.user_contributions import UserContributionEvidence

_USER_ID_LINE_RE = re.compile(r"user_id:\s*\d+")


def _all_evidence_subclasses():
    return EvidenceBase.__subclasses__()


def test_no_prompt_block_leaks_user_id():
    assert _all_evidence_subclasses(), "expected EvidenceBase subclasses"
    for cls in _all_evidence_subclasses():
        fields = getattr(cls, "__dataclass_fields__", {})
        if "user_id" not in fields:
            continue
        kwargs = {"status": "OK", "user_id": 10022716}
        if "project_id" in fields:
            kwargs["project_id"] = 19
        evidence = cls(**kwargs)
        block = evidence.to_prompt_block()
        assert block, f"{cls.__name__} rendered empty for status=OK"
        assert not _USER_ID_LINE_RE.search(
            block
        ), f"{cls.__name__} leaks user_id into the prompt block: {block!r}"


def test_contributions_block_keeps_totals_without_id():
    evidence = UserContributionEvidence(
        status="OK", user_id=10022716, total_hours=93.6, tasks_mapped=10
    )
    block = evidence.to_prompt_block()
    assert "total_contribution_hours_all_time: 93.6" in block
    assert not _USER_ID_LINE_RE.search(block)


def test_citation_still_carries_subject_id():
    evidence = UserContributionEvidence(status="OK", user_id=10022716)
    citation = evidence.to_citation()
    assert "10022716" in citation["id"]


def test_project_context_still_rendered():
    evidence = DomainEvidence(status="OK", project_id=19, total_tasks=100)
    block = evidence.to_prompt_block()
    assert "project_id: 19" in block
