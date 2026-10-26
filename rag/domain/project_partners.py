from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from loguru import logger

from rag.domain._rows import _attr, _iso_day
from rag.domain.auth import authorize_project
from rag.domain.evidence import DomainStatus, EvidenceBase, safe_value

PARTNERS_OPERATION = "get_project_partners"
PARTNERS_PROVENANCE = (
    "ProjectPartnershipService.get_partnerships_by_project"
    " + PartnerService.get_partner_by_id"
)

_MAX_PARTNERS = 20


@dataclass(frozen=True)
class PartnerEntry:
    partner_id: Optional[int]
    name: Optional[str] = None
    started_on: str = ""
    ended_on: str = ""


@dataclass(frozen=True)
class ProjectPartnersEvidence(EvidenceBase):
    """Partnerships recorded on one project.

    Mirrors the partners endpoints: ``get_partnerships_by_project`` for the
    links plus ``get_partner_by_id`` to resolve partner names. The by-id
    partnership endpoint returns the same fields.
    """

    status: DomainStatus
    project_id: int
    operation: str = PARTNERS_OPERATION
    partners_total: Optional[int] = None
    partners: Tuple[PartnerEntry, ...] = ()
    provenance: str = PARTNERS_PROVENANCE

    _CITATION_KIND = "partners"
    _CITATION_TITLE = "Project {id} partners"
    _CITATION_HEADING = "project_partners"
    _CITATION_SOURCE = {
        "path": "backend/services/project_partnership_service.py",
        "symbol": "ProjectPartnershipService.get_partnerships_by_project",
    }

    def _scope_id(self) -> Any:
        return self.project_id

    def _body_lines(self) -> List[str]:
        lines: List[str] = []
        if self.partners:
            shown = self.partners[:_MAX_PARTNERS]
            label = "project_partners"
            if self.partners_total is not None and self.partners_total > len(shown):
                label += f" (showing {len(shown)} of {self.partners_total})"
            else:
                label += f" (complete list, {len(shown)} items)"
            lines.append(label + ":")
            for position, entry in enumerate(shown, start=1):
                name = safe_value(entry.name, 80) if entry.name else ""
                head = f"#{entry.partner_id}" + (f" {name}" if name else "")
                parts = [head]
                if entry.started_on:
                    parts.append(f"started: {entry.started_on}")
                if entry.ended_on:
                    parts.append(f"ended: {entry.ended_on}")
                lines.append(f"{position}. " + " | ".join(parts))
        elif self.partners_total == 0:
            lines.append("project_partners: none")
        return lines


async def get_project_partners_evidence(
    user_id: int, project_id: int, db: Any
) -> ProjectPartnersEvidence:
    """Authorized read-only partnerships list for one project."""
    status, _project = await authorize_project(user_id, project_id, db)
    if status != "OK":
        return ProjectPartnersEvidence(status=status, project_id=project_id)

    from backend.services.partner_service import PartnerService
    from backend.services.project_partnership_service import (
        ProjectPartnershipService,
    )

    try:
        rows = await ProjectPartnershipService.get_partnerships_by_project(
            project_id, db
        )
    except Exception:
        logger.exception(f"project {project_id} partnerships fetch failed")
        return ProjectPartnersEvidence(status="UNAVAILABLE", project_id=project_id)

    entries: List[PartnerEntry] = []
    for row in rows or []:
        partner_id = _attr(row, "partner_id")
        name: Optional[str] = None
        if partner_id is not None:
            try:
                partner = await PartnerService.get_partner_by_id(partner_id, db)
                name = _attr(partner, "name")
            except Exception:
                name = None
        entries.append(
            PartnerEntry(
                partner_id=partner_id,
                name=name,
                started_on=_iso_day(_attr(row, "started_on")),
                ended_on=_iso_day(_attr(row, "ended_on")),
            )
        )

    return ProjectPartnersEvidence(
        status="OK",
        project_id=project_id,
        partners_total=len(entries),
        partners=tuple(entries),
    )
