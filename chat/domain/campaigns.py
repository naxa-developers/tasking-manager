from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from loguru import logger

from chat.domain._rows import _attr
from chat.domain.auth import authorize_project
from chat.domain.evidence import DomainStatus, EvidenceBase, safe_value

CAMPAIGNS_OPERATION = "get_campaigns"
CAMPAIGNS_PROVENANCE = (
    "CampaignService.get_project_campaigns_as_dto / CampaignService.get_all_campaigns"
)

# Per-op prompt-size guard for the campaign list.
_MAX_CAMPAIGNS = 20


@dataclass(frozen=True)
class CampaignEntry:
    campaign_id: Optional[int]
    name: Optional[str] = None


@dataclass(frozen=True)
class CampaignsEvidence(EvidenceBase):
    """Campaigns: those linked to one project, or the site-wide list.

    Mirrors ``CampaignService.get_project_campaigns_as_dto`` when the question
    names a project and ``CampaignService.get_all_campaigns`` otherwise. The
    by-id detail endpoint needs a campaign id the route does not carry.
    """

    status: DomainStatus
    project_id: Optional[int] = None
    operation: str = CAMPAIGNS_OPERATION
    campaigns_total: Optional[int] = None
    campaigns: Tuple[CampaignEntry, ...] = ()
    provenance: str = CAMPAIGNS_PROVENANCE

    _CITATION_KIND = "campaigns"
    _CITATION_TITLE = "Campaigns"
    _CITATION_HEADING = "campaigns"
    _CITATION_SOURCE = {
        "path": "backend/services/campaign_service.py",
        "symbol": "CampaignService.get_all_campaigns",
    }

    def _scope_id(self) -> Any:
        return self.project_id if self.project_id is not None else "tm"

    def _label(self) -> str:
        return "project_campaigns" if self.project_id is not None else "campaigns"

    def _body_lines(self) -> List[str]:
        label = self._label()
        lines: List[str] = []
        if self.campaigns:
            shown = self.campaigns[:_MAX_CAMPAIGNS]
            header = label
            if self.campaigns_total is not None and self.campaigns_total > len(shown):
                header += f" (showing {len(shown)} of {self.campaigns_total})"
            else:
                header += f" (complete list, {len(shown)} items)"
            lines.append(header + ":")
            for position, campaign in enumerate(shown, start=1):
                name = safe_value(campaign.name, 80) if campaign.name else ""
                line = f"{position}. #{campaign.campaign_id}"
                if name:
                    line += f" {name}"
                lines.append(line)
        elif self.campaigns_total == 0:
            lines.append(f"{label}: none")
        return lines


async def get_campaigns_evidence(
    user_id: int, project_id: Optional[int], db: Any
) -> CampaignsEvidence:
    """Read-only campaign summary: project-scoped or site-wide."""
    from backend.services.campaign_service import CampaignService

    if project_id is not None:
        status, _project = await authorize_project(user_id, project_id, db)
        if status != "OK":
            return CampaignsEvidence(status=status, project_id=project_id)

    try:
        if project_id is not None:
            dto = await CampaignService.get_project_campaigns_as_dto(project_id, db)
        else:
            dto = await CampaignService.get_all_campaigns(db)
    except Exception:
        logger.exception("campaigns fetch failed")
        return CampaignsEvidence(status="UNAVAILABLE", project_id=project_id)

    campaigns = tuple(
        CampaignEntry(campaign_id=_attr(row, "id"), name=_attr(row, "name"))
        for row in (_attr(dto, "campaigns") or [])
        if _attr(row, "id") is not None
    )
    return CampaignsEvidence(
        status="OK",
        project_id=project_id,
        campaigns_total=len(campaigns),
        campaigns=campaigns,
    )
