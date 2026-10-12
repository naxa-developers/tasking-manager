"""Evidence invariants for the similar-projects op.

Mirrors ``ProjectRecommendationService.get_similar_projects``: ranked
search-shaped results; the endpoint's published-project gate surfaces as
NOT_FOUND.
"""

import asyncio
from dataclasses import dataclass
from typing import Any, List, Optional

import chat.retrieval.domain.similar_projects as similar


@dataclass
class _Result:
    project_id: Optional[int]
    name: Optional[str] = None
    status: Optional[str] = None
    difficulty: Optional[str] = None
    country: Optional[str] = None


class _ResultsDTO:
    def __init__(self, rows: List[_Result]):
        self.results = rows


def _patch(
    monkeypatch,
    *,
    auth="OK",
    rows=None,
    raise_not_found=False,
    fetch_raise=False,
):
    async def _authorize(user_id, project_id, db):
        return auth, (object() if auth == "OK" else None)

    monkeypatch.setattr(similar, "authorize_project", _authorize)

    from backend.exceptions import NotFound
    from backend.services.recommendation_service import (
        ProjectRecommendationService,
    )

    async def _get(db, project_id, user_id=None, preferred_locale="en", limit=4):
        if raise_not_found:
            raise NotFound(sub_code="PROJECT_NOT_FOUND", project_id=project_id)
        if fetch_raise:
            raise RuntimeError("boom")
        return _ResultsDTO(rows or [])

    monkeypatch.setattr(ProjectRecommendationService, "get_similar_projects", _get)


def test_similar_lists_ranked_projects(monkeypatch):
    _patch(
        monkeypatch,
        rows=[
            _Result(
                9, "Roads A", status="PUBLISHED", difficulty="EASY", country="Nepal"
            ),
            _Result(10, "Roads B"),
        ],
    )
    evidence = asyncio.run(similar.get_similar_projects_evidence(7, 5, db=None))

    assert evidence.status == "OK"
    block = evidence.to_prompt_block()
    assert "operation: get_similar_projects" in block
    assert "project_id: 5" in block
    assert "similar_projects (2):" in block
    assert "#9 Roads A | status: PUBLISHED | difficulty: EASY | country: Nepal" in block
    assert "#10 Roads B" in block


def test_similar_empty(monkeypatch):
    _patch(monkeypatch, rows=[])
    evidence = asyncio.run(similar.get_similar_projects_evidence(7, 5, db=None))

    block = evidence.to_prompt_block()
    assert "similar_projects: none found" in block


def test_similar_unpublished_is_not_found(monkeypatch):
    _patch(monkeypatch, raise_not_found=True)
    evidence = asyncio.run(similar.get_similar_projects_evidence(7, 5, db=None))

    assert evidence.status == "NOT_FOUND"
    assert evidence.to_prompt_block() == ""


def test_similar_unavailable_on_failure(monkeypatch):
    _patch(monkeypatch, fetch_raise=True)
    evidence = asyncio.run(similar.get_similar_projects_evidence(7, 5, db=None))

    assert evidence.status == "UNAVAILABLE"
    assert evidence.to_prompt_block() == ""


def test_similar_unauthorized_renders_nothing(monkeypatch):
    _patch(monkeypatch, auth="UNAUTHORIZED")
    evidence = asyncio.run(similar.get_similar_projects_evidence(7, 5, db=None))

    assert evidence.status == "UNAUTHORIZED"
    assert evidence.to_prompt_block() == ""
