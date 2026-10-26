from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from loguru import logger

from rag.domain._rows import _attr, _int_or_zero, _iso_day
from rag.domain.auth import authorize_project
from rag.domain.evidence import DomainStatus, EvidenceBase, safe_value

CONTRIBUTIONS_OPERATION = "get_project_contributions"
CONTRIBUTIONS_PROVENANCE = (
    "StatsService.get_user_contributions + ProjectService.get_contribs_by_day"
)

# Per-op prompt-size guards: the headline is the top contributors by total
# tasks (the backend orders them that way); days render newest-first.
_MAX_CONTRIBUTORS = 20
_MAX_DAYS = 14


@dataclass(frozen=True)
class Contributor:
    username: str
    mapped: int = 0
    validated: int = 0
    bad_imagery: int = 0
    total: int = 0


@dataclass(frozen=True)
class ContributionDay:
    date: str
    mapped: int = 0
    validated: int = 0


@dataclass(frozen=True)
class ProjectContributionsEvidence(EvidenceBase):
    """Contributors to one project plus per-day contribution increments.

    Mirrors the contribution endpoints: per-user totals from
    ``get_user_contributions`` (top contributors first, as the backend orders
    them) and per-day mapped/validated increments from ``get_contribs_by_day``.
    The asker's own row is singled out when they contributed.
    """

    status: DomainStatus
    project_id: int
    operation: str = CONTRIBUTIONS_OPERATION
    contributors_total: Optional[int] = None
    contributors: Tuple[Contributor, ...] = ()
    days_total: Optional[int] = None
    days: Tuple[ContributionDay, ...] = ()
    you: Optional[Contributor] = None
    you_contributed: Optional[bool] = None
    provenance: str = CONTRIBUTIONS_PROVENANCE

    _CITATION_KIND = "contributions"
    _CITATION_TITLE = "Project {id} contributors"
    _CITATION_HEADING = "project_contributors"
    _CITATION_SOURCE = {
        "path": "backend/services/stats_service.py",
        "symbol": "StatsService.get_user_contributions",
    }

    def _scope_id(self) -> Any:
        return self.project_id

    @staticmethod
    def _counts_line(row: Contributor) -> str:
        parts = [f"mapped: {row.mapped}", f"validated: {row.validated}"]
        if row.bad_imagery:
            parts.append(f"bad_imagery: {row.bad_imagery}")
        return " | ".join(parts)

    def _body_lines(self) -> List[str]:
        lines: List[str] = []
        if self.contributors:
            shown = self.contributors[:_MAX_CONTRIBUTORS]
            label = "contributors"
            if self.contributors_total is not None and self.contributors_total > len(
                shown
            ):
                label += (
                    f" (top {len(shown)} of {self.contributors_total}, by total tasks)"
                )
            else:
                label += f" (complete list, {len(shown)} items)"
            lines.append(label + ":")
            lines.extend(
                f"{position}. {safe_value(row.username, 64)} | {self._counts_line(row)}"
                for position, row in enumerate(shown, start=1)
            )
        elif self.contributors_total == 0:
            lines.append("contributors: none yet")
        if self.you is not None:
            lines.append(
                "your_contributions_on_this_project: " + self._counts_line(self.you)
            )
        elif self.you_contributed is False:
            lines.append("your_contributions_on_this_project: none yet")
        if self.days:
            shown_days = list(reversed(self.days[-_MAX_DAYS:]))
            label = "contributions_by_day"
            if self.days_total is not None and self.days_total > len(shown_days):
                label += f" (last {len(shown_days)} of {self.days_total} days)"
            else:
                label += f" (complete list, {len(shown_days)} days)"
            lines.append(label + ":")
            lines.extend(
                f"{day.date} | mapped: {day.mapped} | validated: {day.validated}"
                for day in shown_days
            )
        return lines


async def get_project_contributions_evidence(
    user_id: int, project_id: int, db: Any
) -> ProjectContributionsEvidence:
    """Authorized read-only contributor summary for one project."""
    status, _project = await authorize_project(user_id, project_id, db)
    if status != "OK":
        return ProjectContributionsEvidence(status=status, project_id=project_id)

    from backend.models.postgis.user import User as UserModel
    from backend.services.project_service import ProjectService
    from backend.services.stats_service import StatsService

    contributors: List[Contributor] = []
    try:
        dto = await StatsService.get_user_contributions(project_id, db)
        for row in _attr(dto, "user_contributions") or []:
            username = _attr(row, "username")
            if not username:
                continue
            contributors.append(
                Contributor(
                    username=str(username),
                    mapped=_int_or_zero(_attr(row, "mapped")),
                    validated=_int_or_zero(_attr(row, "validated")),
                    bad_imagery=_int_or_zero(_attr(row, "bad_imagery")),
                    total=_int_or_zero(_attr(row, "total")),
                )
            )
    except Exception:
        logger.exception(f"project {project_id} contributors fetch failed")
        return ProjectContributionsEvidence(status="UNAVAILABLE", project_id=project_id)

    days: List[ContributionDay] = []
    try:
        day_dto = await ProjectService.get_contribs_by_day(project_id, db)
        for row in _attr(day_dto, "stats") or []:
            day = _iso_day(_attr(row, "date"))
            if not day:
                continue
            days.append(
                ContributionDay(
                    date=day,
                    mapped=_int_or_zero(_attr(row, "mapped")),
                    validated=_int_or_zero(_attr(row, "validated")),
                )
            )
    except Exception:
        logger.exception(f"project {project_id} by-day contributions failed")

    you: Optional[Contributor] = None
    you_contributed: Optional[bool] = None
    try:
        user = await UserModel.get_by_id(user_id, db)
        username = _attr(user, "username")
        if username:
            target = str(username).casefold()
            you = next(
                (c for c in contributors if c.username.casefold() == target), None
            )
            you_contributed = you is not None
    except Exception:
        logger.exception(f"project {project_id} asker lookup failed")

    return ProjectContributionsEvidence(
        status="OK",
        project_id=project_id,
        contributors_total=len(contributors),
        contributors=tuple(contributors),
        days_total=len(days),
        days=tuple(days),
        you=you,
        you_contributed=you_contributed,
    )
