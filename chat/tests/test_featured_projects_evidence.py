"""Evidence invariants for the featured-projects op."""

import asyncio
from dataclasses import dataclass
from typing import List, Optional

import chat.retrieval.domain.featured_projects as featured


@dataclass
class _Result:
    project_id: Optional[int]
    name: Optional[str] = None
    status: Optional[str] = "PUBLISHED"


class _ResultsDTO:
    def __init__(self, rows: List[_Result]):
        self.results = rows


def _patch(monkeypatch, *, rows=None, fetch_raise=False):
    from backend.services.project_service import ProjectService

    async def _get(locale, db):
        if fetch_raise:
            raise RuntimeError("boom")
        return _ResultsDTO(rows or [])

    monkeypatch.setattr(ProjectService, "get_featured_projects", _get)


def test_featured_renders_entries(monkeypatch):
    _patch(monkeypatch, rows=[_Result(9, "Roads A"), _Result(10, "Health B")])
    evidence = asyncio.run(featured.get_featured_projects_evidence(7, db=None))

    assert evidence.status == "OK"
    block = evidence.to_prompt_block()
    assert "operation: get_featured_projects" in block
    assert "featured_projects (2):" in block
    assert "#9 Roads A | status: PUBLISHED" in block
    assert "#10 Health B" in block


def test_featured_empty(monkeypatch):
    _patch(monkeypatch, rows=[])
    evidence = asyncio.run(featured.get_featured_projects_evidence(7, db=None))

    assert "featured_projects: none right now" in evidence.to_prompt_block()


def test_featured_unavailable_on_failure(monkeypatch):
    _patch(monkeypatch, fetch_raise=True)
    evidence = asyncio.run(featured.get_featured_projects_evidence(7, db=None))

    assert evidence.status == "UNAVAILABLE"
    assert evidence.to_prompt_block() == ""
