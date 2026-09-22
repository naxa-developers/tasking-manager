from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from chat.retrieval.domain.evidence import DomainStatus, EvidenceBase, safe_value

CONTRIBUTION_OPERATION = "get_user_contributions"
CONTRIBUTION_PROVENANCE = "UserService.get_detailed_stats"

_MAX_MONTHS = 6
_MAX_PROJECTS = 10


def _attr(obj: Any, name: str) -> Any:
    """Read a field off a DTO/ORM object or mapping; None when absent."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _int_or_zero(value: Any) -> int:
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0


def _hours(seconds: Any) -> Optional[float]:
    try:
        if seconds is None:
            return None
        return round(float(seconds) / 3600.0, 1)
    except (TypeError, ValueError):
        return None


def _month_key(day: Any) -> Optional[str]:
    if isinstance(day, datetime.datetime):
        day = day.date()
    if isinstance(day, datetime.date):
        return day.strftime("%Y-%m")
    return None


def _monthly_totals(rows: Any) -> Tuple[Tuple[str, int], ...]:
    """Group per-day contribution rows into recent months, newest first."""
    totals: Dict[str, int] = {}
    for row in rows or []:
        key = _month_key(_attr(row, "date"))
        if key is None:
            continue
        totals[key] = totals.get(key, 0) + _int_or_zero(_attr(row, "count"))
    ordered = sorted(totals.items(), key=lambda item: item[0], reverse=True)
    return tuple(ordered[:_MAX_MONTHS])


@dataclass(frozen=True)
class ContributionProject:
    project_id: Optional[int]
    name: Optional[str] = None
    tasks_mapped: int = 0
    tasks_validated: int = 0


@dataclass(frozen=True)
class UserContributionEvidence(EvidenceBase):
    """Lifetime contribution totals plus recent monthly activity."""

    status: DomainStatus
    user_id: int
    operation: str = CONTRIBUTION_OPERATION
    total_hours: Optional[float] = None
    mapping_hours: Optional[float] = None
    validation_hours: Optional[float] = None
    tasks_mapped: Optional[int] = None
    tasks_validated: Optional[int] = None
    tasks_invalidated: Optional[int] = None
    projects_contributed: Optional[int] = None
    countries_contributed: Optional[int] = None
    months: Tuple[Tuple[str, int], ...] = ()
    projects: Tuple[ContributionProject, ...] = ()
    provenance: str = CONTRIBUTION_PROVENANCE

    _CONTEXT_FIELD = "user_id"
    _CITATION_SCOPE = "user"
    _CITATION_KIND = "contributions"
    _CITATION_TITLE = "User contribution summary"
    _CITATION_HEADING = "user_contributions"
    _CITATION_SOURCE = {
        "path": "backend/services/users/user_service.py",
        "symbol": "UserService.get_detailed_stats",
    }

    def _scope_id(self) -> Any:
        return self.user_id

    def _body_lines(self) -> List[str]:
        lines: List[str] = []
        if self.total_hours is not None:
            lines.append(f"total_contribution_hours_all_time: {self.total_hours}")
        if self.mapping_hours is not None:
            lines.append(f"mapping_hours_all_time: {self.mapping_hours}")
        if self.validation_hours is not None:
            lines.append(f"validation_hours_all_time: {self.validation_hours}")
        if self.tasks_mapped is not None:
            lines.append(f"tasks_mapped_all_time: {self.tasks_mapped}")
        if self.tasks_validated is not None:
            lines.append(f"tasks_validated_all_time: {self.tasks_validated}")
        if self.tasks_invalidated is not None:
            lines.append(f"tasks_invalidated_all_time: {self.tasks_invalidated}")
        if self.projects_contributed is not None:
            lines.append(f"projects_contributed_to: {self.projects_contributed}")
        if self.countries_contributed is not None:
            lines.append(f"countries_contributed_to: {self.countries_contributed}")
        if self.months:
            recent = ", ".join(f"{month}: {count}" for month, count in self.months)
            lines.append(f"task_contributions_by_month: {recent}")
        if self.projects:
            parts = []
            for project in self.projects[:_MAX_PROJECTS]:
                name = safe_value(project.name, 80) if project.name else ""
                label = f"#{project.project_id}" + (f" {name}" if name else "")
                parts.append(
                    f"{label} (mapped {project.tasks_mapped}, "
                    f"validated {project.tasks_validated})"
                )
            lines.append("recent_projects: " + "; ".join(parts))
        return lines


async def get_user_contribution_evidence(
    user_id: int, db: Any
) -> UserContributionEvidence:
    """Read-only lifetime + monthly contribution summary for the asker."""
    try:
        from backend.models.postgis.user import User as UserModel
        from backend.services.users.user_service import UserService

        user = await UserModel.get_by_id(user_id, db)
        if user is None:
            return UserContributionEvidence(status="NOT_FOUND", user_id=user_id)

        username = _attr(user, "username")
        if not username:
            return UserContributionEvidence(status="NOT_FOUND", user_id=user_id)

        stats = await UserService.get_detailed_stats(str(username), db)

        months: Tuple[Tuple[str, int], ...] = ()
        try:
            by_day = await UserService.get_contributions_by_day(user_id, db)
            months = _monthly_totals(by_day)
        except Exception:
            logger.exception(f"user {user_id} daily contributions fetch failed")

        projects: List[ContributionProject] = []
        try:
            dto = await UserModel.get_mapped_projects(user_id, "en", db)
            for row in (_attr(dto, "mapped_projects") or [])[:_MAX_PROJECTS]:
                projects.append(
                    ContributionProject(
                        project_id=_attr(row, "project_id"),
                        name=_attr(row, "name"),
                        tasks_mapped=_int_or_zero(_attr(row, "tasks_mapped")),
                        tasks_validated=_int_or_zero(_attr(row, "tasks_validated")),
                    )
                )
        except Exception:
            logger.exception(f"user {user_id} project list fetch failed")

        countries = _attr(stats, "countries_contributed")

        return UserContributionEvidence(
            status="OK",
            user_id=user_id,
            total_hours=_hours(_attr(stats, "total_time_spent")),
            mapping_hours=_hours(_attr(stats, "time_spent_mapping")),
            validation_hours=_hours(_attr(stats, "time_spent_validating")),
            tasks_mapped=_attr(stats, "tasks_mapped"),
            tasks_validated=_attr(stats, "tasks_validated"),
            tasks_invalidated=_attr(stats, "tasks_invalidated"),
            projects_contributed=_attr(stats, "projects_mapped"),
            countries_contributed=_attr(countries, "total"),
            months=months,
            projects=tuple(projects),
        )
    except Exception:
        logger.exception(f"user {user_id} contribution fetch failed")
        return UserContributionEvidence(status="UNAVAILABLE", user_id=user_id)
