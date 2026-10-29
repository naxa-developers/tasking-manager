from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from loguru import logger

from chat.domain._rows import _attr
from chat.domain.evidence import DomainStatus, EvidenceBase, safe_value

TEAM_OPERATION = "get_team_detail"
TEAM_PROVENANCE = "TeamService.get_team_as_dto"

# Per-op prompt-size guard for the member list.
_MAX_MEMBERS = 20


@dataclass(frozen=True)
class TeamDetailEvidence(EvidenceBase):
    """One team's details: organisation, visibility, join method, members."""

    status: DomainStatus
    team_id: int
    operation: str = TEAM_OPERATION
    name: Optional[str] = None
    organisation: Optional[str] = None
    visibility: Optional[str] = None
    join_method: Optional[str] = None
    description: Optional[str] = None
    members_total: Optional[int] = None
    members: Tuple[str, ...] = ()
    pending_join_requests: Optional[int] = None
    provenance: str = TEAM_PROVENANCE

    _CONTEXT_FIELD = "team_id"
    _CITATION_KIND = "team"
    _CITATION_TITLE = "Team {id}"
    _CITATION_HEADING = "team_detail"
    _CITATION_SOURCE = {
        "path": "backend/services/team_service.py",
        "symbol": "TeamService.get_team_as_dto",
    }

    def _scope_id(self) -> Any:
        return self.team_id

    def _body_lines(self) -> List[str]:
        lines: List[str] = []
        if self.name:
            lines.append(f"team_name: {safe_value(self.name, 80)}")
        if self.organisation:
            lines.append(f"organisation: {safe_value(self.organisation, 80)}")
        if self.visibility:
            lines.append(f"visibility: {safe_value(self.visibility, 32)}")
        if self.join_method:
            lines.append(f"join_method: {safe_value(self.join_method, 32)}")
        if self.description:
            lines.append(f"description: {safe_value(self.description, 200)}")
        if self.members:
            shown = self.members[:_MAX_MEMBERS]
            label = "members"
            if self.members_total is not None and self.members_total > len(shown):
                label += f" (showing {len(shown)} of {self.members_total})"
            else:
                label += f" (complete list, {len(shown)} items)"
            lines.append(label + ":")
            lines.extend(
                f"{position}. {safe_value(name, 80)}"
                for position, name in enumerate(shown, start=1)
            )
        elif self.members_total == 0:
            lines.append("members: none")
        if self.pending_join_requests is not None:
            lines.append(f"pending_join_requests: {self.pending_join_requests}")
        return lines


async def get_team_detail_evidence(
    user_id: int, project_id: Any, db: Any, filters: Optional[dict] = None
) -> TeamDetailEvidence:
    """Read-only team details for the route's ``team_id`` filter."""
    raw = (filters or {}).get("team_id")
    try:
        team_id = int(raw) if raw is not None else 0
    except (TypeError, ValueError):
        team_id = 0
    if team_id <= 0:
        return TeamDetailEvidence(status="NOT_FOUND", team_id=0)

    from backend.exceptions import NotFound
    from backend.services.team_service import TeamService

    try:
        dto = await TeamService.get_team_as_dto(team_id, user_id, False, db)
    except NotFound:
        return TeamDetailEvidence(status="NOT_FOUND", team_id=team_id)
    except Exception:
        logger.exception(f"team {team_id} detail fetch failed")
        return TeamDetailEvidence(status="UNAVAILABLE", team_id=team_id)

    members: List[str] = []
    for row in _attr(dto, "members") or []:
        username = _attr(row, "username")
        if username:
            members.append(str(username))

    pending: Optional[int] = None
    if _attr(dto, "is_org_admin") or _attr(dto, "is_general_admin"):
        try:
            row = await db.fetch_one(
                query=(
                    "SELECT COUNT(*) AS n FROM team_members "
                    "WHERE team_id = :team_id AND active = FALSE"
                ),
                values={"team_id": team_id},
            )
            pending = int(_attr(row, "n") or 0)
        except Exception:
            logger.exception(f"team {team_id} join-request count failed")

    return TeamDetailEvidence(
        status="OK",
        team_id=team_id,
        name=_attr(dto, "name"),
        organisation=_attr(dto, "organisation"),
        visibility=_attr(dto, "visibility"),
        join_method=_attr(dto, "join_method"),
        description=_attr(dto, "description"),
        members_total=len(members),
        members=tuple(members),
        pending_join_requests=pending,
    )
