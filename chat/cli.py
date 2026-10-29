from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import List, Optional

from chat.pipeline import Delta, Finished, Turn, run_turn, stream_turn


async def _turn(question: str, user_id: Optional[int], db) -> Turn:
    return await run_turn(question, user_id=user_id, db=db)


async def _stream(question: str, user_id: Optional[int], db) -> Turn:
    """Print deltas as they arrive; return the finished turn for the footer."""
    final: Optional[Turn] = None
    async for event in stream_turn(question, user_id=user_id, db=db):
        if isinstance(event, Delta):
            sys.stdout.write(event.text)
            sys.stdout.flush()
        elif isinstance(event, Finished):
            final = event.turn
    print()
    if final is None:
        raise SystemExit("stream ended without a finished turn")
    return final


def _print_json(turn: Turn) -> None:
    print(
        json.dumps(
            {
                "answer": turn.answer,
                "route": turn.route,
                "ops": list(turn.ops),
                "project_id": turn.project_id,
                "reason": turn.reason,
                "candidate_count": turn.candidate_count,
                "model": turn.model,
                "citations": [
                    {k: v for k, v in c.items() if k in ("id", "title", "doc_id")}
                    for c in turn.citations
                ],
            },
            indent=2,
        )
    )


async def _run(
    question: str,
    user_id: Optional[int],
    as_json: bool,
    stream: bool,
) -> int:
    db = None
    if user_id is not None:
        from databases import Database

        from backend.config import settings

        db = Database(settings.SQLALCHEMY_DATABASE_URI.unicode_string())
        await db.connect()
    try:
        turn = (
            await _stream(question, user_id, db)
            if stream
            else await _turn(question, user_id, db)
        )
    finally:
        if db is not None:
            await db.disconnect()

    if as_json:
        _print_json(turn)
        return 0

    if not stream:
        print(turn.answer)
    print("-" * 60)
    print(f"route   : {turn.route}  ops={list(turn.ops)}  project={turn.project_id}")
    print(f"reason  : {turn.reason}  candidates={turn.candidate_count}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ask one question from the terminal."
    )
    parser.add_argument("question", help="Question to ask")
    parser.add_argument(
        "--user-id", type=int, default=None, help="Authenticated user id"
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument(
        "--stream", action="store_true", help="Print the answer as it is generated"
    )
    args = parser.parse_args(argv)
    return asyncio.run(_run(args.question, args.user_id, args.json, args.stream))


if __name__ == "__main__":
    raise SystemExit(main())
