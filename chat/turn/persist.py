from __future__ import annotations

from typing import Any, List, Optional

from databases import Database
from loguru import logger

from backend.db import db_connection
from chat.dtos import RagCitationDTO
from chat.models import RagSession

# Session auto-title display width (DB column allows 200 — see RagSession.title).
TITLE_TRUNCATE_LIMIT = 60


def log_turn(
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


def truncate_title(question: str, limit: int = TITLE_TRUNCATE_LIMIT) -> str:
    q = question.strip()
    if len(q) <= limit:
        return q or "New chat"
    return q[:limit].rsplit(" ", 1)[0] + "…"


async def persist_user_turn(
    session_id: int, session: Any, q: str, db: Database
) -> None:
    """Persist the user turn and auto-title the session on its first message."""
    first_turn = int(session.get("message_count") or 0) == 0
    await RagSession.add_message(session_id, "user", q, db)
    await RagSession.touch(session_id, db)
    if first_turn or (session.get("title") in (None, "", "New chat")):
        await RagSession.update_title(session_id, truncate_title(q), db)


async def persist_assistant_turn(
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


async def persist_assistant_turn_stream(
    session_id: int,
    answer: str,
    citations: List[RagCitationDTO],
    candidate_count: int,
    # None for deterministic (canned) answers — no generation ran.
    model: Optional[str] = None,
) -> None:
    """Persist from inside a stream generator (fresh pooled connection)."""
    async with db_connection.database.connection() as fresh:
        await persist_assistant_turn(
            session_id, answer, citations, candidate_count, fresh, model=model
        )
