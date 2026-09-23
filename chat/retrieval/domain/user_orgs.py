from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from loguru import logger

from chat.retrieval.domain.evidence import DomainStatus, EvidenceBase, safe_value
from chat.retrieval.domain.project_entries import (
    ProjectEntry,
    entry_from_dto,
    render_project_entries,
)

ORG_PROJECTS_OPERATION = "get_user_org_projects"
ORG_PROJECTS_PROVENANCE = (
    "Organisation.get_organisations_managed_by_user + "
    "ProjectSearchService.search_projects"
)

_MAX_ORGS = 3
_MAX_PROJECTS_PER_ORG = 5


def _attr(obj: Any, name: str) -> Any:
    """Read a field off a DTO/ORM object or mapping; None when absent."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


@dataclass(frozen=True)
class OrgProjectGroup:
    organisation: str
    total_projects: Optional[int] = None
    projects: Tuple[ProjectEntry, ...] = ()


@dataclass(frozen=True)
class UserOrgProjectsEvidence(EvidenceBase):
    """Projects running under the organisations the asker manages."""

    status: DomainStatus
    user_id: int
    operation: str = ORG_PROJECTS_OPERATION
    groups: Tuple[OrgProjectGroup, ...] = ()
    provenance: str = ORG_PROJECTS_PROVENANCE

    _CONTEXT_FIELD = "user_id"
    _CITATION_SCOPE = "user"
    _CITATION_KIND = "org_projects"
    _CITATION_TITLE = "Projects run by user {id}'s organisations"
    _CITATION_HEADING = "user_org_projects"
    _CITATION_SOURCE = {
        "path": "backend/services/organisation_service.py",
        "symbol": "OrganisationService.get_organisations_managed_by_user",
    }

    def _scope_id(self) -> Any:
        return self.user_id

    def _body_lines(self) -> List[str]:
        if not self.groups:
            return [
                "organisations_managed_by_you: none (the asker does not manage any organisation)",
                "projects_running_by_your_organisations: none",
            ]
        lines = [f"organisations_managed_by_you: {len(self.groups)}"]
        for group in self.groups[:_MAX_ORGS]:
            name = safe_value(group.organisation, 80)
            total = (
                group.total_projects
                if group.total_projects is not None
                else len(group.projects)
            )
            lines.append(
                f"organisation: {name} | projects_running_by_this_organisation: {total}"
            )
            lines.extend(
                render_project_entries(group.projects, limit=_MAX_PROJECTS_PER_ORG)
            )
        return lines


async def get_user_org_projects_evidence(
    user_id: int, db: Any
) -> UserOrgProjectsEvidence:
    """Read-only listing of the asker's managed-organisation projects."""
    try:
        from backend.models.postgis.organisation import Organisation
        from backend.models.postgis.user import User as UserModel

        user = await UserModel.get_by_id(user_id, db)
        if user is None:
            return UserOrgProjectsEvidence(status="NOT_FOUND", user_id=user_id)

        orgs = await Organisation.get_organisations_managed_by_user(user_id, db)
        names: List[str] = []
        for org in orgs or []:
            name = _attr(org, "name")
            if name and str(name) not in names:
                names.append(str(name))
        names = names[:_MAX_ORGS]
        if not names:
            return UserOrgProjectsEvidence(status="OK", user_id=user_id, groups=())

        from backend.models.dtos.project_dto import ProjectSearchDTO
        from backend.services.project_search_service import ProjectSearchService

        groups: List[OrgProjectGroup] = []
        for name in names:
            try:
                search = ProjectSearchDTO(
                    preferred_locale="en",
                    page=1,
                    omit_map_results=True,
                    organisation_name=name,
                )
                results = await ProjectSearchService.search_projects(search, user, db)
                total = _attr(_attr(results, "pagination"), "total")
                entries = tuple(
                    entry_from_dto(dto)
                    for dto in (_attr(results, "results") or [])[:_MAX_PROJECTS_PER_ORG]
                )
                groups.append(
                    OrgProjectGroup(
                        organisation=name,
                        total_projects=(
                            int(total) if total is not None else len(entries)
                        ),
                        projects=entries,
                    )
                )
            except Exception as exc:
                from backend.exceptions import NotFound

                if not isinstance(exc, NotFound):
                    logger.exception(f"organisation {name!r} project search failed")
                groups.append(OrgProjectGroup(organisation=name, total_projects=0))
        return UserOrgProjectsEvidence(
            status="OK", user_id=user_id, groups=tuple(groups)
        )
    except Exception:
        logger.exception(f"user {user_id} organisation projects fetch failed")
        return UserOrgProjectsEvidence(status="UNAVAILABLE", user_id=user_id)
