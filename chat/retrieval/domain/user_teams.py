from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Tuple

from loguru import logger

from chat.retrieval.domain.evidence import DomainStatus, EvidenceBase, safe_value

TEAMS_FOR_USER_OPERATION = "get_user_teams"
TEAMS_FOR_USER_PROVENANCE = "TeamService.get_all_teams"

_MAX_TEAMS = 15


def _attr(obj: Any, name: str) -> Any:
    """Read a field off a DTO/ORM object or mapping; None when absent."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


@dataclass(frozen=True)
class UserTeamEntry:
    name: str
    organisation: str = ""
    visibility: str = ""


@dataclass(frozen=True)
class UserTeamsEvidence(EvidenceBase):
    """Team memberships for the authenticated user only."""

    status: DomainStatus
    user_id: int
    operation: str = TEAMS_FOR_USER_OPERATION
    teams: Tuple[UserTeamEntry, ...] = ()
    provenance: str = TEAMS_FOR_USER_PROVENANCE

    _CONTEXT_FIELD = "user_id"
    _CITATION_SCOPE = "user"
    _CITATION_KIND = "teams"
    _CITATION_TITLE = "User team memberships"
    _CITATION_HEADING = "user_teams"
    _CITATION_SOURCE = {
        "path": "backend/services/team_service.py",
        "symbol": "TeamService.get_all_teams",
    }

    def _scope_id(self) -> Any:
        return self.user_id

    def _body_lines(self) -> List[str]:
        if not self.teams:
            return ["teams: none — the user is not an active member of any team"]
        lines = [f"teams ({len(self.teams)}):"]
        for entry in self.teams[:_MAX_TEAMS]:
            parts = [safe_value(entry.name, 80)]
            if entry.organisation:
                parts.append(f"organisation: {safe_value(entry.organisation, 80)}")
            if entry.visibility:
                parts.append(f"visibility: {safe_value(entry.visibility, 32)}")
            lines.append("- " + " | ".join(parts))
        return lines


def _entry(team: Any) -> UserTeamEntry:
    return UserTeamEntry(
        name=str(_attr(team, "name") or ""),
        organisation=str(_attr(team, "organisation") or ""),
        visibility=str(_attr(team, "visibility") or ""),
    )


async def get_user_teams_evidence(user_id: int, db: Any) -> UserTeamsEvidence:
    """Read-only lookup of the asker's active team memberships."""
    try:
        from backend.models.dtos.team_dto import TeamSearchDTO
        from backend.services.team_service import TeamService

        search = TeamSearchDTO(
            user_id=user_id,
            member=user_id,
            omit_members=True,
            full_members_list=False,
            paginate=False,
        )
        result = await TeamService.get_all_teams(search, db)

        entries: List[UserTeamEntry] = []
        for team in _attr(result, "teams") or []:
            entry = _entry(team)
            if entry.name:
                entries.append(entry)

        return UserTeamsEvidence(
            status="OK", user_id=user_id, teams=tuple(entries[:_MAX_TEAMS])
        )
    except Exception:
        logger.exception(f"user {user_id} team membership fetch failed")
        return UserTeamsEvidence(status="UNAVAILABLE", user_id=user_id)
