from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from loguru import logger

from chat.domain._rows import _attr
from chat.domain.evidence import DomainStatus, EvidenceBase, safe_value

INTERESTS_OPERATION = "get_user_interests"
INTERESTS_PROVENANCE = (
    "InterestService.compute_contributions_rate + InterestService.get_all_interests"
)

_MAX_RATES = 10
_MAX_INTERESTS = 20


@dataclass(frozen=True)
class UserInterestsEvidence(EvidenceBase):
    """The asker's interest mix, weighted by their contributed projects.

    Mirrors the interests endpoints: ``compute_contributions_rate`` gives each
    interest's share of the asker's contributed projects,
    ``get_all_interests`` the interest catalog.
    """

    status: DomainStatus
    user_id: int
    operation: str = INTERESTS_OPERATION
    rates: Tuple[Tuple[str, float], ...] = ()
    interests_total: Optional[int] = None
    interests: Tuple[str, ...] = ()
    provenance: str = INTERESTS_PROVENANCE

    _CONTEXT_FIELD = "user_id"
    _CITATION_SCOPE = "user"
    _CITATION_KIND = "interests"
    _CITATION_TITLE = "User {id} interests"
    _CITATION_HEADING = "user_interests"
    _CITATION_SOURCE = {
        "path": "backend/services/interests_service.py",
        "symbol": "InterestService.compute_contributions_rate",
    }

    def _scope_id(self) -> Any:
        return self.user_id

    def _body_lines(self) -> List[str]:
        lines: List[str] = []
        if self.rates:
            shown = self.rates[:_MAX_RATES]
            label = "interest_rates"
            if len(self.rates) > len(shown):
                label += f" (top {len(shown)} of {len(self.rates)})"
            else:
                label += f" (complete list, {len(shown)} items)"
            lines.append(label + ":")
            lines.extend(
                f"{position}. {safe_value(name, 64)}: {rate}"
                for position, (name, rate) in enumerate(shown, start=1)
            )
        if self.interests:
            shown = self.interests[:_MAX_INTERESTS]
            label = "interests"
            if self.interests_total is not None and self.interests_total > len(shown):
                label += f" (showing {len(shown)} of {self.interests_total})"
            else:
                label += f" (complete list, {len(shown)} items)"
            lines.append(label + ":")
            lines.extend(
                f"{position}. {safe_value(name, 64)}"
                for position, name in enumerate(shown, start=1)
            )
        elif self.interests_total == 0:
            lines.append("interests: none")
        return lines


async def get_user_interests_evidence(user_id: int, db: Any) -> UserInterestsEvidence:
    """Read-only interest mix for the asker (their own data, no gate)."""
    from backend.services.interests_service import InterestService

    try:
        dto = await InterestService.compute_contributions_rate(user_id, db)
        rates = tuple(
            (str(_attr(row, "name")), round(float(_attr(row, "rate") or 0.0), 3))
            for row in (_attr(dto, "rates") or [])
            if _attr(row, "name")
        )
    except Exception:
        logger.exception(f"user {user_id} interest rates fetch failed")
        return UserInterestsEvidence(status="UNAVAILABLE", user_id=user_id)

    interests: Tuple[str, ...] = ()
    interests_ok = False
    try:
        all_dto = await InterestService.get_all_interests(db)
        interests = tuple(
            str(_attr(row, "name"))
            for row in (_attr(all_dto, "interests") or [])
            if _attr(row, "name")
        )
        interests_ok = True
    except Exception:
        logger.exception(f"user {user_id} interests catalog fetch failed")

    return UserInterestsEvidence(
        status="OK",
        user_id=user_id,
        rates=rates,
        interests=interests,
        interests_total=len(interests) if interests_ok else None,
    )
