from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

from loguru import logger

from rag.domain._rows import _attr
from rag.domain.evidence import DomainStatus, EvidenceBase

OSM_OPERATION = "get_user_osm_stats"
OSM_PROVENANCE = "UserService.get_osm_details_for_user"


@dataclass(frozen=True)
class UserOsmStatsEvidence(EvidenceBase):
    """The asker's OpenStreetMap account details.

    Mirrors ``UserService.get_osm_details_for_user`` (the OSM API lookup
    behind the openstreetmap endpoint). External dependency: unreachable OSM
    surfaces as UNAVAILABLE. Ohsome edit statistics are served by a separate
    proxy endpoint with no stored-copy service here, so they are out of
    scope.
    """

    status: DomainStatus
    user_id: int
    operation: str = OSM_OPERATION
    osm_username: Optional[str] = None
    account_created: Optional[str] = None
    changeset_count: Optional[int] = None
    provenance: str = OSM_PROVENANCE

    _CONTEXT_FIELD = "user_id"
    _CITATION_SCOPE = "user"
    _CITATION_KIND = "osm"
    _CITATION_TITLE = "User {id} OpenStreetMap stats"
    _CITATION_HEADING = "user_osm_stats"
    _CITATION_SOURCE = {
        "path": "backend/services/users/user_service.py",
        "symbol": "UserService.get_osm_details_for_user",
    }

    def _scope_id(self) -> Any:
        return self.user_id

    def _body_lines(self) -> List[str]:
        lines: List[str] = []
        if self.osm_username:
            lines.append(f"osm_username: {self.osm_username}")
        if self.account_created:
            lines.append(f"osm_account_created: {self.account_created}")
        if self.changeset_count is not None:
            lines.append(f"osm_changeset_count: {self.changeset_count}")
        return lines


async def get_user_osm_stats_evidence(user_id: int, db: Any) -> UserOsmStatsEvidence:
    """Read-only OSM account details for the asker."""
    from backend.models.postgis.user import User as UserModel
    from backend.services.users.user_service import UserService

    user = await UserModel.get_by_id(user_id, db)
    username = _attr(user, "username")
    if not username:
        return UserOsmStatsEvidence(status="NOT_FOUND", user_id=user_id)

    try:
        dto = await UserService.get_osm_details_for_user(str(username), db)
    except Exception:
        logger.exception(f"user {user_id} OSM details fetch failed")
        return UserOsmStatsEvidence(status="UNAVAILABLE", user_id=user_id)

    return UserOsmStatsEvidence(
        status="OK",
        user_id=user_id,
        osm_username=str(username),
        account_created=_attr(dto, "account_created"),
        changeset_count=_attr(dto, "changeset_count"),
    )
