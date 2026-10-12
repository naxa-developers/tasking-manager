"""Evidence invariants for the favorites op.

Mirrors ``UserService.get_projects_favorited`` for the asker's list and
``ProjectService.is_favorited`` for the per-project status when the question
names one project. Asker-only data.
"""

import asyncio
from dataclasses import dataclass
from typing import Any, List, Optional

import chat.retrieval.domain.favorites as favorites


@dataclass
class _Info:
    name: Optional[str]


@dataclass
class _FavRow:
    project_id: Optional[int]
    project_info: Optional[_Info]


class _FavDTO:
    def __init__(self, rows: List[_FavRow]):
        self.favorited_projects = rows


def _patch(
    monkeypatch,
    *,
    rows=None,
    is_favorited=None,
    fetch_raise=False,
    status_raise=False,
):
    from backend.services.project_service import ProjectService
    from backend.services.users.user_service import UserService

    async def _get_favorites(user_id, db):
        if fetch_raise:
            raise RuntimeError("boom")
        return _FavDTO(rows or [])

    async def _is_favorited(project_id, user_id, db):
        if status_raise:
            raise RuntimeError("boom")
        return is_favorited

    monkeypatch.setattr(UserService, "get_projects_favorited", _get_favorites)
    monkeypatch.setattr(ProjectService, "is_favorited", _is_favorited)


def test_favorites_list_and_project_status(monkeypatch):
    _patch(
        monkeypatch,
        rows=[
            _FavRow(12, _Info("Waterways")),
            _FavRow(34, _Info(None)),
        ],
        is_favorited=True,
    )
    evidence = asyncio.run(favorites.get_favorites_evidence(7, 5, db=None))

    assert evidence.status == "OK"
    block = evidence.to_prompt_block()
    assert "operation: get_user_favorites" in block
    assert "favorite_projects_total: 2" in block
    assert "project_5_is_favorite: yes" in block
    assert "favorite_projects (complete list, 2 items):" in block
    assert "1. #12 Waterways" in block
    assert "2. #34" in block


def test_favorites_project_not_favorited(monkeypatch):
    _patch(monkeypatch, rows=[], is_favorited=False)
    evidence = asyncio.run(favorites.get_favorites_evidence(7, 5, db=None))

    block = evidence.to_prompt_block()
    assert "project_5_is_favorite: no" in block
    assert "favorite_projects: none yet" in block


def test_favorites_without_project_omits_status(monkeypatch):
    _patch(monkeypatch, rows=[_FavRow(12, _Info("Waterways"))], is_favorited=True)
    evidence = asyncio.run(favorites.get_favorites_evidence(7, None, db=None))

    block = evidence.to_prompt_block()
    assert "_is_favorite:" not in block
    assert "favorite_projects_total: 1" in block


def test_favorites_cap_discloses_slice(monkeypatch):
    rows = [_FavRow(i, _Info(f"P{i}")) for i in range(1, 26)]
    _patch(monkeypatch, rows=rows)
    evidence = asyncio.run(favorites.get_favorites_evidence(7, None, db=None))

    block = evidence.to_prompt_block()
    assert "favorite_projects (showing 20 of 25):" in block
    assert "1. #1 P1" in block
    assert "20. #20 P20" in block
    assert "#21" not in block


def test_favorites_unavailable_when_list_fails(monkeypatch):
    _patch(monkeypatch, fetch_raise=True)
    evidence = asyncio.run(favorites.get_favorites_evidence(7, 5, db=None))

    assert evidence.status == "UNAVAILABLE"
    assert evidence.to_prompt_block() == ""


def test_favorites_status_failure_degrades(monkeypatch):
    _patch(monkeypatch, rows=[_FavRow(12, _Info("Waterways"))], status_raise=True)
    evidence = asyncio.run(favorites.get_favorites_evidence(7, 5, db=None))

    block = evidence.to_prompt_block()
    assert evidence.status == "OK"
    assert "favorite_projects_total: 1" in block
    assert "_is_favorite:" not in block
