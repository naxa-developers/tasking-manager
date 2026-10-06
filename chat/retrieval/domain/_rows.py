"""Shared row/DTO read helpers for the domain evidence modules."""

from __future__ import annotations

from typing import Any


def _attr(obj: Any, name: str) -> Any:
    """Read a field off a DTO/ORM object or mapping; None when absent."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)
