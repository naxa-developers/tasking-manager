from __future__ import annotations

import importlib
import httpx
import json
import os
import re
import time
from typing import (
    Any,
    AsyncIterator,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
)

from databases import Database
from fastapi import HTTPException
from loguru import logger
from starlette.concurrency import run_in_threadpool

from chat.constants import MAX_ROUTING_HISTORY
from chat.dtos import (
    RagChatResponseDTO,
    RagMessageDTO,
    RagSessionDTO,
)
from chat.models import MAX_SESSION_MESSAGES, RagSession
from chat.turn.errors import RagAnswerFailed

try:
    from chat.retrieval.config import get_embedding_config, get_generation_config
    from chat.retrieval.guardrails import classify_query
    from chat.retrieval.llm_answer import LLMService
    from chat.retrieval.query_kb import CHUNKS_PATH
    from chat.turn.decide import GenerateTurn, decide_early_turn, decide_turn
    from chat.turn.emit import emit_canned_turn, emit_generated_turn
    from chat.turn.persist import persist_user_turn
    from chat.turn.plan import prepare_turn

    for _domain_module in (
        "global_stats",
        "mywork",
        "project_chat",
        "project_discovery",
        "recommendations",
        "stats",
        "teams",
        "trending",
        "user_activity",
        "user_contributions",
        "user_profile",
        "user_projects",
        "user_orgs",
        "user_tasks",
        "user_teams",
    ):
        importlib.import_module(f"chat.retrieval.domain.{_domain_module}")

    _RAG_AVAILABLE = True
    _RAG_IMPORT_ERROR: Optional[str] = None
except Exception as e:
    logger.warning(f"RAG unavailable: {e}")
    _RAG_AVAILABLE = False
    _RAG_IMPORT_ERROR = str(e)


def _session_dto(row: Dict[str, Any]) -> RagSessionDTO:
    return RagSessionDTO(
        id=str(row.get("id")),
        title=row.get("title") or "New chat",
        user_id=row.get("user_id"),
        created_at=str(row.get("created_at")) if row.get("created_at") else None,
        updated_at=str(row.get("updated_at")) if row.get("updated_at") else None,
        message_count=int(row.get("message_count") or 0),
    )


async def _get_session(session_id: int, db: Database) -> Any:
    session = await RagSession.get_by_id(session_id, db)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


async def _get_owned_session(session_id: int, user_id: int, db: Database) -> Any:
    """Fetch a session or 404 — including when it belongs to another user."""
    session = await _get_session(session_id, db)
    if session.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _chunks_file_count() -> Optional[int]:
    """Number of chunks in chunks.json, or None when unreadable."""
    try:
        payload = json.loads(CHUNKS_PATH.read_text(encoding="utf-8"))
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


_TABLE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _kb_table() -> str:
    """Validated pgvector table name; env-controlled identifier, never raw SQL."""
    base = os.getenv("PGVECTOR_TABLE", "kb_nodes")
    if not _TABLE_NAME_RE.match(base):
        logger.warning(f"Invalid PGVECTOR_TABLE {base!r}; falling back to kb_nodes")
        base = "kb_nodes"
    return f"data_{base}"


_READY_PROBE_TTL_DEFAULT = 30.0
_READY_PROBE_TIMEOUT = 3.0
_PROBE_CACHE: Dict[str, Tuple[float, str]] = {}


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


class RagService:
    """Session CRUD + the RAG answer pipeline."""

    @staticmethod
    def is_available() -> bool:
        """True when the chat/retrieval library imported successfully."""
        return _RAG_AVAILABLE

    @staticmethod
    def unavailable_reason() -> Optional[str]:
        """Import error behind an unavailable RAG deployment, if any."""
        return _RAG_IMPORT_ERROR

    @staticmethod
    async def health(db: Database) -> Dict[str, Any]:
        """KB health: live pgvector row count + BM25 source (deploy gate)."""
        if not _RAG_AVAILABLE:
            logger.error(f"RAG components failed to import: {_RAG_IMPORT_ERROR}")
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
        if not CHUNKS_PATH.exists():
            logger.warning(f"BM25 degraded: chunks.json missing at {CHUNKS_PATH}")
            payload["bm25"] = "unavailable (chunks.json missing)"
        if degraded_reasons:
            payload["status"] = "degraded"
            payload["reason"] = "; ".join(degraded_reasons)
        return payload

    @staticmethod
    async def readiness(db: Database) -> Dict[str, Any]:
        """Strict deploy gate: health diagnostics plus reachable providers."""
        payload = await RagService.health(db)
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

    @staticmethod
    async def create_session(user_id: int, title: str, db: Database) -> RagSessionDTO:
        """Create a session owned by ``user_id`` and return it."""
        row = await RagSession.create(user_id, title or "New chat", db)
        return _session_dto(row)

    @staticmethod
    async def list_sessions(
        user_id: int, limit: int, offset: int, db: Database
    ) -> List[RagSessionDTO]:
        """List ``user_id``'s sessions, newest first (bounded page size)."""
        limit = max(1, min(int(limit or 20), 100))
        offset = max(0, int(offset or 0))
        rows = await RagSession.list_for(user_id, db, limit=limit, offset=offset)
        return [_session_dto(row) for row in rows]

    @staticmethod
    async def get_session_messages(
        session_id: int, user_id: int, db: Database
    ) -> Tuple[RagSessionDTO, List[RagMessageDTO]]:
        """Return an owned session plus its messages, oldest first."""
        session = await _get_owned_session(session_id, user_id, db)
        messages = await RagSession.get_messages(
            session_id, db, limit=MAX_SESSION_MESSAGES, newest_first=True
        )
        return _session_dto(session), [
            RagMessageDTO(
                role=m["role"],
                content=m["content"],
                model=m.get("model"),
                candidate_count=m.get("candidate_count"),
                created_at=str(m.get("created_at")) if m.get("created_at") else None,
            )
            for m in messages
        ]

    @staticmethod
    async def update_session_title(
        session_id: int, user_id: int, title: Optional[str], db: Database
    ) -> RagSessionDTO:
        """Update an owned session's title (no-op when ``title`` is None)."""
        await _get_owned_session(session_id, user_id, db)
        if title is not None:
            await RagSession.update_title(session_id, title, db)
        return _session_dto(await _get_owned_session(session_id, user_id, db))

    @staticmethod
    async def delete_session(session_id: int, user_id: int, db: Database) -> bool:
        """Delete an owned session; False when the row was already gone."""
        await _get_owned_session(session_id, user_id, db)
        return await RagSession.delete(session_id, db)

    @staticmethod
    async def chat(
        session_id: int,
        user_id: int,
        question: str,
        stream: bool,
        db: Database,
    ) -> Union[RagChatResponseDTO, AsyncIterator[str]]:
        """Run one chat turn: guardrails, routing, retrieval, generation, persist."""
        q = question
        started = time.monotonic()

        def elapsed_ms() -> int:
            return int((time.monotonic() - started) * 1000)

        # Ownership first: unknown or foreign sessions (incl. legacy anonymous) 404.
        session = await _get_owned_session(session_id, user_id, db)

        # Static gate: unsafe refusal or small-talk canned answer, no retrieval.
        guard = classify_query(q)
        early = decide_early_turn(guard, q)
        if early is not None:
            await persist_user_turn(session_id, session, q, db)
            return await emit_canned_turn(
                db=db,
                session_id=session_id,
                user_id=user_id,
                stream=stream,
                decision=early,
                elapsed_ms=elapsed_ms,
            )

        # Prior turns: routing history for follow-up and project-id inheritance.
        prior = await RagSession.get_messages(
            session_id, db, limit=MAX_ROUTING_HISTORY, newest_first=True
        )

        prepared = await prepare_turn(q, session, db, guard, user_id, prior=prior)
        decision = decide_turn(prepared)

        if isinstance(decision, GenerateTurn):
            return await emit_generated_turn(
                db=db,
                session_id=session_id,
                user_id=user_id,
                stream=stream,
                question=q,
                prepared=prepared,
                decision=decision,
                llm=LLMService(),
                elapsed_ms=elapsed_ms,
            )
        return await emit_canned_turn(
            db=db,
            session_id=session_id,
            user_id=user_id,
            stream=stream,
            decision=decision,
            elapsed_ms=elapsed_ms,
        )
