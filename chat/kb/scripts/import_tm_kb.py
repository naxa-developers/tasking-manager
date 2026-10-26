#!/usr/bin/env python3
"""Convert a tm-kb ``chunks.jsonl`` build into tasking-manager's KB shape.

The output is the lean ``chunks.json`` consumed by ``chat/retrieval/query_kb.py``
and ``chat/retrieval/scripts/index_kb.py``. Metadata is mapped to the keys the
turn pipeline uses for citations (``title``, ``doc_id``, ``node_heading``,
``source_refs``, ``provenance``).

If ``--embedding-cache`` is supplied, document vectors are read from the
content-hash cache produced by the standalone tmbot service and written to a
separate ``.npz`` (``ids`` + ``vectors``). ``index_kb.py --embeddings`` then
indexes without re-embedding.

Usage::

    PYTHONPATH=. .venv/bin/python chat/retrieval/scripts/import_tm_kb.py \
        --chunks ~/Desktop/tm-kb/chunks/chunks.jsonl \
        --embedding-cache ~/Desktop/final-rag-chat/chat/cache/embeddings \
        --out-chunks chat/retrieval/data/chunks.json \
        --out-embeddings chat/retrieval/data/embeddings_tmkb.npz

The cache key parameters must match the cache producer, not this repo's
runtime embedding config: the tmbot cache tags ``embeddinggemma`` with the
``title: none | text: `` document prefix and 768 dimensions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

DEFAULT_CHUNK_TOKENS = 600
DEFAULT_CACHE_MODEL = "embeddinggemma"
DEFAULT_CACHE_DOC_PREFIX = "title: none | text: "
DEFAULT_CACHE_DIMENSIONS = 768


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_chunks(path: Path, limit: int = 0) -> List[Dict[str, Any]]:
    """Read the JSONL build; validate the two fields the pipeline needs."""
    chunks = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{line_number}: invalid JSON") from error
            if not isinstance(chunk, dict):
                raise ValueError(f"{path}:{line_number}: chunk must be an object")
            node_id = str(chunk.get("id") or "").strip()
            text = str(chunk.get("text") or "").strip()
            if not node_id or not text:
                raise ValueError(f"{path}:{line_number}: chunk needs id and text")
            chunks.append(chunk)
            if limit and len(chunks) >= limit:
                break
    if not chunks:
        raise ValueError(f"no chunks found in {path}")
    return chunks


def _qualified_doc_id(chunk: Dict[str, Any]) -> str:
    source_id = str(chunk.get("source_id") or "").strip()
    doc_id = str(chunk.get("doc_id") or "").strip()
    if source_id and doc_id and not doc_id.startswith(f"{source_id}/"):
        return f"{source_id}/{doc_id}"
    return doc_id or source_id


def _heading_anchor(node_id: str) -> str:
    if "#h=" not in node_id:
        return ""
    return node_id.split("#h=", 1)[1].split("#", 1)[0]


def _source_refs(chunk: Dict[str, Any], doc_id: str) -> List[Dict[str, str]]:
    source_type = str(chunk.get("source_type") or chunk.get("source_id") or "source")
    source_url = str(chunk.get("source_url") or "").strip()
    if source_url:
        return [{"type": source_type, "path": source_url}]
    if doc_id:
        return [{"type": source_type, "path": doc_id}]
    return []


def build_entry(chunk: Dict[str, Any], node_index: int) -> Dict[str, Any]:
    """Map one tm-kb chunk to the entry shape tasking-manager reads."""
    node_id = str(chunk["id"]).strip()
    text = str(chunk["text"]).strip()
    doc_id = _qualified_doc_id(chunk)
    source_id = str(chunk.get("source_id") or "").strip()
    source_title = str(chunk.get("source_title") or "").strip()
    heading = str(chunk.get("heading") or "").strip()
    section = str(chunk.get("section") or "").strip()
    source_commit = chunk.get("source_commit")
    content_hash = str(chunk.get("content_hash") or "").strip()
    title = source_title or doc_id or source_id
    refs = _source_refs(chunk, doc_id)
    chunk_index = int(chunk.get("chunk_index") or 0)

    metadata: Dict[str, Any] = {
        "doc_id": doc_id,
        "title": title,
        "status": "published",
        "collection": source_id,
        "source_refs": refs,
        "sources": refs,
        "provenance": {"commit": source_commit} if source_commit else {},
        "frozen_commit": source_commit,
        "chunk_index": chunk_index,
        "node_index": node_index,
        "chunk_token_count": int(chunk.get("chunk_token_count") or 0),
        "heading_anchor": _heading_anchor(node_id),
        "node_heading": heading,
        "node_heading_path": section or heading,
        "node_headings": [heading] if heading else [],
        "parent_id": None,
        "is_table_chunk": False,
        "is_troubleshooting_chunk": False,
        "needs_verification": False,
        # Keep the source fields verbatim for provenance/debugging.
        "source_id": source_id,
        "source_type": str(chunk.get("source_type") or ""),
        "source_title": source_title,
        "source_url": str(chunk.get("source_url") or ""),
        "source_commit": source_commit,
        "source_doc_id": str(chunk.get("doc_id") or ""),
        "audience": chunk.get("audience"),
        "license": chunk.get("license"),
        "content_hash": content_hash,
        "hard_split": bool(chunk.get("hard_split")),
    }
    return {
        "id": node_id,
        "doc_id": doc_id,
        "chunk_index": chunk_index,
        "node_index": node_index,
        "title": title,
        "status": "published",
        "embedding_hash": content_hash[:12],
        "text": text,
        "metadata": metadata,
    }


def build_entries(chunks: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [build_entry(chunk, index) for index, chunk in enumerate(chunks)]


def cache_key(
    content_hash: str,
    model: str,
    document_prefix: str,
    dimensions: int,
) -> str:
    """Mirror tmbot's EmbeddingCache.cache_key exactly."""
    material = json.dumps(
        {
            "content_hash": content_hash,
            "dimensions": dimensions,
            "document_prefix": document_prefix,
            "model": model,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(material).hexdigest()


def load_cached_vector(
    cache_dir: Path,
    content_hash: str,
    *,
    model: str,
    document_prefix: str,
    dimensions: int,
) -> List[float]:
    """Load and validate one tmbot cache entry; raise on a mismatch."""
    if not content_hash:
        raise ValueError("chunk has no content_hash")
    path = (
        cache_dir
        / f"{cache_key(content_hash, model, document_prefix, dimensions)}.json"
    )
    if not path.is_file():
        raise FileNotFoundError(f"cache miss for content_hash {content_hash}: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"malformed cache entry: {path}") from error
    expected = {
        "schema_version": 1,
        "content_hash": content_hash,
        "model": model,
        "document_prefix": document_prefix,
        "dimensions": dimensions,
    }
    if not isinstance(payload, dict):
        raise ValueError(f"cache entry is not an object: {path}")
    for field, expected_value in expected.items():
        if payload.get(field) != expected_value:
            raise ValueError(f"cache entry has incompatible {field}: {path}")
    vector = payload.get("vector")
    if not isinstance(vector, list) or len(vector) != dimensions:
        raise ValueError(f"cache entry has an incompatible vector: {path}")
    if not all(
        isinstance(value, (int, float)) and math.isfinite(value) for value in vector
    ):
        raise ValueError(f"cache entry has a non-finite vector: {path}")
    return [float(value) for value in vector]


def collect_embeddings(
    entries: Sequence[Dict[str, Any]],
    cache_dir: Path,
    *,
    model: str,
    document_prefix: str,
    dimensions: int,
) -> List[List[float]]:
    """Load one vector per entry, failing on the first incomplete corpus."""
    vectors: List[List[float]] = []
    errors: List[str] = []
    for entry in entries:
        content_hash = str((entry.get("metadata") or {}).get("content_hash") or "")
        try:
            vectors.append(
                load_cached_vector(
                    cache_dir,
                    content_hash,
                    model=model,
                    document_prefix=document_prefix,
                    dimensions=dimensions,
                )
            )
        except (FileNotFoundError, ValueError) as error:
            errors.append(f"{entry['id']}: {error}")
            if len(errors) >= 5:
                break
    if errors:
        raise ValueError("embedding cache is incomplete:\n  " + "\n  ".join(errors))
    return vectors


def write_chunks(
    entries: Sequence[Dict[str, Any]],
    out_path: Path,
    *,
    chunks_path: Path,
    source_sha256: str,
    chunk_tokens: int,
) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "chat/retrieval/scripts/import_tm_kb.py",
        "parent_child": False,
        "chunk_tokens": chunk_tokens,
        "count": len(entries),
        "source": str(chunks_path),
        "source_sha256": source_sha256,
        "chunks": list(entries),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_embeddings(
    entries: Sequence[Dict[str, Any]],
    vectors: Sequence[Sequence[float]],
    out_path: Path,
) -> Tuple[int, int]:
    """Write ``ids`` + ``vectors`` for index_kb --embeddings."""
    try:
        import numpy as np
    except ImportError as error:
        raise RuntimeError("numpy is required to write embeddings") from error
    ids = np.asarray([entry["id"] for entry in entries], dtype=str)
    matrix = np.asarray(vectors, dtype=np.float32)
    if matrix.ndim != 2 or matrix.shape[0] != len(entries):
        raise ValueError("embedding matrix does not match the chunk count")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out_path, ids=ids, vectors=matrix)
    return matrix.shape[0], matrix.shape[1]


def _summarize(
    chunks: Sequence[Dict[str, Any]],
    entries: Sequence[Dict[str, Any]],
    vectors: Optional[Sequence[Sequence[float]]],
) -> None:
    sources = Counter(
        str((entry.get("metadata") or {}).get("source_id") or "unknown")
        for entry in entries
    )
    max_tokens = max(
        (
            int((entry.get("metadata") or {}).get("chunk_token_count") or 0)
            for entry in entries
        ),
        default=0,
    )
    print(
        f"[import] chunks={len(chunks)} entries={len(entries)} max_tokens={max_tokens}"
    )
    for source, count in sorted(sources.items()):
        print(f"[import]   {source}: {count}")
    if vectors is not None:
        print(
            f"[import] embeddings={len(vectors)} dim={len(vectors[0]) if vectors else 0}"
        )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunks", required=True, type=Path, help="tm-kb chunks.jsonl")
    parser.add_argument(
        "--out-chunks",
        type=Path,
        default=Path("chat/retrieval/data/chunks.json"),
        help="tasking-manager chunks.json output",
    )
    parser.add_argument(
        "--embedding-cache",
        type=Path,
        default=None,
        help="tmbot content-hash embedding cache (optional)",
    )
    parser.add_argument(
        "--out-embeddings",
        type=Path,
        default=Path("chat/retrieval/data/embeddings_tmkb.npz"),
        help="index_kb --embeddings output (used only with --embedding-cache)",
    )
    parser.add_argument("--cache-model", default=DEFAULT_CACHE_MODEL)
    parser.add_argument("--cache-doc-prefix", default=DEFAULT_CACHE_DOC_PREFIX)
    parser.add_argument(
        "--cache-dimensions", type=int, default=DEFAULT_CACHE_DIMENSIONS
    )
    parser.add_argument("--chunk-tokens", type=int, default=DEFAULT_CHUNK_TOKENS)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    chunks_path: Path = args.chunks
    if not chunks_path.is_file():
        print(f"[import] chunks file not found: {chunks_path}", file=sys.stderr)
        return 2
    try:
        chunks = read_chunks(chunks_path, limit=args.limit)
        entries = build_entries(chunks)
        vectors = None
        if args.embedding_cache is not None:
            if not args.embedding_cache.is_dir():
                print(
                    f"[import] embedding cache not found: {args.embedding_cache}",
                    file=sys.stderr,
                )
                return 2
            vectors = collect_embeddings(
                entries,
                args.embedding_cache,
                model=args.cache_model,
                document_prefix=args.cache_doc_prefix,
                dimensions=args.cache_dimensions,
            )
    except (OSError, ValueError) as error:
        print(f"[import] {error}", file=sys.stderr)
        return 1

    _summarize(chunks, entries, vectors)
    if args.dry_run:
        print("[import] dry-run: nothing written")
        return 0

    source_sha256 = _sha256_file(chunks_path)
    write_chunks(
        entries,
        args.out_chunks,
        chunks_path=chunks_path,
        source_sha256=source_sha256,
        chunk_tokens=args.chunk_tokens,
    )
    print(f"[import] wrote {len(entries)} chunks -> {args.out_chunks}")
    if vectors is not None:
        rows, dims = write_embeddings(entries, vectors, args.out_embeddings)
        print(f"[import] wrote {rows}x{dims} embeddings -> {args.out_embeddings}")
    else:
        print("[import] no --embedding-cache: index_kb will embed at index time")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
