"""Execute the router's chosen operations and merge their evidence.

Fail-soft by design: one slow or broken operation must not sink the turn. Each
op runs inside its own timeout and render boundary, and only authorized
evidence reaches the prompt.
"""

from __future__ import annotations

import asyncio
import math
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from loguru import logger

from rag.domain.registry import OPS_BY_NAME, Fetcher, Op

_DEFAULT_OP_TIMEOUT_SECONDS = 5.0
_MAX_OP_TIMEOUT_SECONDS = 30.0


def op_timeout() -> float:
    """Per-op budget (``RAG_DOMAIN_TIMEOUT``) so one slow read cannot stall a turn."""
    raw = os.environ.get("RAG_DOMAIN_TIMEOUT", "")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return _DEFAULT_OP_TIMEOUT_SECONDS
    if not math.isfinite(value) or value <= 0:
        return _DEFAULT_OP_TIMEOUT_SECONDS
    return min(value, _MAX_OP_TIMEOUT_SECONDS)


@dataclass(frozen=True)
class DomainOutcome:
    """Merged evidence for a DOMAIN or BOTH turn."""

    status: Optional[str] = None
    block: str = ""
    citations: Tuple[Dict[str, Any], ...] = ()
    project_id: Optional[int] = None
    op_statuses: Tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status == "OK"


async def _call(
    op: Op,
    fetcher: Fetcher,
    user_id: int,
    project_id: Optional[int],
    db: Any,
    filters: Dict[str, str],
) -> Any:
    """Invoke one fetcher using the call shape its scope declares."""
    if op.scope == "personal":
        return await fetcher(user_id, db)
    if op.scope == "filter":
        return await fetcher(user_id, project_id, db, filters)
    return await fetcher(user_id, project_id, db)


async def _run_op(
    op: Op,
    user_id: int,
    project_id: Optional[int],
    filters: Dict[str, str],
    db: Any,
) -> Tuple[str, str, Optional[Dict[str, Any]]]:
    """One op inside its timeout and render boundary; never raises."""
    try:
        fetcher = op.load()
    except Exception:
        logger.exception(f"domain op {op.name!r} failed to load")
        return "UNAVAILABLE", "", None

    try:
        evidence = await asyncio.wait_for(
            _call(op, fetcher, user_id, project_id, db, filters),
            timeout=op_timeout(),
        )
        if evidence.authorized:
            # Rendering stays inside the boundary: a broken renderer fails one op.
            return evidence.status, evidence.to_prompt_block(), evidence.to_citation()
        return evidence.status, "", None
    except asyncio.TimeoutError:
        logger.warning(f"domain {op.name} timed out after {op_timeout():.1f}s")
        return "TIMEOUT", "", None
    except Exception:
        logger.exception(f"domain {op.name} failed")
        return "UNAVAILABLE", "", None


def _merge_status(statuses: Sequence[str]) -> Optional[str]:
    """One status for the turn: OK wins, otherwise the first specific failure."""
    if not statuses:
        return None
    if "OK" in statuses:
        return "OK"
    for status in ("UNAUTHORIZED", "TIMEOUT", "UNAVAILABLE"):
        if status in statuses:
            return status
    return "NOT_FOUND"


async def collect(
    user_id: int,
    ops: Sequence[str],
    project_id: Optional[int],
    filters: Optional[Dict[str, str]],
    db: Any,
) -> DomainOutcome:
    """Run every selected op, in router order, and merge what came back."""
    selected = [OPS_BY_NAME[name] for name in ops if name in OPS_BY_NAME]
    if not selected:
        return DomainOutcome(project_id=project_id)

    blocks: List[str] = []
    citations: List[Dict[str, Any]] = []
    statuses: List[str] = []
    op_statuses: List[str] = []

    for op in selected:
        status, block, citation = await _run_op(
            op, user_id, project_id, dict(filters or {}), db
        )
        statuses.append(status)
        op_statuses.append(f"{op.name}:{status}")
        if block:
            blocks.append(block)
        if citation is not None:
            citations.append(citation)

    merged = _merge_status(statuses)
    logger.info(f"rag_domain ops={','.join(op_statuses)} status={merged}")
    return DomainOutcome(
        status=merged,
        block="\n\n".join(blocks),
        citations=tuple(citations),
        project_id=project_id,
        op_statuses=tuple(op_statuses),
    )
