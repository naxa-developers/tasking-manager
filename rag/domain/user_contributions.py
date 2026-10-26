from __future__ import annotations

import datetime
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from rag.env import env_int
from rag.domain._rows import _attr, _int_or_zero
from rag.domain.evidence import DomainStatus, EvidenceBase, safe_value

CONTRIBUTION_OPERATION = "get_user_contributions"
CONTRIBUTION_PROVENANCE = "UserService.get_detailed_stats"

_MAX_MONTHS = 6
# The contributed-projects list renders completely by default; set
# RAG_MAX_USER_PROJECTS=N (N > 0) to cap it for very long answers. The stated
# total and status breakdown always cover every project the backend records;
# the list is disclosed as partial when it exceeds the cap.
_PREFERRED_LOCALE = "en"
_STATUS_ORDER = ("PUBLISHED", "ARCHIVED", "DRAFT")


def _max_projects() -> Optional[int]:
    """Optional render cap for the contributed-projects list.

    ``RAG_MAX_USER_PROJECTS`` unset, 0, or invalid means no cap: render every
    contributed project.
    """
    cap = env_int("RAG_MAX_USER_PROJECTS", 0)
    return cap if cap > 0 else None


def _status_label(value: Any) -> Optional[str]:
    """Project status name (PUBLISHED/DRAFT/ARCHIVED), None when unknown."""
    try:
        from backend.models.postgis.statuses import ProjectStatus

        return ProjectStatus(int(value)).name
    except Exception:
        return None


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
    status: Optional[str] = None
    tasks_mapped: Optional[int] = None
    tasks_validated: Optional[int] = None


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
    # Every contributed project the backend records (users.projects_mapped).
    contributed_projects_total: Optional[int] = None
    projects_by_status: Tuple[Tuple[str, int], ...] = ()
    countries_contributed: Optional[int] = None
    months: Tuple[Tuple[str, int], ...] = ()
    this_month: Optional[Tuple[str, int]] = None
    last_month: Optional[Tuple[str, int]] = None
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

    @property
    def contributions_total(self) -> Optional[int]:
        """Task actions performed, all time.

        The backend has no single "contributions" figure, so this is the sum of
        the three action counts it does record. A task mapped and later
        validated by the same person counts twice — it is two contributions.
        """
        parts = [
            value
            for value in (
                self.tasks_mapped,
                self.tasks_validated,
                self.tasks_invalidated,
            )
            if value is not None
        ]
        return sum(parts) if parts else None

    @staticmethod
    def _project_line(project: ContributionProject) -> str:
        name = safe_value(project.name, 80) if project.name else ""
        parts = [f"#{project.project_id}" + (f" {name}" if name else "")]
        if project.status and project.status != "PUBLISHED":
            parts.append(f"status: {project.status}")
        if project.tasks_mapped is None and project.tasks_validated is None:
            parts.append("no current tasks")
        else:
            parts.append(f"mapped: {project.tasks_mapped or 0}")
            parts.append(f"validated: {project.tasks_validated or 0}")
        return " | ".join(parts)

    def _body_lines(self) -> List[str]:
        lines: List[str] = []
        # Lead with the totals. Small models answer with the first figure they
        # read, so the "how many contributions" answer comes before hours.
        total = self.contributions_total
        if total is not None:
            lines.append(f"contributions_total_task_actions: {total}")
            breakdown = []
            if self.tasks_mapped is not None:
                breakdown.append(f"{self.tasks_mapped} mapped")
            if self.tasks_validated is not None:
                breakdown.append(f"{self.tasks_validated} validated")
            if self.tasks_invalidated is not None:
                breakdown.append(f"{self.tasks_invalidated} invalidated")
            if breakdown:
                lines.append(f"contributions_breakdown: {', '.join(breakdown)}")
        if self.tasks_mapped is not None:
            lines.append(f"tasks_mapped_all_time: {self.tasks_mapped}")
        if self.tasks_validated is not None:
            lines.append(f"tasks_validated_all_time: {self.tasks_validated}")
        if self.tasks_invalidated is not None:
            lines.append(f"tasks_invalidated_all_time: {self.tasks_invalidated}")
        if self.contributed_projects_total is not None:
            lines.append(
                f"contributed_projects_total: {self.contributed_projects_total}"
            )
        if self.projects_by_status:
            breakdown = ", ".join(
                f"{count} {label.lower()}" for label, count in self.projects_by_status
            )
            lines.append(f"contributed_projects_by_status: {breakdown}")
        if self.total_hours is not None:
            lines.append(f"total_contribution_hours_all_time: {self.total_hours}")
        if self.mapping_hours is not None:
            lines.append(f"mapping_hours_all_time: {self.mapping_hours}")
        if self.validation_hours is not None:
            lines.append(f"validation_hours_all_time: {self.validation_hours}")
        if self.countries_contributed is not None:
            lines.append(f"countries_contributed_to: {self.countries_contributed}")
        if self.months:
            recent = ", ".join(f"{month}: {count}" for month, count in self.months)
            lines.append(f"task_contributions_by_month: {recent}")
        if self.this_month is not None:
            month, count = self.this_month
            lines.append(f"contributions_this_month ({month}): {count}")
        if self.last_month is not None:
            month, count = self.last_month
            lines.append(f"contributions_last_month ({month}): {count}")
        if self.projects:
            cap = _max_projects()
            shown = self.projects if cap is None else self.projects[:cap]
            label = "contributed_projects"
            if (
                self.contributed_projects_total is not None
                and self.contributed_projects_total > len(shown)
            ):
                label += f" (showing {len(shown)} of {self.contributed_projects_total})"
            else:
                # A numbered, complete list: small models enumerate it reliably.
                label += f" (complete list, {len(shown)} items)"
            lines.append(label + ":")
            lines.extend(
                f"{position}. {self._project_line(project)}"
                for position, project in enumerate(shown, start=1)
            )
        elif self.contributed_projects_total == 0:
            lines.append("contributed_projects: none — no contributed projects yet")
        return lines


async def get_user_contribution_evidence(
    user_id: int, db: Any
) -> UserContributionEvidence:
    """Read-only lifetime + monthly contribution summary for the asker.

    The contributed-projects list comes from the backend's canonical
    ``users.projects_mapped`` array — the append-only record the backend writes
    when a user maps a project — not from current task state, so history stays
    visible after tasks are reset. Per-project mapped/validated counts merge in
    from the tasks query where the tasks still exist.
    """
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

        totals = dict(months)
        today = datetime.date.today()
        current_key = today.strftime("%Y-%m")
        previous_key = (today.replace(day=1) - datetime.timedelta(days=1)).strftime(
            "%Y-%m"
        )
        this_month = (current_key, totals.get(current_key, 0))
        last_month = (previous_key, totals.get(previous_key, 0))

        # Canonical contributed projects: the append-only array the backend
        # maintains (UserService.get_projects_mapped == users.projects_mapped).
        project_ids: List[int] = []
        array_ok = True
        try:
            project_ids = [
                int(pid)
                for pid in (await UserService.get_projects_mapped(user_id, db) or [])
                if pid is not None
            ]
        except Exception:
            array_ok = False
            logger.exception(f"user {user_id} mapped-projects array fetch failed")

        # Per-project counts from current tasks, keyed by project id.
        counts: Dict[int, Tuple[int, int]] = {}
        try:
            dto = await UserModel.get_mapped_projects(user_id, _PREFERRED_LOCALE, db)
            for row in _attr(dto, "mapped_projects") or []:
                pid = _attr(row, "project_id")
                if pid is not None:
                    counts[int(pid)] = (
                        _int_or_zero(_attr(row, "tasks_mapped")),
                        _int_or_zero(_attr(row, "tasks_validated")),
                    )
        except Exception:
            logger.exception(f"user {user_id} project count fetch failed")

        projects: List[ContributionProject] = []
        status_counts: Counter = Counter()
        projects_total: Optional[int] = None
        if not array_ok:
            projects_total = None
        elif not project_ids:
            projects_total = 0
        else:
            try:
                rows = await db.fetch_all(
                    query="""
                        SELECT p.id, p.status,
                               COALESCE(pi_locale.name, pi_default.name) AS name
                        FROM projects p
                        LEFT JOIN project_info pi_locale
                            ON pi_locale.project_id = p.id
                            AND pi_locale.locale = :locale
                        LEFT JOIN project_info pi_default
                            ON pi_default.project_id = p.id
                            AND pi_default.locale = p.default_locale
                        WHERE p.id = ANY(:project_ids)
                        ORDER BY p.id DESC
                    """,
                    values={"project_ids": project_ids, "locale": _PREFERRED_LOCALE},
                )
                for row in rows or []:
                    pid = _attr(row, "id")
                    if pid is None:
                        continue
                    mapped, validated = counts.get(int(pid), (None, None))
                    status = _status_label(_attr(row, "status"))
                    if status:
                        status_counts[status] += 1
                    projects.append(
                        ContributionProject(
                            project_id=int(pid),
                            name=_attr(row, "name"),
                            status=status,
                            tasks_mapped=mapped,
                            tasks_validated=validated,
                        )
                    )
                projects_total = len(projects)
            except Exception:
                logger.exception(
                    f"user {user_id} contributed-project list fetch failed"
                )

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
            contributed_projects_total=projects_total,
            projects_by_status=tuple(
                (label, status_counts[label])
                for label in _STATUS_ORDER
                if status_counts.get(label)
            ),
            countries_contributed=_attr(countries, "total"),
            months=months,
            this_month=this_month,
            last_month=last_month,
            projects=tuple(projects),
        )
    except Exception:
        logger.exception(f"user {user_id} contribution fetch failed")
        return UserContributionEvidence(status="UNAVAILABLE", user_id=user_id)
