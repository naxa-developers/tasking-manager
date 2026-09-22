import json
from typing import Any, Dict, List, Optional

from databases import Database
from loguru import logger
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from backend.db import Base
from backend.models.postgis.user import User
from backend.models.postgis.utils import timestamp

# Session-view cap: GET /sessions/{id} returns at most this many newest messages.
MAX_SESSION_MESSAGES = 200

# rag_messages is raw SQL, not ORM: keep it on Base.metadata in sync with migrations.
rag_messages = Table(
    "rag_messages",
    Base.metadata,
    Column("id", BigInteger, primary_key=True),
    Column(
        "session_id",
        BigInteger,
        ForeignKey("rag_sessions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("role", String(16), nullable=False),
    Column("content", Text, nullable=False),
    Column("citations", JSONB, nullable=True),
    Column("model", String(64), nullable=True),
    Column("candidate_count", Integer, nullable=True),
    Column("created_at", DateTime, nullable=False),
    Index("ix_rag_messages_session_created", "session_id", "created_at"),
)


def _parse_citations(citations: Any) -> List[Dict[str, Any]]:
    """Decode a stored ``citations`` value into citation dicts."""
    if isinstance(citations, str):
        try:
            decoded = json.loads(citations)
        except ValueError:
            return []
        return decoded if isinstance(decoded, list) else []
    if isinstance(citations, list):
        return citations
    return []


class RagSession(Base):
    """A TMBot conversation session (global, not project-scoped)."""

    __tablename__ = "rag_sessions"

    __table_args__ = (Index("ix_rag_sessions_updated_at", "updated_at"),)

    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True, index=True)
    title = Column(String(200), nullable=False, default="New chat")
    created_at = Column(DateTime, nullable=False, default=timestamp)
    updated_at = Column(DateTime, nullable=False, default=timestamp)
    message_count = Column(Integer, nullable=False, default=0)

    user = relationship(User, foreign_keys=[user_id])

    @staticmethod
    async def create(user_id: int, title: str, db: Database) -> Dict[str, Any]:
        """Create a new session and return its row."""
        now = timestamp()
        query = """
            INSERT INTO rag_sessions (user_id, title, created_at, updated_at, message_count)
            VALUES (:user_id, :title, :created_at, :updated_at, 0)
            RETURNING id, user_id, title, created_at, updated_at, message_count
        """
        values = {
            "user_id": user_id,
            "title": title[:200],
            "created_at": now,
            "updated_at": now,
        }
        row = await db.fetch_one(query=query, values=values)
        if row:
            logger.debug(f"Created rag session {row['id']}")
        return dict(row) if row else {}

    @staticmethod
    async def get_by_id(session_id: int, db: Database) -> Optional[Dict[str, Any]]:
        """Return a session row by id, or None when it does not exist."""
        query = """
            SELECT id, user_id, title, created_at, updated_at, message_count
            FROM rag_sessions WHERE id = :id
        """
        row = await db.fetch_one(query=query, values={"id": session_id})
        return dict(row) if row else None

    @staticmethod
    async def list_for(
        user_id: int,
        db: Database,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List sessions for a user, ordered by recency."""
        if user_id is None:
            raise ValueError("user_id is required: sessions are owner-scoped")
        query = """
            SELECT id, user_id, title, created_at, updated_at, message_count
            FROM rag_sessions
            WHERE user_id = :user_id
            ORDER BY updated_at DESC
            LIMIT :limit OFFSET :offset
        """
        values = {"user_id": user_id, "limit": limit, "offset": offset}
        rows = await db.fetch_all(query=query, values=values)
        return [dict(r) for r in rows]

    @staticmethod
    async def update_title(session_id: int, title: str, db: Database) -> None:
        """Update a session title and bump its ``updated_at``."""
        query = "UPDATE rag_sessions SET title = :title, updated_at = :updated_at WHERE id = :id"
        await db.execute(
            query=query,
            values={
                "id": session_id,
                "title": title[:200],
                "updated_at": timestamp(),
            },
        )

    @staticmethod
    async def touch(session_id: int, db: Database) -> None:
        """Bump ``updated_at`` and increment ``message_count`` after a turn."""
        query = """
            UPDATE rag_sessions
            SET updated_at = :updated_at, message_count = message_count + 1
            WHERE id = :id
        """
        await db.execute(
            query=query, values={"id": session_id, "updated_at": timestamp()}
        )

    @staticmethod
    async def delete(session_id: int, db: Database) -> bool:
        """Delete a session; return True when a row was removed."""
        query = "DELETE FROM rag_sessions WHERE id = :id RETURNING id"
        row = await db.fetch_one(query=query, values={"id": session_id})
        return row is not None

    @staticmethod
    async def add_message(
        session_id: int,
        role: str,
        content: str,
        db: Database,
        citations: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        candidate_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Append a message to a session and return its row."""
        query = """
            INSERT INTO rag_messages
                (session_id, role, content, citations, model, candidate_count, created_at)
            VALUES
                (:session_id, :role, :content, :citations, :model, :candidate_count, :created_at)
            RETURNING id, session_id, role, content, citations, model, candidate_count, created_at
        """
        values = {
            "session_id": session_id,
            "role": role,
            "content": content,
            "citations": json.dumps(citations) if citations is not None else None,
            "model": model,
            "candidate_count": candidate_count,
            "created_at": timestamp(),
        }
        row = await db.fetch_one(query=query, values=values)
        return dict(row) if row else {}

    @staticmethod
    async def get_messages(
        session_id: int,
        db: Database,
        limit: int = MAX_SESSION_MESSAGES,
        offset: int = 0,
        newest_first: bool = False,
    ) -> List[Dict[str, Any]]:
        """Return messages in chronological order."""
        order = "DESC" if newest_first else "ASC"
        query = f"""
            SELECT id, session_id, role, content, citations, model, candidate_count, created_at
            FROM rag_messages
            WHERE session_id = :session_id
            ORDER BY created_at {order}, id {order}
            LIMIT :limit OFFSET :offset
        """
        rows = await db.fetch_all(
            query=query,
            values={"session_id": session_id, "limit": limit, "offset": offset},
        )
        if newest_first:
            rows.reverse()
        return [
            {**dict(row), "citations": _parse_citations(row["citations"])}
            for row in rows
        ]
