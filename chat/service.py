from __future__ import annotations

import asyncio
import importlib
import httpx
import json
import os
import re
import time
from dataclasses import dataclass
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
)

from databases import Database
from fastapi import HTTPException
from loguru import logger
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from backend.db import db_connection
from chat.dtos import (
    RagChatResponseDTO,
    RagCitationDTO,
    RagMessageDTO,
    RagSessionDTO,
)
from chat.models import MAX_SESSION_MESSAGES, RagSession
from chat.retrieval.policy import (
    DOMAIN_TEMPORARY_ANSWER,
    DOMAIN_UNAVAILABLE_ANSWER,
    GREETING_ANSWER,
    LOW_CONFIDENCE_ANSWER,
    NEEDS_PROJECT_ANSWER,
    SMALLTALK_ANSWERS,
    conf_threshold,
    is_low_confidence,
    third_party_user_answer,
)

try:
    from chat.retrieval.config import get_embedding_config, get_generation_config
    from chat.retrieval.domain.dispatch import collect_evidence
    from chat.retrieval.domain.routing import (
        DomainRoute,
        extract_third_party_username,
        is_third_party_user_query,
        route_query,
    )
    from chat.retrieval.guardrails import (
        classify_query,
        is_followup_query,
        is_smalltalk_query,
        refusal_for,
        smalltalk_kind,
        strip_smalltalk_prefix,
    )
    from chat.retrieval.llm_answer import LLMService
    from chat.retrieval.project_context import (
        clarification_citation,
        latest_explicit_project_id,
        pending_clarification_question,
        resolve_supplied_project_id,
    )
    from chat.retrieval.query_kb import (
        CHUNKS_PATH,
        DEFAULT_TOP_K,
        TOP_K_MAX,
        TOP_K_MIN,
        RetrievalResponse,
        retrieve,
    )

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

# Server-side history lookback for the deterministic layer (not the LLM cap).
MAX_ROUTING_HISTORY = 10

# Session auto-title display width (DB column allows 200 — see RagSession.title).
TITLE_TRUNCATE_LIMIT = 60


class RagAnswerFailed(Exception):
    """Non-streamed LLM generation failed; the API maps it to a 503 body."""


def _public_guardrail(hint: Optional[str]) -> Optional[str]:
    """Client-facing guardrail tag: gate:verdict only; reasons stay server-side."""
    if not hint:
        return None
    head = hint.split(" ", 1)[0]
    parts = head.split(":", 1)
    return ":".join(parts[:2]) if len(parts) == 2 else head


def _retryable_llm_error(exc: Exception) -> bool:
    """True for transient LLM failures worth a single retry (429 / 5xx)."""
    status = getattr(exc, "status_code", None)
    if status in (429, 500, 502, 503, 504):
        return True
    name = type(exc).__name__
    return any(
        k in name
        for k in (
            "RateLimit",
            "Timeout",
            "APIConnection",
            "InternalServer",
            "ServiceUnavailable",
        )
    )


def _log_turn(
    session_id: int,
    user_id: int,
    guardrail: Optional[str],
    candidate_count: int,
    degraded: bool,
    elapsed_ms: int,
    domain_status: Optional[str] = None,
    domain_project_id: Optional[int] = None,
) -> None:
    """Metadata-only per-turn log (no message content). Persisted to tm.json in prod."""
    logger.info(
        "rag_turn session={} user={} guardrail={} candidates={} degraded={} elapsed_ms={} domain={} project={}",
        session_id,
        user_id,
        guardrail or "-",
        candidate_count,
        degraded,
        elapsed_ms,
        domain_status or "-",
        domain_project_id if domain_project_id is not None else "-",
    )


def _truncate_title(question: str, limit: int = TITLE_TRUNCATE_LIMIT) -> str:
    q = question.strip()
    if len(q) <= limit:
        return q or "New chat"
    return q[:limit].rsplit(" ", 1)[0] + "…"


def _build_citations(resp: Any) -> List[RagCitationDTO]:
    citations: List[RagCitationDTO] = []
    for scored in resp.results:
        meta = scored.node.metadata or {}
        prov = meta.get("provenance") or {}
        citations.append(
            RagCitationDTO(
                id=scored.node.id_,
                title=meta.get("title") or "",
                doc_id=meta.get("doc_id") or "",
                heading=meta.get("node_heading") or meta.get("node_heading_path") or "",
                source_refs=meta.get("source_refs") or meta.get("sources") or [],
                commit=prov.get("commit") or meta.get("frozen_commit"),
            )
        )
    return citations


def _history_dicts(messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    return [
        {"role": m["role"], "content": m["content"]}
        for m in messages
        if m.get("role") in {"user", "assistant"}
    ]


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


def _last_user_message(prior: List[Dict[str, Any]]) -> Optional[str]:
    """Most recent user question in the hydrated window."""
    for m in reversed(prior):
        if m.get("role") == "user":
            return m.get("content", "")
    return None


async def _persist_user_turn(
    session_id: int, session: Any, q: str, db: Database
) -> None:
    """Persist the user turn and auto-title the session on its first message."""
    first_turn = int(session.get("message_count") or 0) == 0
    await RagSession.add_message(session_id, "user", q, db)
    await RagSession.touch(session_id, db)
    if first_turn or (session.get("title") in (None, "", "New chat")):
        await RagSession.update_title(session_id, _truncate_title(q), db)


async def _persist_assistant_turn(
    session_id: int,
    answer: str,
    citations: List[RagCitationDTO],
    candidate_count: int,
    db: Database,
    # None for deterministic (canned) answers — no generation ran.
    model: Optional[str] = None,
) -> None:
    await RagSession.add_message(
        session_id,
        "assistant",
        answer,
        db,
        citations=[c.model_dump() for c in citations],
        model=model,
        candidate_count=candidate_count,
    )
    await RagSession.touch(session_id, db)


async def _persist_assistant_turn_stream(
    session_id: int,
    answer: str,
    citations: List[RagCitationDTO],
    candidate_count: int,
    # None for deterministic (canned) answers — no generation ran.
    model: Optional[str] = None,
) -> None:
    """Persist from inside a stream generator (fresh pooled connection)."""
    async with db_connection.database.connection() as fresh:
        await _persist_assistant_turn(
            session_id, answer, citations, candidate_count, fresh, model=model
        )


def _sse_stream(gen: AsyncIterator[str], meta: Dict[str, Any]) -> AsyncIterator[str]:
    """Wrap a chunk/delta generator with trailing meta + done events."""

    async def inner() -> AsyncIterator[str]:
        async for item in gen:
            yield item
        yield f"event: meta\ndata: {json.dumps(meta)}\n\n"
        yield "event: done\ndata: {}\n\n"

    return inner()


@dataclass(frozen=True)
class PreparedTurn:
    """Everything one chat turn needs after guardrails + retrieval."""

    history: List[Dict[str, str]]
    resp: Any
    citations: List[RagCitationDTO]
    guardrail_hint: Optional[str]
    scope_verdict: str
    domain_block: str
    domain_status: Optional[str]
    domain_project_id: Optional[int]
    domain_route_str: Optional[str]
    needs_project_id: bool = False
    third_party_user: bool = False
    third_party_username: Optional[str] = None


async def _prepare_turn(
    q: str,
    top_k_raw: int,
    session: Any,
    db: Database,
    guard: Any,
    user_id: Optional[int] = None,
    prior: Optional[List[Dict[str, Any]]] = None,
) -> PreparedTurn:
    """Validate, persist the user turn, hydrate history, and run retrieval."""
    session_id = session["id"]
    guardrail_hint = None
    if guard.verdict in {"unsafe", "out_of_scope"}:
        guardrail_hint = f"{guard.gate}:{guard.verdict} {guard.reason}"

    top_k = max(TOP_K_MIN, min(TOP_K_MAX, top_k_raw or DEFAULT_TOP_K))

    # Hydrate history from DB unless the caller already did (semantic path).
    if prior is None:
        prior = await RagSession.get_messages(
            session_id, db, limit=MAX_ROUTING_HISTORY, newest_first=True
        )
    history_dicts = _history_dicts(prior)

    retrieval_q = q
    # Follow-up handling: vague q + TM context in history -> expand it.
    # History-first order reads naturally and keeps BM25 term proximity stable.
    if guard.verdict == "out_of_scope" and is_followup_query(q):
        last_user_q = _last_user_message(prior)
        if last_user_q and classify_query(last_user_q).verdict == "ok":
            retrieval_q = f"{last_user_q} {q}"
            guardrail_hint = None  # inherit scope from history
            guard = classify_query(retrieval_q)
            if guard.verdict != "unsafe":
                # Never let merge word order decide an inherited-unsafe verdict.
                reverse = classify_query(f"{q} {last_user_q}")
                if reverse.verdict == "unsafe":
                    guard = reverse
                    guardrail_hint = f"{guard.gate}:{guard.verdict} {guard.reason}"

    # Strip a leading small-talk prefix for retrieval; original q is persisted.
    try:
        _cleaned, _had_prefix = strip_smalltalk_prefix(retrieval_q)
    except Exception:
        _cleaned, _had_prefix = retrieval_q, False
    if _had_prefix:
        retrieval_q = _cleaned
        try:
            guard = classify_query(retrieval_q)
        except Exception:
            pass
        if guard.verdict in {"unsafe", "out_of_scope"}:
            guardrail_hint = f"{guard.gate}:{guard.verdict} {guard.reason}"
        else:
            guardrail_hint = None

    # Third-party profile asks: deterministic web redirect, never LLM evidence.
    try:
        third_party_user = is_third_party_user_query(retrieval_q)
        third_party_username = (
            extract_third_party_username(retrieval_q) if third_party_user else None
        )
    except Exception:
        third_party_user = False
        third_party_username = None

    await _persist_user_turn(session_id, session, q, db)

    if third_party_user:
        # No domain dispatch, no retrieval, no generation for another user's data.
        return PreparedTurn(
            history=history_dicts,
            resp=RetrievalResponse(
                results=[],
                denied_count=0,
                denied_reasons=[],
                candidate_count=0,
                mode="third-party",
                query=retrieval_q,
            ),
            citations=[],
            guardrail_hint=guardrail_hint,
            scope_verdict=guard.verdict,
            domain_block="",
            domain_status=None,
            domain_project_id=None,
            domain_route_str=None,
            third_party_user=True,
            third_party_username=third_party_username,
        )

    # Domain routing: validated classifier intents on the semantic path, the
    # deterministic router otherwise. Auth always runs inside the tool.
    domain_block = ""
    domain_status: Optional[str] = None
    domain_project_id: Optional[int] = None
    domain_route_str: Optional[str] = None
    pending_citations: List[Dict[str, Any]] = []
    needs_project_id = False
    dron: Optional[DomainRoute] = None
    if user_id is not None:
        # Pending clarification: fold the pending question with the supplied id.
        pending_q = pending_clarification_question(prior)
        if pending_q is not None:
            supplied = resolve_supplied_project_id(retrieval_q)
            if supplied is not None:
                retrieval_q = f"{pending_q} project {supplied}"
        try:
            dron = route_query(retrieval_q)
        except Exception:
            dron = None
        if dron is not None and dron.needs_project_id:
            # Never guess an id: use this turn's text, else the latest explicit id.
            supplied = resolve_supplied_project_id(retrieval_q)
            if supplied is not None:
                retrieval_q = f"{retrieval_q} project {supplied}"
                dron = route_query(retrieval_q)
            if dron.needs_project_id:
                inherited = latest_explicit_project_id(prior)
                if inherited is not None:
                    retrieval_q = f"{retrieval_q} project {inherited}"
                    dron = route_query(retrieval_q)
            if dron.needs_project_id:
                needs_project_id = True
                dron = None
        if dron is not None and dron.route in ("DOMAIN", "BOTH"):
            # DOMAIN/BOTH always carry ops; guard keeps the KB path alive if dispatch breaks.
            try:
                outcome = await collect_evidence(user_id, dron, db)
            except Exception:
                logger.exception("domain dispatch failed; continuing KB-only")
                outcome = None
            if outcome is not None:
                domain_route_str = outcome.route
                domain_project_id = outcome.project_id
                domain_status = outcome.status
                domain_block = outcome.block
                pending_citations = [dict(c) for c in outcome.citations]

    if needs_project_id:
        # No retrieval/embedding call for a clarification turn.
        resp = RetrievalResponse(
            results=[],
            denied_count=0,
            denied_reasons=[],
            candidate_count=0,
            mode="clarify",
            query=retrieval_q,
        )
    elif dron is not None and dron.route == "DOMAIN":
        # DOMAIN-only turn: skip embedding + BM25 entirely.
        resp = RetrievalResponse(
            results=[],
            denied_count=0,
            denied_reasons=[],
            candidate_count=0,
            mode="domain-only",
            query=retrieval_q,
        )
    else:
        # Sync retrieval (embedding HTTP + BM25) runs off the event loop.
        resp = await run_in_threadpool(retrieve, retrieval_q, top_k=top_k)
    citations = _build_citations(resp)
    if domain_status == "OK":
        for cite in pending_citations:
            try:
                citations.append(
                    RagCitationDTO(
                        id=cite["id"],
                        title=cite["title"],
                        doc_id=cite["doc_id"],
                        heading=cite["heading"],
                        source_refs=cite["source_refs"],
                        commit=cite.get("commit"),
                    )
                )
            except Exception:
                continue

    return PreparedTurn(
        history=history_dicts,
        resp=resp,
        citations=citations,
        guardrail_hint=guardrail_hint,
        scope_verdict=guard.verdict,
        domain_block=domain_block,
        domain_status=domain_status,
        domain_project_id=domain_project_id,
        domain_route_str=domain_route_str,
        needs_project_id=needs_project_id,
    )


async def _emit_turn(
    *,
    db: Database,
    session_id: int,
    user_id: int,
    stream: bool,
    answer: str,
    citations: List[RagCitationDTO],
    candidate_count: int,
    guardrail: str,
    elapsed_ms: Callable[[], int],
    log_guardrail: Optional[str] = None,
    degraded: bool = False,
    domain_status: Optional[str] = None,
    domain_project_id: Optional[int] = None,
    persist_log: str = "assistant message",
    # None for deterministic (canned) answers — no generation ran.
    model: Optional[str] = None,
) -> Union[RagChatResponseDTO, AsyncIterator[str]]:
    """Persist + log a canned answer; return a DTO or SSE body iterator."""
    meta = {
        "session_id": str(session_id),
        "degraded": degraded,
        "candidate_count": candidate_count,
        "guardrail": guardrail,
        "model": model,
    }
    log_tag = log_guardrail if log_guardrail is not None else guardrail

    if not stream:
        await _persist_assistant_turn(
            session_id, answer, citations, candidate_count, db, model=model
        )
        _log_turn(
            session_id,
            user_id,
            log_tag,
            candidate_count,
            degraded,
            elapsed_ms(),
            domain_status,
            domain_project_id,
        )
        return RagChatResponseDTO(
            answer=answer,
            degraded=degraded,
            candidate_count=candidate_count,
            guardrail=guardrail,
            model=model,
            session_id=str(session_id),
        )

    async def gen():
        yield f"data: {json.dumps({'delta': answer})}\n\n"
        try:
            await _persist_assistant_turn_stream(
                session_id, answer, citations, candidate_count, model=model
            )
        except Exception:
            logger.exception(f"persist {persist_log} failed")
        _log_turn(
            session_id,
            user_id,
            log_tag,
            candidate_count,
            degraded,
            elapsed_ms(),
            domain_status,
            domain_project_id,
        )

    return _sse_stream(gen(), meta)


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
        try:
            generation_cfg = get_generation_config()
        except Exception:
            payload["generation"] = "missing_model"
            degraded_reasons.append("generation model missing")
        else:
            try:
                generation_cfg.require_api_key()
                payload["generation"] = "configured"
            except Exception:
                payload["generation"] = "missing_key"
                degraded_reasons.append("generation key missing")
        try:
            embedding_cfg = get_embedding_config()
        except Exception:
            payload["embedding"] = "missing_model"
            degraded_reasons.append("embedding model missing")
        else:
            try:
                embedding_cfg.require_api_key()
                payload["embedding"] = "configured"
            except Exception:
                payload["embedding"] = "missing_key"
                degraded_reasons.append("embedding key missing")
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
        top_k: int,
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

        # Unsafe always hard-refuses, even when the text starts with small-talk.
        guard = classify_query(q)
        if guard.verdict == "unsafe":
            await _persist_user_turn(session_id, session, q, db)
            client_tag = f"{guard.gate}:{guard.verdict}"
            guard_hint = f"{guard.gate}:{guard.verdict} {guard.reason}"
            return await _emit_turn(
                db=db,
                session_id=session_id,
                user_id=user_id,
                stream=stream,
                answer=refusal_for(guard.verdict),
                citations=[],
                candidate_count=0,
                guardrail=client_tag,
                log_guardrail=guard_hint,
                elapsed_ms=elapsed_ms,
                persist_log="refusal",
            )

        # Pure small-talk short-circuit: canned answer, no retrieval/LLM.
        if is_smalltalk_query(q):
            try:
                _kind = smalltalk_kind(q)
            except Exception:
                _kind = "greeting"
            _answer = SMALLTALK_ANSWERS.get(_kind, GREETING_ANSWER)
            await _persist_user_turn(session_id, session, q, db)
            return await _emit_turn(
                db=db,
                session_id=session_id,
                user_id=user_id,
                stream=stream,
                answer=_answer,
                citations=[],
                candidate_count=0,
                guardrail=_kind if _kind in SMALLTALK_ANSWERS else "greeting",
                elapsed_ms=elapsed_ms,
                persist_log="small-talk",
            )

        # Prior turns: routing history for follow-up and project-id inheritance.
        prior = await RagSession.get_messages(
            session_id, db, limit=MAX_ROUTING_HISTORY, newest_first=True
        )

        prepared = await _prepare_turn(
            q, top_k, session, db, guard, user_id, prior=prior
        )
        resp = prepared.resp
        citations = prepared.citations
        guardrail_hint = prepared.guardrail_hint

        # Inherited-unsafe: never fall through to the LLM on an unsafe verdict.
        if prepared.scope_verdict == "unsafe":
            return await _emit_turn(
                db=db,
                session_id=session_id,
                user_id=user_id,
                stream=stream,
                answer=refusal_for("unsafe"),
                citations=[],
                candidate_count=int(resp.candidate_count),
                guardrail="safety:unsafe",
                log_guardrail=prepared.guardrail_hint or "safety:unsafe",
                degraded=bool(resp.degraded),
                elapsed_ms=elapsed_ms,
                persist_log="refusal",
            )

        # Third-party profile asks: canned web redirect, no evidence, no LLM.
        if prepared.third_party_user:
            return await _emit_turn(
                db=db,
                session_id=session_id,
                user_id=user_id,
                stream=stream,
                answer=third_party_user_answer(prepared.third_party_username),
                citations=[],
                candidate_count=0,
                guardrail="privacy:third-party-user",
                elapsed_ms=elapsed_ms,
                persist_log="third-party user redirect",
            )

        # Missing project id: deterministic clarification, no retrieval/LLM call.
        if prepared.needs_project_id:
            clarify = clarification_citation()
            return await _emit_turn(
                db=db,
                session_id=session_id,
                user_id=user_id,
                stream=stream,
                answer=NEEDS_PROJECT_ANSWER,
                citations=[
                    RagCitationDTO(
                        id=clarify["id"],
                        title=clarify["title"],
                        doc_id=clarify["doc_id"],
                        heading=clarify["heading"],
                        source_refs=clarify["source_refs"],
                        commit=clarify["commit"],
                    )
                ],
                candidate_count=0,
                guardrail="domain:needs-project-id",
                elapsed_ms=elapsed_ms,
                persist_log="project clarification",
            )

        domain_ok = prepared.domain_status == "OK" and bool(
            prepared.domain_block.strip()
        )

        # DOMAIN deny/failure: LLM never called; BOTH routes still answer the KB part.
        if prepared.domain_route_str == "DOMAIN" and prepared.domain_status in (
            "UNAUTHORIZED",
            "NOT_FOUND",
            "TIMEOUT",
            "UNAVAILABLE",
        ):
            temporary = prepared.domain_status in ("TIMEOUT", "UNAVAILABLE")
            return await _emit_turn(
                db=db,
                session_id=session_id,
                user_id=user_id,
                stream=stream,
                answer=(
                    DOMAIN_TEMPORARY_ANSWER if temporary else DOMAIN_UNAVAILABLE_ANSWER
                ),
                citations=[],
                candidate_count=int(resp.candidate_count),
                guardrail="domain:temporary" if temporary else "domain:no-evidence",
                degraded=bool(resp.degraded),
                domain_status=prepared.domain_status,
                domain_project_id=prepared.domain_project_id,
                elapsed_ms=elapsed_ms,
                persist_log=(
                    "temporary domain message"
                    if temporary
                    else "denied assistant message"
                ),
            )

        # Retrieval-gated scope: strong evidence answers, weak evidence gets the precision prompt.
        if prepared.scope_verdict == "out_of_scope" and not domain_ok:
            if is_low_confidence(resp):
                return await _emit_turn(
                    db=db,
                    session_id=session_id,
                    user_id=user_id,
                    stream=stream,
                    answer=refusal_for("out_of_scope"),
                    citations=[],
                    candidate_count=int(resp.candidate_count),
                    guardrail="scope:precision-prompt",
                    log_guardrail=guardrail_hint or "scope:out_of_scope",
                    degraded=bool(resp.degraded),
                    elapsed_ms=elapsed_ms,
                    persist_log="precision prompt",
                )
            guardrail_hint = "scope:answered-from-evidence"

        # Low-confidence guard: fall back without the LLM unless domain evidence is OK.
        if guardrail_hint is None and not domain_ok and is_low_confidence(resp):
            low_log = (
                f"low_confidence top={resp.results[0].fused_score:.4f} thr={conf_threshold():.3f}"
                if resp.results
                else "low_confidence no_candidates"
            )
            return await _emit_turn(
                db=db,
                session_id=session_id,
                user_id=user_id,
                stream=stream,
                answer=LOW_CONFIDENCE_ANSWER,
                citations=[],
                candidate_count=int(resp.candidate_count),
                guardrail="retrieval:low-confidence",
                log_guardrail=low_log,
                degraded=bool(resp.degraded),
                elapsed_ms=elapsed_ms,
                persist_log="low-confidence assistant message",
            )

        llm = LLMService()
        if not stream:
            try:
                # Blocking generation runs in a worker thread, not the loop.
                answer = await run_in_threadpool(
                    llm.answer,
                    q,
                    resp.results,
                    history=prepared.history,
                    domain_evidence=prepared.domain_block,
                )
            except Exception:
                logger.exception("RAG answer failed")
                raise RagAnswerFailed() from None
            await _persist_assistant_turn(
                session_id,
                answer,
                citations,
                int(resp.candidate_count),
                db,
                model=getattr(llm, "model", None),
            )
            _log_turn(
                session_id,
                user_id,
                guardrail_hint,
                int(resp.candidate_count),
                bool(resp.degraded),
                elapsed_ms(),
                prepared.domain_status,
                prepared.domain_project_id,
            )
            return RagChatResponseDTO(
                answer=answer,
                degraded=bool(resp.degraded),
                candidate_count=int(resp.candidate_count),
                guardrail=_public_guardrail(guardrail_hint),
                model=getattr(llm, "model", None),
                session_id=str(session_id),
                citations=citations,
            )

        meta = {
            "session_id": str(session_id),
            "degraded": bool(resp.degraded),
            "candidate_count": int(resp.candidate_count),
            "guardrail": _public_guardrail(guardrail_hint),
            "model": getattr(llm, "model", None),
        }

        async def gen():
            full: List[str] = []
            attempts = 0
            stream_failed = False
            while True:
                try:
                    # Sync stream generator is consumed in a worker thread.
                    async for delta in iterate_in_threadpool(
                        llm.stream(
                            q,
                            resp.results,
                            history=prepared.history,
                            domain_evidence=prepared.domain_block,
                        )
                    ):
                        full.append(delta)
                        yield f"data: {json.dumps({'delta': delta})}\n\n"
                    break
                except Exception as e:
                    # Single retry for transient failures, only if nothing streamed yet.
                    if not full and attempts == 0 and _retryable_llm_error(e):
                        attempts += 1
                        logger.warning(
                            f"RAG stream transient failure, retrying once: {e}"
                        )
                        await asyncio.sleep(1.0)
                        continue
                    logger.exception("RAG stream failed")
                    stream_failed = True
                    yield f"event: error\ndata: {json.dumps({'error': 'Answer generation failed'})}\n\n"
                    break

            answer = "".join(full).strip()
            try:
                # A failed stream may produce no text; never persist an empty turn.
                # Never persist a truncated partial after an error mid-stream.
                if answer and not stream_failed:
                    await _persist_assistant_turn_stream(
                        session_id,
                        answer,
                        citations,
                        int(resp.candidate_count),
                        model=getattr(llm, "model", None),
                    )
            except Exception:
                logger.exception("persist assistant message failed")
            _log_turn(
                session_id,
                user_id,
                guardrail_hint,
                int(resp.candidate_count),
                bool(resp.degraded),
                elapsed_ms(),
                prepared.domain_status,
                prepared.domain_project_id,
            )

        return _sse_stream(gen(), meta)
