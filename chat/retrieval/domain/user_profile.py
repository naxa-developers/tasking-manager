from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from loguru import logger

from chat.retrieval.domain.evidence import DomainStatus, EvidenceBase, safe_value

PROFILE_OPERATION = "get_user_profile"
PROFILE_PROVENANCE = (
    "UserService.get_mapping_level + UserService.next_level + "
    "MappingBadge.get_public_for_user"
)

_MAX_BADGES = 12
_MAX_METRICS = 12


def _attr(obj: Any, name: str) -> Any:
    """Read a field off a DTO/ORM object or mapping; None when absent."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _names(rows: Any, limit: int = _MAX_BADGES) -> Tuple[str, ...]:
    names: List[str] = []
    for row in rows or []:
        name = _attr(row, "name")
        if name:
            names.append(str(name))
        if len(names) >= limit:
            break
    return tuple(names)


@dataclass(frozen=True)
class UserProfileEvidence(EvidenceBase):
    """Mapping level + badge progress for the asker only."""

    status: DomainStatus
    user_id: int
    operation: str = PROFILE_OPERATION
    current_level: Optional[str] = None
    next_level: Optional[str] = None
    max_level: bool = False
    aggregated_progress: Optional[float] = None
    aggregated_goal: Optional[float] = None
    metrics: Tuple[str, ...] = ()
    earned_badges: Tuple[str, ...] = ()
    missing_badges: Tuple[str, ...] = ()
    provenance: str = PROFILE_PROVENANCE

    _CONTEXT_FIELD = "user_id"
    _CITATION_SCOPE = "user"
    _CITATION_KIND = "profile"
    _CITATION_TITLE = "User mapping profile"
    _CITATION_HEADING = "user_profile"
    _CITATION_SOURCE = {
        "path": "backend/services/users/user_service.py",
        "symbol": "UserService.next_level",
    }

    def _scope_id(self) -> Any:
        return self.user_id

    def _body_lines(self) -> List[str]:
        lines: List[str] = []
        if self.current_level:
            lines.append(f"current_mapping_level: {safe_value(self.current_level, 64)}")
        if self.max_level:
            lines.append("next_level: none — the user is at the highest mapping level")
        elif self.next_level:
            lines.append(f"next_level: {safe_value(self.next_level, 64)}")
            if self.aggregated_goal:
                lines.append(
                    f"progress_towards_next_level: {int(self.aggregated_progress or 0)}"
                    f" / {int(self.aggregated_goal)}"
                )
            if self.metrics:
                metrics = ", ".join(
                    safe_value(m, 40) for m in self.metrics[:_MAX_METRICS]
                )
                lines.append(f"progress_metrics: {metrics}")
        if self.earned_badges:
            badges = ", ".join(
                safe_value(b, 64) for b in self.earned_badges[:_MAX_BADGES]
            )
            lines.append(f"earned_badges ({len(self.earned_badges)}): {badges}")
        else:
            lines.append("earned_badges: none — no badges earned yet")
            lines.append("earned_badges_count: 0")
        if self.missing_badges:
            missing = ", ".join(
                safe_value(b, 64) for b in self.missing_badges[:_MAX_BADGES]
            )
            lines.append(f"badges_still_needed_for_next_level: {missing}")
        return lines


async def get_user_profile_evidence(user_id: int, db: Any) -> UserProfileEvidence:
    """Read-only mapping level and badge progress for the authenticated user."""
    try:
        from backend.models.postgis.mapping_badge import MappingBadge
        from backend.models.postgis.mapping_level import MappingLevel
        from backend.services.users.user_service import UserService

        level = await UserService.get_mapping_level(user_id, db)
        current_level = _attr(level, "name")

        earned_rows = await MappingBadge.get_public_for_user(user_id, db)
        earned_badges = _names(earned_rows)

        earned_ids = set()
        try:
            all_rows = await MappingBadge.get_related_to_user(user_id, db)
            earned_ids = {
                int(_attr(row, "id"))
                for row in all_rows or []
                if _attr(row, "id") is not None
            }
        except Exception:
            logger.exception(f"user {user_id} badge id lookup failed")

        dto = await UserService.next_level(user_id, db)
        if dto is None:
            return UserProfileEvidence(
                status="OK",
                user_id=user_id,
                current_level=current_level,
                max_level=True,
                earned_badges=earned_badges,
            )

        next_name = _attr(dto, "next_level") or _attr(dto, "nextLevel")

        missing_badges: Tuple[str, ...] = ()
        if next_name:
            try:
                next_row = await MappingLevel.get_by_name(str(next_name), db)
                if next_row is not None:
                    required = await MappingBadge.get_related_to_level(
                        _attr(next_row, "id"), db
                    )
                    missing_badges = tuple(
                        str(_attr(b, "name"))
                        for b in required or []
                        if _attr(b, "id") not in earned_ids
                        and _attr(b, "name")
                        and not _attr(b, "is_internal")
                    )
            except Exception:
                logger.exception(f"user {user_id} required-badge lookup failed")

        return UserProfileEvidence(
            status="OK",
            user_id=user_id,
            current_level=current_level,
            next_level=str(next_name) if next_name else None,
            aggregated_progress=_attr(dto, "aggregated_progress"),
            aggregated_goal=_attr(dto, "aggregated_goal"),
            metrics=tuple(str(m) for m in (_attr(dto, "metrics") or [])),
            earned_badges=earned_badges,
            missing_badges=missing_badges,
        )
    except Exception:
        logger.exception(f"user {user_id} profile fetch failed")
        return UserProfileEvidence(status="UNAVAILABLE", user_id=user_id)
