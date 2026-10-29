from __future__ import annotations

from dataclasses import dataclass

from databases import Database
from loguru import logger

from chat.env import env_int

DEFAULT_RATE_LIMIT = 20
DEFAULT_RATE_WINDOW_SECONDS = 60


@dataclass(frozen=True)
class RateLimitConfig:
    limit: int  # turns accepted per window; <= 0 disables the limiter
    window_seconds: int


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after: int  # seconds until the window resets; 0 when allowed
    remaining: int


def get_rate_limit_config() -> RateLimitConfig:
    return RateLimitConfig(
        limit=env_int("RAG_CHAT_RATE_LIMIT", DEFAULT_RATE_LIMIT),
        window_seconds=max(
            1, env_int("RAG_CHAT_RATE_WINDOW_SECONDS", DEFAULT_RATE_WINDOW_SECONDS)
        ),
    )


# One atomic upsert: reset an expired window, otherwise count the turn.
# RETURNING gives the new count and seconds left, from database time.
_COUNT_TURN = """
    INSERT INTO rag_rate_limits (user_id, window_start, count)
    VALUES (:user_id, NOW(), 1)
    ON CONFLICT (user_id) DO UPDATE SET
        count = CASE
            WHEN rag_rate_limits.window_start
                 <= NOW() - make_interval(secs => :window_seconds)
            THEN 1
            ELSE rag_rate_limits.count + 1
        END,
        window_start = CASE
            WHEN rag_rate_limits.window_start
                 <= NOW() - make_interval(secs => :window_seconds)
            THEN NOW()
            ELSE rag_rate_limits.window_start
        END
    RETURNING count,
        CEIL(EXTRACT(EPOCH FROM (
            window_start + make_interval(secs => :window_seconds) - NOW()
        )))::int AS retry_after
"""


async def check_rate_limit(user_id: int, db: Database) -> RateLimitDecision:
    """Count one chat turn for ``user_id`` and report whether it is allowed."""
    cfg = get_rate_limit_config()
    if cfg.limit <= 0:
        return RateLimitDecision(allowed=True, retry_after=0, remaining=0)

    try:
        row = await db.fetch_one(
            query=_COUNT_TURN,
            values={"user_id": user_id, "window_seconds": cfg.window_seconds},
        )
    except Exception as e:
        logger.warning(f"RAG rate limit check failed, allowing turn: {e}")
        return RateLimitDecision(allowed=True, retry_after=0, remaining=cfg.limit)

    count = int(row["count"]) if row else 1
    retry_after = int(row["retry_after"] or 0) if row else 0
    if count > cfg.limit:
        return RateLimitDecision(
            allowed=False, retry_after=max(1, retry_after), remaining=0
        )
    return RateLimitDecision(
        allowed=True, retry_after=0, remaining=max(0, cfg.limit - count)
    )
