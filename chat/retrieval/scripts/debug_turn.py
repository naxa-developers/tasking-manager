#!/usr/bin/env python3
"""One-command TMBot turn debugger.

Prints the deterministic decision, KB chunks, domain DB evidence, the exact
LLM prompt, and (optionally) the generated answer for one question. Mirrors
``chat/service.py`` so a debugging run reproduces production behavior without
persisting a session.

Run inside tm-backend:
  docker compose run --rm --no-deps tm-backend \
    python chat/retrieval/scripts/debug_turn.py \
    --user-id 24358865 --question "how many projects have i created?" --show all
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import List, Optional

from chat.retrieval.debug_report import (
    SECTIONS,
    gather_turn,
    render_human,
    resolve_sections,
    to_json,
)


def _parse_history(raw: Optional[str]) -> Optional[List[dict]]:
    if not raw:
        return None
    try:
        history = json.loads(raw)
    except ValueError as exc:
        raise SystemExit(f"invalid --history-json: {exc}")
    if not isinstance(history, list):
        raise SystemExit("--history-json must be a JSON array of {role, content}")
    return history


async def _run(args: argparse.Namespace) -> int:
    db = None
    if args.user_id is not None:
        from databases import Database
        from backend.config import settings

        db = Database(settings.SQLALCHEMY_DATABASE_URI.unicode_string())
        await db.connect()
    try:
        report = await gather_turn(
            db,
            args.question,
            user_id=args.user_id,
            top_k=args.top_k,
            history=_parse_history(args.history_json),
            snippet_chars=args.snippets_chars,
            generate="answer" in args.sections,
        )
    finally:
        if db is not None:
            await db.disconnect()

    if args.json:
        print(to_json(report))
    else:
        print(render_human(report, args.sections))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reproduce one TMBot turn and print decisions, KB chunks, domain "
            "evidence, the exact LLM prompt, and the answer."
        ),
        epilog="Sections: " + ", ".join(SECTIONS) + " (default: all).",
    )
    parser.add_argument("--question", required=True, help="Question to debug")
    parser.add_argument(
        "--user-id",
        type=int,
        default=None,
        help="Authenticated user id (required for live domain ops)",
    )
    parser.add_argument(
        "--top-k", type=int, default=5, help="KB passages to retrieve (default 5)"
    )
    parser.add_argument(
        "--history-json",
        default=None,
        help="JSON array of prior {role, content} turns",
    )
    parser.add_argument(
        "--show",
        default="all",
        help="Comma-separated sections or all (default)",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit one JSON object instead of text"
    )
    parser.add_argument(
        "--snippets-chars",
        type=int,
        default=360,
        help="Max chars per KB snippet (default 360)",
    )
    args = parser.parse_args(argv)

    try:
        args.sections = resolve_sections(args.show)
    except ValueError as exc:
        parser.error(str(exc))
    if args.top_k < 1:
        parser.error("--top-k must be >= 1")
    if args.snippets_chars < 0:
        parser.error("--snippets-chars must be >= 0")

    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001 - debug tool: one clean failure line
        print(f"debug_turn failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
