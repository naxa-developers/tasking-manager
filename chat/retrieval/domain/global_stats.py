from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from loguru import logger

from chat.retrieval.domain.evidence import DomainStatus, EvidenceBase, safe_value

GLOBAL_STATS_OPERATION = "get_global_stats"
GLOBAL_STATS_PROVENANCE = "StatsService.get_rag_global_stats"

_MAX_ORGS = 8
_MAX_CAMPAIGNS = 8


def _attr(obj: Any, name: str) -> Any:
    """Read a field off a DTO/ORM object or mapping; None when absent."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class GlobalStatsEvidence(EvidenceBase):
    """Site-wide aggregate counts (read-only, cache-backed)."""

    status: DomainStatus
    user_id: int
    operation: str = GLOBAL_STATS_OPERATION
    total_projects: Optional[int] = None
    total_users: Optional[int] = None
    mappers_online: Optional[int] = None
    total_validators: Optional[int] = None
    tasks_mapped: Optional[int] = None
    tasks_validated: Optional[int] = None
    total_organisations: Optional[int] = None
    total_campaigns: Optional[int] = None
    top_organisations: Tuple[Tuple[str, int], ...] = ()
    top_campaigns: Tuple[Tuple[str, int], ...] = ()
    provenance: str = GLOBAL_STATS_PROVENANCE

    _CONTEXT_FIELD = "user_id"
    _CITATION_SCOPE = "global"
    _CITATION_KIND = "stats"
    _CITATION_TITLE = "Tasking Manager global statistics"
    _CITATION_HEADING = "global_stats"
    _CITATION_SOURCE = {
        "path": "backend/services/stats_service.py",
        "symbol": "StatsService.get_rag_global_stats",
    }
    _CITATION_ID_TEMPLATE = "tm:global:{kind}"
    _CITATION_DOC_TEMPLATE = "tasking_manager:global"

    def _scope_id(self) -> Any:
        return "tm"

    def _body_lines(self) -> List[str]:
        lines = [
            f"users_registered: {self.total_users}",
            f"projects_total: {self.total_projects}",
            f"tasks_mapped_total: {self.tasks_mapped}",
            f"tasks_validated_total: {self.tasks_validated}",
            "freshness: computed live from the current database",
        ]
        if self.total_validators is not None:
            lines.append(f"validators_total: {self.total_validators}")
        if self.mappers_online is not None:
            lines.append(f"mappers_with_locked_tasks_now: {self.mappers_online}")
        if self.total_organisations is not None:
            lines.append(f"organisations_total: {self.total_organisations}")
        if self.total_campaigns is not None:
            lines.append(f"campaigns_total: {self.total_campaigns}")
        if self.top_organisations:
            orgs = "; ".join(
                f"{safe_value(name, 60)}: {count}"
                for name, count in self.top_organisations[:_MAX_ORGS]
            )
            lines.append(f"projects_per_organisation: {orgs}")
        if self.top_campaigns:
            campaigns = "; ".join(
                f"{safe_value(name, 60)}: {count}"
                for name, count in self.top_campaigns[:_MAX_CAMPAIGNS]
            )
            lines.append(f"projects_per_campaign: {campaigns}")
        return lines


def _name_counts(
    rows: Any, name_field: str, value_field: str
) -> Tuple[Tuple[str, int], ...]:
    pairs: List[Tuple[str, int]] = []
    for row in rows or []:
        name = (
            _attr(row, name_field)
            or _attr(row, "organisation")
            or _attr(row, "campaign")
        )
        count = _int_or_none(_attr(row, value_field))
        if name and count is not None:
            pairs.append((str(name), count))
    return tuple(pairs)


async def get_global_stats_evidence(user_id: int, db: Any) -> GlobalStatsEvidence:
    """Read-only site-wide counts for the authenticated asker."""
    try:
        from backend.services.stats_service import StatsService

        stats = await StatsService.get_rag_global_stats(db)

        top_orgs = _name_counts(
            _attr(stats, "organisations"), "organisation", "projects_created"
        )
        top_campaigns = _name_counts(
            _attr(stats, "campaigns"), "campaign", "projects_created"
        )

        return GlobalStatsEvidence(
            status="OK",
            user_id=user_id,
            total_projects=_int_or_none(_attr(stats, "total_projects")),
            total_users=_int_or_none(_attr(stats, "total_users")),
            mappers_online=_int_or_none(_attr(stats, "mappers_online")),
            total_validators=_int_or_none(_attr(stats, "total_validators")),
            tasks_mapped=_int_or_none(_attr(stats, "tasks_mapped")),
            tasks_validated=_int_or_none(_attr(stats, "tasks_validated")),
            total_organisations=_int_or_none(_attr(stats, "total_organisations")),
            total_campaigns=_int_or_none(_attr(stats, "total_campaigns")),
            top_organisations=top_orgs,
            top_campaigns=top_campaigns,
        )
    except Exception:
        logger.exception(f"user {user_id} global stats fetch failed")
        return GlobalStatsEvidence(status="UNAVAILABLE", user_id=user_id)
