from __future__ import annotations

import pytest

from backend.models.postgis.statuses import ProjectStatus
from backend.services.project_admin_service import ProjectAdminService
from backend.services.project_service import ProjectService
from backend.services.team_service import TeamService


def _project(*, private: bool, status: int = ProjectStatus.PUBLISHED.value):
    return {"id": 7, "private": private, "status": status}


def _patch_access(monkeypatch, *, manager=False, allowed=False, team=False) -> None:
    async def fake_manager(*args, **kwargs):
        return manager

    async def fake_allowed(*args, **kwargs):
        return allowed

    async def fake_team(*args, **kwargs):
        return team

    monkeypatch.setattr(
        ProjectAdminService, "is_user_action_permitted_on_project", fake_manager
    )
    monkeypatch.setattr(ProjectService, "is_user_in_the_allowed_list", fake_allowed)
    monkeypatch.setattr(TeamService, "check_team_membership", fake_team)


@pytest.mark.asyncio
async def test_public_published_project_is_readable(monkeypatch) -> None:
    _patch_access(monkeypatch)
    assert (
        await ProjectService.can_user_read_project(
            _project(private=False), None, object()
        )
        is True
    )


@pytest.mark.asyncio
async def test_private_project_requires_a_user(monkeypatch) -> None:
    _patch_access(monkeypatch, allowed=True, team=True)
    assert (
        await ProjectService.can_user_read_project(
            _project(private=True), None, object()
        )
        is False
    )


@pytest.mark.asyncio
async def test_private_project_denied_without_relationship(monkeypatch) -> None:
    _patch_access(monkeypatch)
    assert (
        await ProjectService.can_user_read_project(
            _project(private=True), 5, object()
        )
        is False
    )


@pytest.mark.asyncio
async def test_private_project_allowed_user(monkeypatch) -> None:
    _patch_access(monkeypatch, allowed=True)
    assert (
        await ProjectService.can_user_read_project(
            _project(private=True), 5, object()
        )
        is True
    )


@pytest.mark.asyncio
async def test_private_project_team_member(monkeypatch) -> None:
    _patch_access(monkeypatch, team=True)
    assert (
        await ProjectService.can_user_read_project(
            _project(private=True), 5, object()
        )
        is True
    )


@pytest.mark.asyncio
async def test_private_project_manager(monkeypatch) -> None:
    _patch_access(monkeypatch, manager=True)
    assert (
        await ProjectService.can_user_read_project(
            _project(private=True), 5, object()
        )
        is True
    )


@pytest.mark.asyncio
async def test_draft_project_requires_manager(monkeypatch) -> None:
    _patch_access(monkeypatch, allowed=True, team=True)
    assert (
        await ProjectService.can_user_read_project(
            _project(private=False, status=ProjectStatus.DRAFT.value), 5, object()
        )
        is False
    )


@pytest.mark.asyncio
async def test_draft_project_manager_can_read(monkeypatch) -> None:
    _patch_access(monkeypatch, manager=True)
    assert (
        await ProjectService.can_user_read_project(
            _project(private=False, status=ProjectStatus.DRAFT.value), 5, object()
        )
        is True
    )


@pytest.mark.asyncio
async def test_missing_visibility_fields_fail_closed() -> None:
    assert await ProjectService.can_user_read_project({"id": 7}, 5, object()) is False
