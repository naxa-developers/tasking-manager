from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from loguru import logger

from chat.retrieval.domain.evidence import DomainStatus, EvidenceBase

ACTIVITY_OPERATION = "get_user_activity"
ACTIVITY_PROVENANCE = (
    "UserService.get_contributions_by_day + UserService.get_detailed_stats"
)


def _attr(obj: Any, name: str) -> Any:
    """Read a field off a DTO/ORM object or mapping; None when absent."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _as_date(value: Any) -> Optional[datetime.date]:
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    return None


def _int_or_zero(value: Any) -> int:
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0


def _streaks(days: List[datetime.date], today: datetime.date) -> Tuple[int, int]:
    """Return (current_streak, longest_streak) over consecutive-day runs."""
    if not days:
        return 0, 0
    unique = sorted(set(days))
    longest = 1
    run = 1
    for previous, current in zip(unique, unique[1:]):
        if (current - previous).days == 1:
            run += 1
            longest = max(longest, run)
        else:
            run = 1
    last = unique[-1]
    if (today - last).days > 1:
        return 0, longest
    current_streak = 1
    for previous, current in zip(reversed(unique[:-1]), reversed(unique)):
        if (current - previous).days == 1:
            current_streak += 1
        else:
            break
    return current_streak, longest


@dataclass(frozen=True)
class UserActivityEvidence(EvidenceBase):
    """Current mapping streak and mapping-vs-validation split."""

    status: DomainStatus
    user_id: int
    operation: str = ACTIVITY_OPERATION
    current_streak_days: int = 0
    longest_streak_days: int = 0
    active_days_last_30: int = 0
    tasks_mapped: Optional[int] = None
    tasks_validated: Optional[int] = None
    tasks_invalidated: Optional[int] = None
    mapping_share_percent: Optional[int] = None
    validation_share_percent: Optional[int] = None
    provenance: str = ACTIVITY_PROVENANCE

    _CONTEXT_FIELD = "user_id"
    _CITATION_SCOPE = "user"
    _CITATION_KIND = "activity"
    _CITATION_TITLE = "User activity summary"
    _CITATION_HEADING = "user_activity"
    _CITATION_SOURCE = {
        "path": "backend/services/users/user_service.py",
        "symbol": "UserService.get_contributions_by_day",
    }

    def _scope_id(self) -> Any:
        return self.user_id

    def _body_lines(self) -> List[str]:
        no_split = "none — no mapped or validated tasks yet"
        mapped_share = (
            f"{self.mapping_share_percent}%"
            if self.mapping_share_percent is not None
            else no_split
        )
        validation_share = (
            f"{self.validation_share_percent}%"
            if self.validation_share_percent is not None
            else no_split
        )
        return [
            f"current_mapping_streak_days: {self.current_streak_days}",
            f"longest_mapping_streak_days: {self.longest_streak_days}",
            f"active_days_last_30: {self.active_days_last_30}",
            f"tasks_mapped_all_time: {self.tasks_mapped}",
            f"tasks_validated_all_time: {self.tasks_validated}",
            f"tasks_invalidated_all_time: {self.tasks_invalidated}",
            f"mapping_share_percent: {mapped_share}",
            f"validation_share_percent: {validation_share}",
        ]


async def get_user_activity_evidence(user_id: int, db: Any) -> UserActivityEvidence:
    """Read-only streak + contribution split for the authenticated user."""
    try:
        from backend.models.postgis.user import User as UserModel
        from backend.services.users.user_service import UserService

        user = await UserModel.get_by_id(user_id, db)
        if user is None:
            return UserActivityEvidence(status="NOT_FOUND", user_id=user_id)

        today = datetime.date.today()
        active_days: List[datetime.date] = []
        by_day = await UserService.get_contributions_by_day(user_id, db)
        for row in by_day or []:
            day = _as_date(_attr(row, "date"))
            if day is not None:
                active_days.append(day)

        current_streak, longest_streak = _streaks(active_days, today)
        active_last_30 = len([day for day in active_days if (today - day).days <= 30])

        stats = None
        username = _attr(user, "username")
        if username:
            stats = await UserService.get_detailed_stats(str(username), db)

        mapped = _attr(stats, "tasks_mapped")
        validated = _attr(stats, "tasks_validated")
        mapped_share: Optional[int] = None
        validation_share: Optional[int] = None
        if mapped is not None and validated is not None:
            total = _int_or_zero(mapped) + _int_or_zero(validated)
            if total > 0:
                mapped_share = round(_int_or_zero(mapped) * 100 / total)
                validation_share = 100 - mapped_share

        return UserActivityEvidence(
            status="OK",
            user_id=user_id,
            current_streak_days=current_streak,
            longest_streak_days=longest_streak,
            active_days_last_30=active_last_30,
            tasks_mapped=mapped,
            tasks_validated=validated,
            tasks_invalidated=_attr(stats, "tasks_invalidated"),
            mapping_share_percent=mapped_share,
            validation_share_percent=validation_share,
        )
    except Exception:
        logger.exception(f"user {user_id} activity fetch failed")
        return UserActivityEvidence(status="UNAVAILABLE", user_id=user_id)
