"""Env parsing helpers — one place for getenv/convert/fallback."""

from __future__ import annotations

import os
from typing import Optional


def env_int(name: str, default: int) -> int:
    """Integer env value, falling back to ``default`` (never raises)."""
    try:
        return int((os.getenv(name) or str(default)).strip())
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    """Float env value, falling back to ``default`` (never raises)."""
    try:
        return float((os.getenv(name) or str(default)).strip())
    except ValueError:
        return default


def env_optional(*names: str) -> Optional[str]:
    """First non-empty env var among names, in order."""
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None
