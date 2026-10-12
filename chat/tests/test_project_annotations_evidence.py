"""Evidence invariants for the project-annotations op.

Mirrors ``TaskAnnotation.get_task_annotations_by_project_id``: per-type counts
plus a bounded list of annotations (task id, type, source, markdown excerpt).
"""

import asyncio
from dataclasses import dataclass
from typing import Any, List, Optional

import chat.retrieval.domain.project_annotations as annotations


@dataclass
class _AnnRow:
    task_id: Optional[int]
    annotation_type: Optional[str]
    annotation_source: Optional[str] = None
    annotation_markdown: Optional[str] = None
    properties: Optional[dict] = None


class _AnnDTO:
    def __init__(self, rows: List[_AnnRow]):
        self.tasks = rows


def _patch(monkeypatch, *, auth="OK", rows=None, fetch_raise=False):
    async def _authorize(user_id, project_id, db):
        return auth, (object() if auth == "OK" else None)

    monkeypatch.setattr(annotations, "authorize_project", _authorize)

    from backend.models.postgis.task_annotation import TaskAnnotation

    async def _get(project_id, db):
        if fetch_raise:
            raise RuntimeError("boom")
        return _AnnDTO(rows or [])

    monkeypatch.setattr(TaskAnnotation, "get_task_annotations_by_project_id", _get)


def test_annotations_counts_and_list(monkeypatch):
    _patch(
        monkeypatch,
        rows=[
            _AnnRow(12, "bad_imagery", "validator", "clouds cover the area"),
            _AnnRow(15, "bad_imagery", "mapper"),
            _AnnRow(20, "other", None, "see forum thread"),
        ],
    )
    evidence = asyncio.run(annotations.get_project_annotations_evidence(7, 5, db=None))

    assert evidence.status == "OK"
    block = evidence.to_prompt_block()
    assert "operation: get_project_annotations" in block
    assert "annotations_by_type: 2 bad_imagery, 1 other" in block
    assert "task_annotations (complete list, 3 items):" in block
    assert "1. task #12 | bad_imagery | by validator | clouds cover the area" in block
    assert "2. task #15 | bad_imagery | by mapper" in block
    assert "3. task #20 | other | see forum thread" in block


def test_annotations_cap_discloses_slice(monkeypatch):
    rows = [_AnnRow(i, "bad_imagery") for i in range(1, 26)]
    _patch(monkeypatch, rows=rows)
    evidence = asyncio.run(annotations.get_project_annotations_evidence(7, 5, db=None))

    block = evidence.to_prompt_block()
    assert "task_annotations (showing 20 of 25):" in block
    assert "1. task #1 | bad_imagery" in block
    assert "20. task #20 | bad_imagery" in block
    assert "task #21" not in block


def test_annotations_empty_project(monkeypatch):
    _patch(monkeypatch, rows=[])
    evidence = asyncio.run(annotations.get_project_annotations_evidence(7, 5, db=None))

    block = evidence.to_prompt_block()
    assert "task_annotations: none" in block


def test_annotations_unavailable_on_failure(monkeypatch):
    _patch(monkeypatch, fetch_raise=True)
    evidence = asyncio.run(annotations.get_project_annotations_evidence(7, 5, db=None))

    assert evidence.status == "UNAVAILABLE"
    assert evidence.to_prompt_block() == ""


def test_annotations_unauthorized_renders_nothing(monkeypatch):
    _patch(monkeypatch, auth="UNAUTHORIZED")
    evidence = asyncio.run(annotations.get_project_annotations_evidence(7, 5, db=None))

    assert evidence.status == "UNAUTHORIZED"
    assert evidence.to_prompt_block() == ""
