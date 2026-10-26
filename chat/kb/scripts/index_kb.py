#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from chat.config import (
    get_embedding_config,
    get_embedding_model,
    get_pgvector_config,
    get_vector_store,
)

RETRIEVAL_DIR = Path(__file__).resolve().parents[1]

_TABLE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _valid_table_name(name: str) -> bool:
    """Allow-list for operator-supplied pgvector table names."""
    return bool(_TABLE_NAME_RE.match(name or ""))


def _truncate_table(table: str) -> bool:
    """Truncate data_{table} (fall back to {table}); True on success."""
    from chat.config import get_db_connection

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
    raw = (
        payload.get("chunks")
        if isinstance(payload, dict) and "chunks" in payload
        else payload
    )
    if not isinstance(raw, list):
        raise ValueError(f"Unexpected chunks.json shape in {chunks_path}")
    if limit and limit > 0:
        raw = raw[:limit]
    return raw  # type: ignore


def _load_embeddings(path: Path) -> Tuple[Dict[str, List[float]], int]:
    """Load the ``ids`` + ``vectors`` npz produced by import_tm_kb.py."""
    try:
        import numpy as np
    except ImportError as error:
        raise RuntimeError("numpy is required for --embeddings") from error
    data = np.load(path, allow_pickle=False)
    if "ids" not in data or "vectors" not in data:
        raise ValueError("embeddings npz must contain ids and vectors")
    ids = [str(value) for value in data["ids"].tolist()]
    matrix = data["vectors"]
    if matrix.ndim != 2 or matrix.shape[0] != len(ids):
        raise ValueError("embeddings vectors shape does not match ids")
    if len(set(ids)) != len(ids):
        raise ValueError("embeddings npz contains duplicate ids")
    vectors = {
        node_id: matrix[index].astype("float32").tolist()
        for index, node_id in enumerate(ids)
    }
    return vectors, int(matrix.shape[1])


def _attach_embeddings(nodes: List[Any], vectors: Dict[str, List[float]]) -> None:
    """Require one vector per node; never silently mix embedded and bare nodes."""
    missing = [node.id_ for node in nodes if node.id_ not in vectors]
    if missing:
        preview = ", ".join(missing[:3])
        raise ValueError(
            f"{len(missing)} nodes have no precomputed vector (first: {preview})"
        )
    for node in nodes:
        node.embedding = vectors[node.id_]  # type: ignore[attr-defined]


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Index chunks.json into pgvector via litellm or precomputed vectors"
    )
    ap.add_argument(
        "--chunks",
        type=Path,
        default=RETRIEVAL_DIR / "data" / "chunks.json",
        help="chunks.json path",
    )
    ap.add_argument(
        "--embeddings",
        type=Path,
        default=None,
        help="optional .npz with ids + vectors (from import_tm_kb.py)",
    )
    ap.add_argument(
        "--table",
        type=str,
        default=None,
        help="PGVector table (default PGVECTOR_TABLE=kb_nodes)",
    )
    ap.add_argument(
        "--limit", type=int, default=0, help="Limit chunks for smoke (0=all)"
    )
    ap.add_argument(
        "--truncate", action="store_true", help="TRUNCATE table before insert"
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate chunks and optional embeddings without DB/embedding calls",
    )
    args = ap.parse_args(argv)

    chunks_path: Path = (
        args.chunks if args.chunks.is_absolute() else Path.cwd() / args.chunks
    )
    if not chunks_path.exists():
        print(f"[index] chunks.json not found: {chunks_path}", file=sys.stderr)
        print(
            "[index] run: python chat/retrieval/scripts/import_tm_kb.py --chunks <tm-kb chunks.jsonl>",
            file=sys.stderr,
        )
        return 2
    try:
        raw_chunks = _load_chunks(chunks_path, limit=args.limit)
    except (OSError, ValueError) as error:
        print(f"[index] could not read chunks: {error}", file=sys.stderr)
        return 2
    print(f"[index] loaded {len(raw_chunks)} chunks from {chunks_path}")

    # Build TextNodes first so a dry run can validate precomputed vectors
    # without contacting the embedding service.
    from llama_index.core.schema import TextNode  # type: ignore

    nodes: List[Any] = []
    skipped = 0
    inline_embeddings = 0
    for entry in raw_chunks:
        nid = entry.get("id") or entry.get("node_id") or ""
        text = entry.get("text") or entry.get("content") or ""
        metadata = entry.get("metadata") or {}
        try:
            node = TextNode(text=text, id_=nid, metadata=metadata)
        except Exception:
            skipped += 1
            continue
        inline = entry.get("embedding")
        if isinstance(inline, list) and inline:
            node.embedding = inline
            inline_embeddings += 1
        nodes.append(node)
    if skipped:
        print(f"[index] skipped {skipped} unparsable chunk entries", file=sys.stderr)
    if not nodes:
        print("[index] no nodes to index", file=sys.stderr)
        return 2

    precomputed = False
    embedding_dim: Optional[int] = None

    if args.embeddings is not None:
        try:
            vectors, embedding_dim = _load_embeddings(args.embeddings)
            _attach_embeddings(nodes, vectors)
        except (OSError, ValueError, RuntimeError) as error:
            print(f"[index] embeddings error: {error}", file=sys.stderr)
            return 2
        precomputed = True
        print(
            f"[index] using {len(nodes)} precomputed vectors "
            f"dim={embedding_dim} from {args.embeddings}"
        )
    elif inline_embeddings:
        if inline_embeddings != len(nodes):
            print(
                "[index] mixed inline embeddings: every node or none",
                file=sys.stderr,
            )
            return 2
        first = getattr(nodes[0], "embedding", None)
        embedding_dim = len(first) if first is not None else 0
        precomputed = True
        print(
            f"[index] using {len(nodes)} inline vectors dim={embedding_dim} "
            "from chunks.json"
        )

    if args.dry_run:
        print(
            f"[index] dry-run: {len(nodes)} nodes, "
            f"precomputed={'yes' if precomputed else 'no'}"
        )
        if precomputed:
            print(f"[index] dry-run: embedding dim={embedding_dim}")
        else:
            print(
                "[index] dry-run: index_kb would embed through the configured service"
            )
        return 0

    cfg = get_embedding_config()
    if precomputed and embedding_dim != cfg.dimension:
        print(
            f"[index] embedding dim mismatch: vectors={embedding_dim} "
            f"configured={cfg.dimension}",
            file=sys.stderr,
        )
        return 2

    if not precomputed:
        # Validate LiteLLM embedding is reachable (one probe query)
        emb = get_embedding_model()
        probe = raw_chunks[0].get("text", "")[:500] if raw_chunks else "hello"
        print(f"[index] probe embedding model {cfg.model} ...")
        try:
            q_emb = emb.get_query_embedding(probe)  # type: ignore[union-attr]
            print(f"[index] probe dim={len(q_emb)} (expected {cfg.dimension})")
            if len(q_emb) != cfg.dimension:
                print("[index] WARN dim mismatch", file=sys.stderr)
        except Exception as e:
            print(f"[index] embedding probe failed: {e}", file=sys.stderr)
            print(
                "[index] check the embedding API key in tasking-manager.env",
                file=sys.stderr,
            )
            return 1

    table = args.table or get_pgvector_config().table_name
    if not _valid_table_name(table):
        print(
            f"[index] invalid table name {table!r} (expected ^[A-Za-z0-9_]+$)",
            file=sys.stderr,
        )
        return 2
    store = get_vector_store(table_name=table)
    print(
        f"[index] pgvector {get_pgvector_config().host}:"
        f"{get_pgvector_config().port}/{get_pgvector_config().database} table={table}"
    )

    if not precomputed:
        print(f"[index] embedding {len(nodes)} nodes with model {cfg.model} ...")
        print(
            "[index] query_prefix="
            f"{'set' if cfg.query_prefix else 'empty'} "
            f"doc_prefix={'set' if cfg.doc_prefix else 'empty'}"
        )
        if "qwen" in cfg.model.lower() and not cfg.query_prefix:
            print(
                "[index] WARN Qwen embedding model without query prefix — recall will degrade",
                file=sys.stderr,
            )
        try:
            # Batch to avoid token limit per call (10 x 600 tok ~ 6K)
            batch_size = 10
            all_embs: List[List[float]] = []
            for i in range(0, len(nodes), batch_size):
                batch_texts = [
                    cfg.apply_doc_prefix(n.text) for n in nodes[i : i + batch_size]
                ]
                import litellm  # type: ignore

                model_id = get_embedding_config().model
                # Auth is passed explicitly (provider-generic env names — see config).
                auth_kw: dict = {}
                if cfg.api_key:
                    auth_kw["api_key"] = cfg.api_key
                if cfg.api_base:
                    auth_kw["api_base"] = cfg.api_base
                resp = litellm.embedding(model=model_id, input=batch_texts, **auth_kw)  # type: ignore
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
                print(
                    f"[index]  batch {i//batch_size+1}/"
                    f"{(len(nodes)+batch_size-1)//batch_size} done "
                    f"({len(all_embs)}/{len(nodes)})"
                )
            print(f"[index] embedding done dim={len(all_embs[0]) if all_embs else 0}")
        except Exception as e:
            print(f"[index] embedding failed: {e}", file=sys.stderr)
            return 1

    # Truncate only after embeddings are present: a failure must not wipe the
    # live table.
    if args.truncate and not _truncate_table(table):
        print(
            "[index] aborting: --truncate requested but truncate failed",
            file=sys.stderr,
        )
        return 1

    try:
        store.add(nodes)  # type: ignore[union-attr]
        print(f"[index] added {len(nodes)} nodes to {table}")
        print("[index] restart RAG workers to pick up the new index")
        # Verify count
        try:
            from chat.config import get_db_connection

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
