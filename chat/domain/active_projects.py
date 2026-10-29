from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from loguru import logger

from chat.domain._rows import _attr
from chat.domain.evidence import DomainStatus, EvidenceBase, safe_value

ACTIVE_OPERATION = "get_active_projects"
ACTIVE_PROVENANCE = "ProjectService.get_active_projects"
ACTIVE_INTERVAL_HOURS = 24
_MAX_ACTIVE = 8


@dataclass(frozen=True)
class ActiveProjectEntry:
    project_id: int
    name: Optional[str] = None
    mapping_types: Optional[str] = None


@dataclass(frozen=True)
class ActiveProjectsEvidence(EvidenceBase):
    """Projects with task activity in the last 24 hours."""

    status: DomainStatus
    user_id: int
    operation: str = ACTIVE_OPERATION
    active_total: Optional[int] = None
    projects: Tuple[ActiveProjectEntry, ...] = ()
    provenance: str = ACTIVE_PROVENANCE

    _CONTEXT_FIELD = "user_id"
    _CITATION_SCOPE = "global"
    _CITATION_KIND = "active_projects"
    _CITATION_TITLE = "Tasking Manager active projects"
    _CITATION_HEADING = "active_projects"
    _CITATION_SOURCE = {
        "path": "backend/services/project_service.py",
        "symbol": "ProjectService.get_active_projects",
    }
    _CITATION_ID_TEMPLATE = "tm:global:{kind}"
    _CITATION_DOC_TEMPLATE = "tasking_manager:global"

    def _scope_id(self) -> Any:
        return "tm"

    def _body_lines(self) -> List[str]:
        if not self.projects:
            return [f"active_projects (last {ACTIVE_INTERVAL_HOURS}h): none"]
        shown = self.projects[:_MAX_ACTIVE]
        label = f"active_projects (last {ACTIVE_INTERVAL_HOURS}h)"
        if self.active_total is not None and self.active_total > len(shown):
            label += f" (showing {len(shown)} of {self.active_total})"
        else:
            label += f" (complete list, {len(shown)} items)"
        lines = [label + ":"]
        for position, entry in enumerate(shown, start=1):
            name = safe_value(entry.name, 80) if entry.name else ""
            line = f"{position}. #{entry.project_id}" + (f" {name}" if name else "")
            if entry.mapping_types:
                line += f" | mapping types: {safe_value(entry.mapping_types, 60)}"
            lines.append(line)
        return lines


async def get_active_projects_evidence(user_id: int, db: Any) -> ActiveProjectsEvidence:
    """Read-only active-projects list (last 24h of task activity)."""
    from backend.services.project_service import ProjectService

    try:
        collection = await ProjectService.get_active_projects(ACTIVE_INTERVAL_HOURS, db)
    except Exception:
        logger.exception("active projects fetch failed")
        return ActiveProjectsEvidence(status="UNAVAILABLE", user_id=user_id)

    features = _attr(collection, "features")
    if features is None and isinstance(collection, dict):
        features = collection.get("features")
    rows: List[Tuple[int, Optional[str]]] = []
    for feature in features or []:
        props = _attr(feature, "properties")
        if isinstance(feature, dict):
            props = feature.get("properties")
        pid = _attr(props, "project_id") if props is not None else None
        if pid is None:
            continue
        rows.append((int(pid), _attr(props, "mapping_types")))

    total = len(rows)
    rows = rows[:_MAX_ACTIVE]

    names = {}
    if rows:
        try:
            name_rows = await db.fetch_all(
                query="""
                    SELECT p.id,
                           COALESCE(pi_locale.name, pi_default.name) AS name
                    FROM projects p
                    LEFT JOIN project_info pi_locale
                        ON pi_locale.project_id = p.id AND pi_locale.locale = :locale
                    LEFT JOIN project_info pi_default
                        ON pi_default.project_id = p.id
                        AND pi_default.locale = p.default_locale
                    WHERE p.id = ANY(:project_ids)
                """,
                values={"project_ids": [pid for pid, _ in rows], "locale": "en"},
            )
            names = {
                int(_attr(row, "id")): _attr(row, "name")
                for row in name_rows or []
                if _attr(row, "id") is not None
            }
        except Exception:
            logger.exception("active projects name lookup failed")

    entries = tuple(
        ActiveProjectEntry(
            project_id=pid,
            name=names.get(pid),
            mapping_types=_mapping_types_text(mapping_types),
        )
        for pid, mapping_types in rows
    )
    return ActiveProjectsEvidence(
        status="OK", user_id=user_id, active_total=total, projects=entries
    )


def _mapping_types_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value if item)
    return str(value)
