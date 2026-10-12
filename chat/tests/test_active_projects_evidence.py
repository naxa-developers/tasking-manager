"""Evidence invariants for the active-projects op.

``ProjectService.get_active_projects`` returns a GeoJSON feature collection
(project ids + mapping types); names are resolved separately.
"""

import asyncio
from typing import Any, List, Optional

import chat.retrieval.domain.active_projects as active


class _Feature:
    def __init__(self, pid: int, mapping_types: Optional[Any] = None):
        self.properties = {"project_id": pid, "mapping_types": mapping_types}


class _Collection:
    def __init__(self, features: List[_Feature]):
        self.features = features


class _FakeDB:
    def __init__(self, names=None, raise_on_fetch=False):
        self.names = names or {}
        self.raise_on_fetch = raise_on_fetch
        self.queries: List[str] = []

    async def fetch_all(self, query: str, values: Optional[dict] = None):
        self.queries.append(query)
        if self.raise_on_fetch:
            raise RuntimeError("boom")
        ids = (values or {}).get("project_ids") or []
        return [{"id": pid, "name": self.names.get(pid)} for pid in ids]


def _patch(monkeypatch, *, features=None, fetch_raise=False):
    from backend.services.project_service import ProjectService

    async def _get(interval, db, sandbox=False):
        if fetch_raise:
            raise RuntimeError("boom")
        return _Collection(features if features is not None else [])

    monkeypatch.setattr(ProjectService, "get_active_projects", _get)


def test_active_projects_with_names(monkeypatch):
    _patch(
        monkeypatch,
        features=[_Feature(9, ["ROADS"]), _Feature(10, ["BUILDINGS"])],
    )
    db = _FakeDB(names={9: "Roads A", 10: "Health B"})
    evidence = asyncio.run(active.get_active_projects_evidence(7, db))

    assert evidence.status == "OK"
    block = evidence.to_prompt_block()
    assert "operation: get_active_projects" in block
    assert "active_projects (last 24h) (complete list, 2 items):" in block
    assert "1. #9 Roads A | mapping types: ROADS" in block
    assert "2. #10 Health B | mapping types: BUILDINGS" in block


def test_active_projects_cap_discloses(monkeypatch):
    features = [_Feature(i) for i in range(1, 11)]
    _patch(monkeypatch, features=features)
    db = _FakeDB(names={i: f"P{i}" for i in range(1, 11)})
    evidence = asyncio.run(active.get_active_projects_evidence(7, db))

    block = evidence.to_prompt_block()
    assert "active_projects (last 24h) (showing 8 of 10):" in block
    assert "8. #8 P8" in block
    assert "#9" not in block


def test_active_projects_empty(monkeypatch):
    _patch(monkeypatch, features=[])
    db = _FakeDB()
    evidence = asyncio.run(active.get_active_projects_evidence(7, db))

    assert "active_projects (last 24h): none" in evidence.to_prompt_block()


def test_active_projects_unavailable_on_failure(monkeypatch):
    _patch(monkeypatch, fetch_raise=True)
    db = _FakeDB()
    evidence = asyncio.run(active.get_active_projects_evidence(7, db))

    assert evidence.status == "UNAVAILABLE"
    assert evidence.to_prompt_block() == ""


def test_active_projects_name_lookup_failure_keeps_ids(monkeypatch):
    _patch(monkeypatch, features=[_Feature(9, ["ROADS"])])
    db = _FakeDB(raise_on_fetch=True)
    evidence = asyncio.run(active.get_active_projects_evidence(7, db))

    block = evidence.to_prompt_block()
    assert evidence.status == "OK"
    assert "1. #9 | mapping types: ROADS" in block
