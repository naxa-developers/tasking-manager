"""Shared row/DTO read helpers for the domain evidence modules."""

from __future__ import annotations

import datetime
from typing import Any, List, Optional, Tuple


def _attr(obj: Any, name: str) -> Any:
    """Read a field off a DTO/ORM object or mapping; None when absent."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _int_or_none(value: Any) -> Optional[int]:
    """``int(value)`` or None; never raises."""
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _int_or_zero(value: Any) -> int:
    """``int(value)`` defaulting to 0; never raises."""
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0


def _iso_day(value: Any) -> str:
    """``YYYY-MM-DD`` for a date/datetime, else empty string."""
    if isinstance(value, datetime.date):
        return value.strftime("%Y-%m-%d")
    return ""


def _names(rows: Any, limit: Optional[int] = None) -> Tuple[str, ...]:
    """Non-empty ``name`` values from DTO/dict rows, optionally capped."""
    names: List[str] = []
    for row in rows or []:
        name = _attr(row, "name")
        if name:
            names.append(str(name))
        if limit is not None and len(names) >= limit:
            break
    return tuple(names)
