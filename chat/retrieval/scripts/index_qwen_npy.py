#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, List, Optional

RETRIEVAL_DIR = Path(__file__).resolve().parents[1]

DEFAULT_TABLE = "kb_nodes_qwen06"
PROTECTED_TABLES = {"kb_nodes", "kb_nodes_test"}
EXPECTED_DIM = 1024


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Index precomputed .npy embeddings → isolated pgvector table")
    ap.add_argument("--npy", type=Path, required=True)
    ap.add_argument("--ids", type=Path, required=True)
    ap.add_argument("--chunks", type=Path, required=True)
    ap.add_argument("--table", type=str, default=DEFAULT_TABLE)
    ap.add_argument("--truncate", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--allow-dim",
        action="store_true",
        help="Allow a dim other than EXPECTED_DIM (default: refuse)",
    )
    ap.add_argument("--allow-default", action="store_true",
                    help="Allow writing the protected OpenAI tables (kb_nodes*)")
    args = ap.parse_args(argv)

    if args.table in PROTECTED_TABLES and not args.allow_default:
        print(f"[qwen-index] REFUSED: {args.table} is the OpenAI index — pass --allow-default to override",
              file=sys.stderr)
        return 2

    try:
        import numpy as np  # type: ignore
    except ImportError as e:
        print(f"[qwen-index] numpy required: {e}", file=sys.stderr)
        return 1

    for p in (args.npy, args.ids, args.chunks):
        if not p.exists():
            print(f"[qwen-index] not found: {p}", file=sys.stderr)
            return 2

    embs = np.load(str(args.npy))
    ids = json.loads(args.ids.read_text(encoding="utf-8"))
    payload = json.loads(args.chunks.read_text(encoding="utf-8"))
    raw = payload.get("chunks", payload) if isinstance(payload, dict) else payload
    by_id = {c.get("id"): c for c in raw if isinstance(c, dict) and c.get("id")}

    # Sidecar meta (model/dim/prefix audit) when present: embed-<slug>.meta.json
    meta_path = args.npy.with_suffix("").with_suffix(".meta.json") \
        if args.npy.name.endswith(".npy") else args.npy.parent / (args.npy.name + ".meta.json")
    alt_meta = Path(str(args.npy).replace(".npy", ".meta.json"))
    meta = {}
    for cand in (alt_meta, meta_path):
        if cand.exists():
            try:
                meta = json.loads(cand.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
            break
    print(f"[qwen-index] npy shape={tuple(embs.shape)} model={meta.get('model', '?')} "
          f"dim={meta.get('dim', embs.shape[1] if len(embs.shape) > 1 else '?')} "
          f"q_prefix={'set' if meta.get('query_prefix') else '?'}")

    if len(embs.shape) != 2 or embs.shape[0] != len(ids):
        print(f"[qwen-index] npy/ids mismatch: shape={tuple(embs.shape)} ids={len(ids)}", file=sys.stderr)
        return 1
    if embs.shape[1] != EXPECTED_DIM and not args.allow_dim:
        print(
            f"[qwen-index] dim={embs.shape[1]} expected {EXPECTED_DIM} — refusing (pass --allow-dim to override)",
            file=sys.stderr,
        )
        return 2
    if embs.shape[1] != EXPECTED_DIM:
        print(f"[qwen-index] WARN dim={embs.shape[1]} expected {EXPECTED_DIM} — table will use actual dim",
              file=sys.stderr)
    dim = int(embs.shape[1])

    missing = [i for i in ids if i not in by_id]
    if missing:
        print(f"[qwen-index] {len(missing)} ids lack chunk text (first: {missing[:3]})", file=sys.stderr)
        return 1
    print(f"[qwen-index] loaded {len(ids)} chunks, dim={dim} → table={args.table}")

    if args.dry_run:
        print("[qwen-index] dry-run: skip write")
        return 0

    from chat.retrieval.config import get_pgvector_config

    pg = get_pgvector_config()
    print(f"[qwen-index] pgvector {pg.host}:{pg.port}/{pg.database} table={args.table} (shared DB, isolated table)")

    if args.truncate:
        try:
            from chat.retrieval.config import get_db_connection

            conn = get_db_connection()
            conn.autocommit = True
            cur = conn.cursor()
            for tbl in (f"data_{args.table}", args.table):
                try:
                    cur.execute(f'TRUNCATE "{tbl}";')
                    print(f"[qwen-index] truncated {tbl}")
                    break
                except Exception:
                    conn.rollback()
                    continue
            try:
                conn.close()
            except Exception:
                pass
        except Exception as e:
            print(f"[qwen-index] truncate failed (non-fatal): {e}", file=sys.stderr)

    from llama_index.core.schema import TextNode  # type: ignore

    nodes: List[Any] = []
    for row, nid in enumerate(ids):
        entry = by_id[nid]
        try:
            node = TextNode(text=entry.get("text") or "", id_=nid,
                            metadata=entry.get("metadata") or {})
            node.embedding = [float(v) for v in embs[row].tolist()]
            nodes.append(node)
        except Exception as e:
            print(f"[qwen-index] skip {nid}: {e}", file=sys.stderr)
    print(f"[qwen-index] built {len(nodes)} nodes with precomputed embeddings")

    try:
        from chat.retrieval.config import get_vector_store

        store = get_vector_store(table_name=args.table, embed_dim=dim)
        store.add(nodes)  # type: ignore[union-attr]
        print(f"[qwen-index] added {len(nodes)} nodes to {args.table}")
    except Exception as e:
        print(f"[qwen-index] PGVectorStore.add failed: {e}", file=sys.stderr)
        return 1

    try:
        from chat.retrieval.config import get_db_connection

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(f'SELECT count(*) FROM "data_{args.table}";')
        cnt = cur.fetchone()[0]
        print(f"[qwen-index] verify data_{args.table} count={cnt}")
        conn.close()
        if cnt != len(nodes):
            print(f"[qwen-index] WARN count mismatch", file=sys.stderr)
    except Exception as e:
        print(f"[qwen-index] verify count failed: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
