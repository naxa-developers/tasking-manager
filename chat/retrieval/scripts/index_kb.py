#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, List, Optional

from chat.retrieval.config import get_embedding_config, get_pgvector_config

RETRIEVAL_DIR = Path(__file__).resolve().parents[1]

_TABLE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _valid_table_name(name: str) -> bool:
    """Allow-list for operator-supplied pgvector table names."""
    return bool(_TABLE_NAME_RE.match(name or ""))


def _truncate_table(table: str) -> bool:
    """Truncate data_{table} (fall back to {table}); True on success."""
    from chat.retrieval.config import get_db_connection

    try:
        conn = get_db_connection()
    except Exception as e:
        print(f"[index] truncate failed: {e}", file=sys.stderr)
        return False
    try:
        conn.autocommit = True
        cur = conn.cursor()
        # PGVectorStore uses data_{table} per from_params
        for tbl in (f"data_{table}", table):
            try:
                cur.execute(f'TRUNCATE "{tbl}";')  # type: ignore
                print(f"[index] truncated {tbl}")
                return True
            except Exception:
                conn.rollback()
                continue
        print("[index] truncate failed: no matching table", file=sys.stderr)
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _zip_embeddings(nodes: List[Any], batch_embs: List[List[float]]) -> None:
    """Attach one batch of embeddings; raise on provider row-count mismatch."""
    if len(batch_embs) != len(nodes):
        raise ValueError(
            f"embedding count mismatch: {len(batch_embs)} rows for {len(nodes)} texts"
        )
    for n, emb_vec in zip(nodes, batch_embs):
        n.embedding = emb_vec  # type: ignore


def _load_chunks(chunks_path: Path, limit: int = 0) -> List[dict]:
    payload = json.loads(chunks_path.read_text(encoding="utf-8"))
    raw = payload.get("chunks") if isinstance(payload, dict) and "chunks" in payload else payload
    if not isinstance(raw, list):
        raise ValueError(f"Unexpected chunks.json shape in {chunks_path}")
    if limit and limit > 0:
        raw = raw[:limit]
    return raw  # type: ignore


def _get_embedding_model():  # type: ignore[no-untyped-def]
    from chat.retrieval.config import get_embedding_model

    return get_embedding_model()


def _get_vector_store(table_name: str):  # type: ignore[no-untyped-def]
    from chat.retrieval.config import get_vector_store

    return get_vector_store(table_name=table_name)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Index flat 53 chunks.json → pgvector 5432 via litellm")
    ap.add_argument("--chunks", type=Path, default=RETRIEVAL_DIR / "data" / "chunks.json", help="chunks.json path")
    ap.add_argument("--table", type=str, default=None, help="PGVector table (default PGVECTOR_TABLE=kb_nodes)")
    ap.add_argument("--limit", type=int, default=0, help="Limit chunks for smoke (0=all)")
    ap.add_argument("--truncate", action="store_true", help="TRUNCATE table before insert")
    ap.add_argument("--dry-run", action="store_true", help="Don't write vectors, just validate chunks + embedding shape")
    args = ap.parse_args(argv)

    chunks_path: Path = args.chunks if args.chunks.is_absolute() else Path.cwd() / args.chunks
    if not chunks_path.exists():
        print(f"[index] chunks.json not found: {chunks_path}", file=sys.stderr)
        print("[index] run: python -m chat.retrieval.chunk --kb chat/knowledge-base --write chat/retrieval/data/chunks.json", file=sys.stderr)
        return 2
    raw_chunks = _load_chunks(chunks_path, limit=args.limit)
    print(f"[index] loaded {len(raw_chunks)} chunks from {chunks_path}")

    # Validate LiteLLM embedding is reachable (one probe query)
    emb = _get_embedding_model()
    probe = raw_chunks[0].get("text", "")[:500] if raw_chunks else "hello"
    print(f"[index] probe embedding model {get_embedding_config().model} ...")
    if not args.dry_run:
        try:
            q_emb = emb.get_query_embedding(probe)  # type: ignore[union-attr]
            print(f"[index] probe dim={len(q_emb)} (expected {get_embedding_config().dimension})")
            if len(q_emb) != get_embedding_config().dimension:
                print(f"[index] WARN dim mismatch", file=sys.stderr)
        except Exception as e:
            print(f"[index] embedding probe failed: {e}", file=sys.stderr)
            print(f"[index] check the embedding API key in tasking-manager.env", file=sys.stderr)
            return 1
    else:
        print("[index] dry-run: skip probe")

    if args.dry_run:
        return 0

    table = args.table or get_pgvector_config().table_name
    if not _valid_table_name(table):
        print(
            f"[index] invalid table name {table!r} (expected ^[A-Za-z0-9_]+$)",
            file=sys.stderr,
        )
        return 2
    store = _get_vector_store(table)
    print(f"[index] pgvector {get_pgvector_config().host}:{get_pgvector_config().port}/{get_pgvector_config().database} table={table}")

    # Convert to TextNodes then embed + add (PGVectorStore.add expects node.embedding set)
    from llama_index.core.schema import TextNode  # type: ignore

    nodes: List[Any] = []
    skipped = 0
    for entry in raw_chunks:
        nid = entry.get("id") or entry.get("node_id") or ""
        text = entry.get("text") or entry.get("content") or ""
        metadata = entry.get("metadata") or {}
        try:
            nodes.append(TextNode(text=text, id_=nid, metadata=metadata))
        except Exception:
            skipped += 1
            continue
    if skipped:
        print(f"[index] skipped {skipped} unparsable chunk entries", file=sys.stderr)

    # Pre-embed via LiteLLM (batch to respect rate limits, 10 at a time)
    cfg = get_embedding_config()
    print(f"[index] embedding {len(nodes)} nodes with model {cfg.model} ...")
    print(f"[index] query_prefix={'set' if cfg.query_prefix else 'empty'} doc_prefix={'set' if cfg.doc_prefix else 'empty'}")
    if "qwen" in cfg.model.lower() and not cfg.query_prefix:
        print("[index] WARN Qwen embedding model without query prefix — recall will degrade", file=sys.stderr)
    try:
        # Batch to avoid token limit per call (10 x 600 tok ~ 6K)
        batch_size = 10
        all_embs: List[List[float]] = []
        for i in range(0, len(nodes), batch_size):
            batch_texts = [cfg.apply_doc_prefix(n.text) for n in nodes[i : i + batch_size]]
            # LiteLLM batch: loop litellm.embedding per batch_texts (litellm supports list input)
            import litellm  # type: ignore

            model_id = get_embedding_config().model
            # Auth is passed explicitly (provider-generic env names — see config).
            auth_kw: dict = {}
            if cfg.api_key:
                auth_kw["api_key"] = cfg.api_key
            if cfg.api_base:
                auth_kw["api_base"] = cfg.api_base
            resp = litellm.embedding(model=model_id, input=batch_texts, **auth_kw)  # type: ignore
            # parse embeddings
            try:
                batch_embs = [d["embedding"] for d in resp.data]  # type: ignore
            except Exception:
                batch_embs = [d["embedding"] for d in resp["data"]]  # type: ignore
            try:
                _zip_embeddings(nodes[i : i + batch_size], batch_embs)
            except ValueError as e:
                print(f"[index] {e}; aborting", file=sys.stderr)
                return 1
            all_embs.extend(batch_embs)
            print(f"[index]  batch {i//batch_size+1}/{(len(nodes)+batch_size-1)//batch_size} done ({len(all_embs)}/{len(nodes)})")
        print(f"[index] embedding done dim={len(all_embs[0]) if all_embs else 0}")
    except Exception as e:
        print(f"[index] embedding failed: {e}", file=sys.stderr)
        return 1

    # Truncate only after embeddings succeeded: an embedding failure must not
    # wipe the live table.
    if args.truncate and not _truncate_table(table):
        print("[index] aborting: --truncate requested but truncate failed", file=sys.stderr)
        return 1

    try:
        store.add(nodes)  # type: ignore[union-attr]
        print(f"[index] added {len(nodes)} nodes to {table} (flat 53)")
        print("[index] restart RAG workers to pick up the new index")
        # Verify count
        try:
            from chat.retrieval.config import get_db_connection

            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(f'SELECT count(*) FROM "data_{table}";')
            cnt = cur.fetchone()[0]
            print(f"[index] verify data_{table} count={cnt}")
            conn.close()
        except Exception as e:
            print(f"[index] verify count failed: {e}", file=sys.stderr)
        return 0
    except Exception as e:
        print(f"[index] PGVectorStore.add failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
