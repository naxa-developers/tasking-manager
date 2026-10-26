from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from loguru import logger

from rag.domain._rows import _attr
from rag.domain.evidence import DomainStatus, EvidenceBase, safe_value

ORG_OPERATION = "get_organisation_info"
ORG_PROVENANCE = "OrganisationService.get_organisation_by_name + get_organisation_stats"

_MAX_CAMPAIGNS = 10
_MAX_DESCRIPTION = 200


@dataclass(frozen=True)
class OrganisationInfoEvidence(EvidenceBase):
    """One organisation's public profile plus project stats and campaigns.

    Mirrors the organisation endpoints: name lookup
    (``get_organisation_by_name``), the organisation DTO, the statistics
    endpoint (draft/published/archived project counts) and the organisation
    campaigns list. The name comes from the route's ``organisation`` filter.
    """

    status: DomainStatus
    organisation_name: str
    operation: str = ORG_OPERATION
    organisation_id: Optional[int] = None
    slug: Optional[str] = None
    url: Optional[str] = None
    description: Optional[str] = None
    projects_published: Optional[int] = None
    projects_draft: Optional[int] = None
    projects_archived: Optional[int] = None
    campaigns: Tuple[str, ...] = ()
    provenance: str = ORG_PROVENANCE

    _CONTEXT_FIELD = "organisation_name"
    _CITATION_SCOPE = "organisation"
    _CITATION_KIND = "info"
    _CITATION_TITLE = "Organisation {id}"
    _CITATION_HEADING = "organisation_info"
    _CITATION_SOURCE = {
        "path": "backend/services/organisation_service.py",
        "symbol": "OrganisationService.get_organisation_by_name",
    }

    def _scope_id(self) -> Any:
        return (
            self.organisation_id
            if self.organisation_id is not None
            else (self.organisation_name)
        )

    def _body_lines(self) -> List[str]:
        lines: List[str] = []
        if self.organisation_id is not None:
            lines.append(f"organisation_id: {self.organisation_id}")
        if self.slug:
            lines.append(f"slug: {safe_value(self.slug, 64)}")
        if self.url:
            lines.append(f"url: {safe_value(self.url, 120)}")
        if self.description:
            lines.append(
                f"description: {safe_value(self.description, _MAX_DESCRIPTION)}"
            )
        if self.projects_published is not None:
            parts = [f"{self.projects_published} published"]
            if self.projects_draft is not None:
                parts.append(f"{self.projects_draft} draft")
            if self.projects_archived is not None:
                parts.append(f"{self.projects_archived} archived")
            lines.append("organisation_projects: " + ", ".join(parts))
        if self.campaigns:
            shown = self.campaigns[:_MAX_CAMPAIGNS]
            lines.append(
                "organisation_campaigns: "
                + ", ".join(safe_value(name, 80) for name in shown)
            )
        return lines


async def get_organisation_info_evidence(
    user_id: int, project_id: Any, db: Any, filters: Optional[dict] = None
) -> OrganisationInfoEvidence:
    """Read-only organisation profile for the route's ``organisation`` filter."""
    name = str((filters or {}).get("organisation") or "").strip()
    if not name:
        return OrganisationInfoEvidence(status="NOT_FOUND", organisation_name="")

    from backend.exceptions import NotFound
    from backend.services.organisation_service import OrganisationService

    try:
        org = await OrganisationService.get_organisation_by_name(name, db)
        org_id = _attr(org, "id")
        dto = await OrganisationService.get_organisation_by_id_as_dto(
            org_id, user_id, True, db
        )
    except NotFound:
        return OrganisationInfoEvidence(status="NOT_FOUND", organisation_name=name)
    except Exception:
        logger.exception(f"organisation {name!r} lookup failed")
        return OrganisationInfoEvidence(status="UNAVAILABLE", organisation_name=name)

    projects_published = projects_draft = projects_archived = None
    try:
        stats = await OrganisationService.get_organisation_stats(org_id, db)
        projects = _attr(stats, "projects")
        projects_published = _attr(projects, "published")
        projects_draft = _attr(projects, "draft")
        projects_archived = _attr(projects, "archived")
    except Exception:
        logger.exception(f"organisation {name!r} stats lookup failed")

    campaigns: Tuple[str, ...] = ()
    try:
        from backend.services.campaign_service import CampaignService

        campaign_dto = await CampaignService.get_organisation_campaigns_as_dto(
            org_id, db
        )
        campaigns = tuple(
            str(_attr(row, "name"))
            for row in (_attr(campaign_dto, "campaigns") or [])
            if _attr(row, "name")
        )
    except Exception:
        logger.exception(f"organisation {name!r} campaigns lookup failed")

    return OrganisationInfoEvidence(
        status="OK",
        organisation_name=str(_attr(dto, "name") or name),
        organisation_id=_attr(dto, "organisation_id") or org_id,
        slug=_attr(dto, "slug"),
        url=_attr(dto, "url"),
        description=_attr(dto, "description"),
        projects_published=projects_published,
        projects_draft=projects_draft,
        projects_archived=projects_archived,
        campaigns=campaigns,
    )
