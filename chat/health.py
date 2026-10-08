"""Deploy-gate health and readiness checks for the RAG stack.

Retrieval modules are imported lazily so a broken RAG stack surfaces as an
unavailable health payload instead of failing application import.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from databases import Database
from loguru import logger
from starlette.concurrency import run_in_threadpool

from chat.service import RagService

_TABLE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")

_READY_PROBE_TTL_DEFAULT = 30.0
_READY_PROBE_TIMEOUT = 3.0
_PROBE_CACHE: Dict[str, Tuple[float, str]] = {}


def _chunks_path() -> Path:
    """chunks.json location (lazy import: the retrieval stack may be down)."""
    from chat.retrieval.query_kb import CHUNKS_PATH

    return CHUNKS_PATH


def _chunks_file_count() -> Optional[int]:
    """Number of chunks in chunks.json, or None when unreadable."""
    try:
        payload = json.loads(_chunks_path().read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(payload, dict):
        count = payload.get("count")
        if isinstance(count, int):
            return count
        chunks = payload.get("chunks")
        return len(chunks) if isinstance(chunks, list) else None
    if isinstance(payload, list):
        return len(payload)
    return None


def _kb_table() -> str:
    """Validated pgvector table name; env-controlled identifier, never raw SQL."""
    base = os.getenv("PGVECTOR_TABLE", "kb_nodes")
    if not _TABLE_NAME_RE.match(base):
        logger.warning(f"Invalid PGVECTOR_TABLE {base!r}; falling back to kb_nodes")
        base = "kb_nodes"
    return f"data_{base}"


def _ready_cache_ttl() -> float:
    """Probe result cache TTL (``RAG_READY_CACHE_TTL``), always positive."""
    try:
        value = float((os.getenv("RAG_READY_CACHE_TTL") or "").strip())
    except ValueError:
        return _READY_PROBE_TTL_DEFAULT
    return value if value > 0 else _READY_PROBE_TTL_DEFAULT


def _require_probe() -> bool:
    """True when an unconfigured provider base must fail readiness."""
    return (os.getenv("RAG_READY_REQUIRE_PROBE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


async def _probe_base(base_url: Optional[str], api_key: Optional[str]) -> str:
    """GET {base}/models: 2xx means the provider answers (no tokens spent)."""
    if not base_url:
        return "skipped (no api_base)"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        async with httpx.AsyncClient(timeout=_READY_PROBE_TIMEOUT) as client:
            resp = await client.get(base_url.rstrip("/") + "/models", headers=headers)
    except Exception as exc:
        logger.warning(f"RAG readiness probe failed for {base_url}: {exc}")
        return "unreachable"
    return "ok" if resp.status_code < 300 else f"http {resp.status_code}"


async def _cached_probe(base_url: Optional[str], api_key: Optional[str]) -> str:
    """Probe with a short TTL so readiness polling cannot hammer providers."""
    key = base_url or ""
    now = time.monotonic()
    cached = _PROBE_CACHE.get(key)
    if cached and now - cached[0] < _ready_cache_ttl():
        return cached[1]
    result = await _probe_base(base_url, api_key)
    _PROBE_CACHE[key] = (now, result)
    return result


def _provider_state(cfg_getter: Any, label: str) -> Tuple[str, Optional[str]]:
    """(health field value, degraded reason) for one LLM provider config."""
    try:
        cfg = cfg_getter()
    except Exception:
        return "missing_model", f"{label} model missing"
    try:
        cfg.require_api_key()
    except Exception:
        return "missing_key", f"{label} key missing"
    return "configured", None


async def rag_health(db: Database) -> Dict[str, Any]:
    """KB health: live pgvector row count + BM25 source (deploy gate)."""
    if not RagService.is_available():
        logger.error(
            f"RAG components failed to import: {RagService.unavailable_reason()}"
        )
        return {
            "status": "unavailable",
            "reason": "RAG components failed to load; see server logs",
        }
    # Deploy gate: the pgvector index must be loaded (index_kb.py is manual).
    table = _kb_table()
    try:
        row = await db.fetch_one(query=f'SELECT COUNT(*) AS n FROM "{table}"')
        indexed = int(row["n"]) if row and row["n"] is not None else 0
    except Exception:
        logger.exception(f"KB health check failed for table {table}")
        return {
            "status": "unavailable",
            "reason": f"KB index unavailable ({table}); see server logs",
        }
    if indexed <= 0:
        return {
            "status": "unavailable",
            "reason": f"KB index empty ({table}, 0 nodes) — run index_kb.py",
            "indexed_nodes": 0,
        }
    payload: Dict[str, Any] = {
        "status": "ok",
        "indexed_nodes": indexed,
        "table": os.getenv("PGVECTOR_TABLE", "kb_nodes"),
    }

    from chat.retrieval.config import get_embedding_config, get_generation_config

    degraded_reasons: List[str] = []
    for provider, cfg_getter in (
        ("generation", get_generation_config),
        ("embedding", get_embedding_config),
    ):
        state, reason = _provider_state(cfg_getter, provider)
        payload[provider] = state
        if reason:
            degraded_reasons.append(reason)
    chunks_count = await run_in_threadpool(_chunks_file_count)
    if chunks_count is not None:
        payload["chunks_file_count"] = chunks_count
        payload["index_mismatch"] = chunks_count != indexed
    chunks_path = _chunks_path()
    if not chunks_path.exists():
        logger.warning(f"BM25 degraded: chunks.json missing at {chunks_path}")
        payload["bm25"] = "unavailable (chunks.json missing)"
    if degraded_reasons:
        payload["status"] = "degraded"
        payload["reason"] = "; ".join(degraded_reasons)
    return payload


async def rag_readiness(db: Database) -> Dict[str, Any]:
    """Strict deploy gate: health diagnostics plus reachable providers."""
    payload = await rag_health(db)
    reasons: List[str] = []
    if payload.get("status") != "ok":
        reasons.append(str(payload.get("reason") or "health check not ok"))
    if payload.get("index_mismatch") is not False:
        reasons.append("chunks.json missing or out of sync with the pgvector index")

    checks: Dict[str, Any] = {
        "health": payload,
        "generation_probe": None,
        "embedding_probe": None,
    }

    from chat.retrieval.config import get_embedding_config, get_generation_config

    for name, cfg_getter in (
        ("generation_probe", get_generation_config),
        ("embedding_probe", get_embedding_config),
    ):
        try:
            cfg = cfg_getter()
        except Exception:
            checks[name] = "config missing"
            continue  # the health payload already reports this
        result = await _cached_probe(cfg.api_base, cfg.api_key)
        checks[name] = result
        if result == "ok" or (
            result == "skipped (no api_base)" and not _require_probe()
        ):
            continue
        reasons.append(f"{name}: {result}")

    return {
        "status": "ready" if not reasons else "not_ready",
        "reasons": reasons,
        "checks": checks,
    }
