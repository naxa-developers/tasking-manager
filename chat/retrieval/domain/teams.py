from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List

from loguru import logger

from chat.retrieval.domain.auth import authorize_project
from chat.retrieval.domain.evidence import DomainStatus, EvidenceBase, safe_value

TEAMS_OPERATION = "get_project_teams"
TEAMS_PROVENANCE = "TeamService.get_project_teams_as_dto"


@dataclass(frozen=True)
class ProjectTeamEntry:
    team_name: str
    role: str


@dataclass(frozen=True)
class ProjectTeamsEvidence(EvidenceBase):
    status: DomainStatus
    project_id: int
    operation: str = TEAMS_OPERATION
    teams: tuple[ProjectTeamEntry, ...] = ()
    provenance: str = TEAMS_PROVENANCE

    _CITATION_KIND = "teams"
    _CITATION_TITLE = "Project {id} live teams"
    _CITATION_HEADING = "project_teams"
    _CITATION_SOURCE = {
        "path": "backend/services/team_service.py",
        "symbol": "TeamService.get_project_teams_as_dto",
    }

    def _scope_id(self) -> Any:
        return self.project_id

    def _body_lines(self) -> List[str]:
        if not self.teams:
            return ["teams: none assigned"]
        lines = [f"teams ({len(self.teams)}):"]
        for entry in self.teams[:20]:
            lines.append(
                f"- {safe_value(entry.team_name)} ({safe_value(entry.role, 64)})"
            )
        return lines


def _role_name(raw: Any) -> str:
    """Map the stored role value to its TeamRoles name; never fail."""
    try:
        from backend.models.postgis.statuses import TeamRoles

        return TeamRoles(int(str(raw).strip())).name
    except Exception:
        return str(raw)


async def get_project_teams_evidence(
    user_id: int, project_id: int, db: Any
) -> ProjectTeamsEvidence:
    """Authorized read-only fetch of a project's teams + roles."""
    from backend.exceptions import NotFound

    status, _project = await authorize_project(user_id, project_id, db)
    if status != "OK":
        return ProjectTeamsEvidence(status=status, project_id=project_id)

    try:
        from backend.services.team_service import TeamService

        dto = await TeamService.get_project_teams_as_dto(project_id, db)
    except NotFound:
        return ProjectTeamsEvidence(status="NOT_FOUND", project_id=project_id)
    except Exception:
        logger.exception(f"project {project_id} teams fetch failed")
        return ProjectTeamsEvidence(status="UNAVAILABLE", project_id=project_id)

    entries: List[ProjectTeamEntry] = []
    for team in getattr(dto, "teams", None) or []:
        name = getattr(team, "team_name", None)
        if isinstance(team, dict):
            name = team.get("team_name")
        role = getattr(team, "role", None)
        if isinstance(team, dict):
            role = team.get("role")
        if name:
            entries.append(ProjectTeamEntry(team_name=str(name), role=_role_name(role)))
    return ProjectTeamsEvidence(
        status="OK", project_id=project_id, teams=tuple(entries)
    )
