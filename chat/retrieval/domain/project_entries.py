from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence

from chat.retrieval.domain.evidence import safe_value

_MAX_RENDERED = 8


def _attr(obj: Any, name: str) -> Any:
    """Read a field off a DTO/ORM object or mapping; None when absent."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value if v)
    return str(value)


def _day(value: Any) -> str:
    if isinstance(value, datetime.datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, datetime.date):
        return value.strftime("%Y-%m-%d")
    return ""


@dataclass(frozen=True)
class ProjectEntry:
    """Small allowlisted project slice for list-style evidence."""

    project_id: Optional[int]
    name: Optional[str] = None
    status: Optional[str] = None
    difficulty: Optional[str] = None
    organisation: Optional[str] = None
    country: str = ""
    percent_mapped: Optional[int] = None
    percent_validated: Optional[int] = None
    active_mappers: Optional[int] = None
    due_date: str = ""
    campaigns: str = ""


def entry_from_dto(dto: Any) -> ProjectEntry:
    campaigns = _attr(dto, "campaigns")
    campaign_names = ""
    if campaigns:
        names = [
            str(_attr(campaign, "name"))
            for campaign in campaigns
            if _attr(campaign, "name")
        ]
        campaign_names = ", ".join(names)
    return ProjectEntry(
        project_id=_attr(dto, "project_id"),
        name=_attr(dto, "name"),
        status=_attr(dto, "status"),
        difficulty=_attr(dto, "difficulty"),
        organisation=_attr(dto, "organisation_name"),
        country=_text(_attr(dto, "country")),
        percent_mapped=_attr(dto, "percent_mapped"),
        percent_validated=_attr(dto, "percent_validated"),
        active_mappers=_attr(dto, "active_mappers"),
        due_date=_day(_attr(dto, "due_date")),
        campaigns=campaign_names,
    )


def render_project_entries(
    entries: Sequence[ProjectEntry], limit: int = _MAX_RENDERED
) -> List[str]:
    """One compact line per project; newest/ranked order is preserved."""
    lines: List[str] = []
    for entry in list(entries)[:limit]:
        if not entry.project_id:
            continue
        name = safe_value(entry.name, 80) if entry.name else ""
        label = f"#{entry.project_id}" + (f" {name}" if name else "")
        parts = [label]
        if entry.status:
            parts.append(f"status: {safe_value(entry.status, 32)}")
        if entry.difficulty:
            parts.append(f"difficulty: {safe_value(entry.difficulty, 32)}")
        if entry.organisation:
            parts.append(f"organisation: {safe_value(entry.organisation, 80)}")
        if entry.country:
            parts.append(f"country: {safe_value(entry.country, 80)}")
        if entry.percent_mapped is not None:
            parts.append(f"mapped: {entry.percent_mapped}%")
        if entry.percent_validated is not None:
            parts.append(f"validated: {entry.percent_validated}%")
        if entry.active_mappers is not None:
            parts.append(f"active mappers: {entry.active_mappers}")
        if entry.campaigns:
            parts.append(f"campaigns: {safe_value(entry.campaigns, 80)}")
        if entry.due_date:
            parts.append(f"due: {entry.due_date}")
        lines.append("- " + " | ".join(parts))
    return lines


def filters_summary(filters: Optional[dict]) -> str:
    """Human-readable filter line for evidence blocks; empty when no filters."""
    if not filters:
        return ""
    parts = []
    for key in sorted(filters):
        value = filters[key]
        if value:
            parts.append(f"{key}={safe_value(value, 80)}")
    return ", ".join(parts)
