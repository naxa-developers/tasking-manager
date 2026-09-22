#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

BM25_TOP = 50  # == query_kb.CANDIDATE_K: same candidate budget as prod retrieve()


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Dump prod BM25 rankings per question")
    ap.add_argument("--questions", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    from chat.retrieval.query_kb import Retriever

    retr = Retriever.from_chunks()
    print(f"[bm25] nodes={len(retr.node_map)} bm25={'ok' if retr.bm25 is not None else 'MISSING'}",
          file=sys.stderr)
    if retr.bm25 is None:
        print("[bm25] BM25 unavailable — abort", file=sys.stderr)
        return 1

    rows = [json.loads(l) for l in Path(args.questions).read_text(encoding="utf-8").splitlines() if l.strip()]
    out = []
    for r in rows:
        bm = retr.bm25_candidates(r["question"])
        top = bm.ids[:BM25_TOP]
        out.append({"id": r["id"], "bm25_ids": top,
                    "bm25_doc_ids": [(retr.node_map[i].metadata or {}).get("doc_id", "") for i in top]})
    Path(args.out).write_text(json.dumps(out))
    print(f"[bm25] wrote {len(out)} rankings -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
