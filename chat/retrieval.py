#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import os
import threading
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from chat.env import env_int

if TYPE_CHECKING:  # annotations only; runtime imports stay lazy (see from_chunks)
    from llama_index.core.schema import TextNode
    from llama_index.retrievers.bm25 import BM25Retriever

RETRIEVAL_DIR = Path(__file__).resolve().parent

# Constants (align with eval/harness recipe)

CHUNKS_PATH = Path(
    os.getenv("RAG_CHUNKS_PATH") or RETRIEVAL_DIR / "data" / "chunks.json"
)
_CHUNKS_BUILD_HINT = (
    f"chunks.json not found at {CHUNKS_PATH} — set RAG_CHUNKS_PATH "
    "to a valid chunks.json build"
)


class RetrievalUnavailable(RuntimeError):
    """Hybrid retrieval could not run; never serve partial results."""

    def __init__(self, detail: str, kind: str = "unavailable") -> None:
        super().__init__(detail)
        self.kind = kind  # "too_large" | "unavailable"


@dataclass
class ScoredNode:
    node: "TextNode"
    vector_rank: Optional[int] = None
    bm25_rank: Optional[int] = None
    vector_score: Optional[float] = None
    bm25_score: Optional[float] = None
    fused_score: float = 0.0


@dataclass
class RetrievalResponse:
    results: List[ScoredNode]
    candidate_count: int
    mode: str
    query: str
    timing_ms: Dict[str, float] = field(default_factory=dict)


def _is_active(node: "TextNode") -> bool:
    """Soft-delete filter — archived nodes are hidden at retrieval."""
    try:
        status = (node.metadata or {}).get("status", "active")
        return str(status).lower() != "archived"
    except Exception:
        return True


def _node_from_entry(index: int, entry: Any) -> Optional["TextNode"]:
    """Rebuild one chunks.json entry; warn and skip on malformed input."""
    from llama_index.core.schema import TextNode  # type: ignore

    if not isinstance(entry, dict):
        warnings.warn(f"chunks.json entry #{index} is not an object; skipping")
        return None
    nid = entry.get("id") or entry.get("node_id") or entry.get("chunk_id") or ""
    text = entry.get("text") or entry.get("content") or ""
    metadata = entry.get("metadata") or {}
    if not metadata:
        # Fallback: entry itself may be metadata
        metadata = {
            k: v for k, v in entry.items() if k not in {"id", "text", "content"}
        }
    # Soft-delete is handled after load; preserve all metadata
    try:
        node = TextNode(text=text, id_=nid, metadata=metadata)
        # Preserve embedding if present in payload (optional, not required for BM25)
        if entry.get("embedding"):
            node.embedding = entry["embedding"]
        return node
    except Exception as exc:
        warnings.warn(
            f"chunks.json entry #{index} could not be rebuilt ({exc}); skipping"
        )
        return None


def load_nodes(path: Path) -> List["TextNode"]:
    """Read chunks.json and rebuild TextNodes. Pure: no cache, no state."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as exc:
        raise ValueError(f"chunks.json at {path} is not valid JSON: {exc}") from exc

    if isinstance(payload, dict) and "chunks" in payload:
        raw_chunks = payload["chunks"]
    elif isinstance(payload, list):
        raw_chunks = payload
    else:
        raise ValueError(
            f'chunks.json at {path} must be a list or a {{"chunks": [...]}} object'
        )
    if not isinstance(raw_chunks, list):
        raise ValueError(f'chunks.json "chunks" at {path} must be a list')

    nodes: List["TextNode"] = []
    for index, entry in enumerate(raw_chunks):
        node = _node_from_entry(index, entry)
        if node is not None:
            nodes.append(node)
    return nodes


@dataclass
class RankedCandidates:
    """One retriever's ranked output: best-first node ids, scores, and nodes."""

    ids: List[str]
    scores: Dict[str, float]
    error: Optional[str] = None
    nodes: Dict[str, "TextNode"] = field(default_factory=dict)


_RRF_K = 60.0  # reciprocal-rank-fusion constant (Cormack et al.)


def _reciprocal_rank_fusion(
    vec: RankedCandidates,
    bm25: RankedCandidates,
    node_map: Dict[str, "TextNode"],
) -> List[ScoredNode]:
    """Fuse the two ranked arms by reciprocal rank, best-first."""
    fused_scores: Dict[str, float] = {}
    hash_to_ranked: Dict[str, Tuple[str, "TextNode"]] = {}
    for arm in (vec, bm25):
        ranked = [
            (nid, arm.nodes.get(nid) or node_map.get(nid), arm.scores.get(nid))
            for nid in arm.ids
            if arm.nodes.get(nid) is not None or nid in node_map
        ]
        for rank, (nid, node, score) in enumerate(
            sorted(ranked, key=lambda item: item[2] or 0.0, reverse=True)
        ):
            node_hash = node.hash
            hash_to_ranked[node_hash] = (nid, node)
            fused_scores[node_hash] = fused_scores.get(node_hash, 0.0) + 1.0 / (
                rank + _RRF_K
            )

    vec_rank_index = {nid: idx + 1 for idx, nid in enumerate(vec.ids)}
    bm25_rank_index = {nid: idx + 1 for idx, nid in enumerate(bm25.ids)}
    results: List[ScoredNode] = []
    seen_ids: set = set()
    for node_hash, fused_score in sorted(
        fused_scores.items(), key=lambda item: item[1], reverse=True
    ):
        nid, ranked_node = hash_to_ranked[node_hash]
        if nid in seen_ids:
            # Fused by content hash; keep one logical result per node_id.
            continue
        # Prefer the vector store's node; fall back to chunks/BM25 node.
        node = vec.nodes.get(nid) or node_map.get(nid) or ranked_node
        seen_ids.add(nid)
        results.append(
            ScoredNode(
                node=node,
                vector_rank=vec_rank_index.get(nid),
                bm25_rank=bm25_rank_index.get(nid),
                vector_score=vec.scores.get(nid),
                bm25_score=bm25.scores.get(nid),
                fused_score=float(fused_score or 0.0),
            )
        )
    return results


def _ids_from_store_result(
    res: Any,
) -> tuple[List[str], Dict[str, float], Dict[str, "TextNode"]]:
    """Ids, scores, and store nodes from either supported result shape."""
    ids: List[str] = []
    sims: Dict[str, float] = {}
    store_nodes: Dict[str, "TextNode"] = {}
    res_nodes = list(getattr(res, "nodes", None) or [])
    if getattr(res, "ids", None):
        ids = list(res.ids)
        for nid, sim in zip(ids, res.similarities or []):
            if sim is not None:
                sims[nid] = float(sim)
        # pgvector returns node text + metadata per query; keep aligned with res.ids.
        for nid, item in zip(ids, res_nodes):
            node = getattr(item, "node", item)
            if node is not None:
                store_nodes[nid] = node
    elif res_nodes:
        for item in res_nodes:
            node = getattr(item, "node", item)
            nid = getattr(node, "id_", None) or getattr(item, "id_", None)
            if nid:
                ids.append(nid)
                store_nodes[nid] = node
                score = getattr(item, "score", None)
                if score is not None:
                    sims[nid] = float(score)
    return ids, sims, store_nodes


def _active_candidates(
    ids: List[str],
    store_nodes: Dict[str, "TextNode"],
    node_map: Dict[str, "TextNode"],
) -> tuple[List[str], Dict[str, "TextNode"]]:
    """Keep active nodes in ranked order; store nodes shadow the loaded map."""
    nodes: Dict[str, "TextNode"] = {}
    kept: List[str] = []
    for nid in ids:
        node = store_nodes.get(nid) or node_map.get(nid)
        if node is None or not _is_active(node):
            continue
        nodes[nid] = node
        kept.append(nid)
    return kept, nodes


class Retriever:
    """Owns all retrieval state: nodes, BM25, embedding model, vector store."""

    def __init__(
        self,
        nodes: List["TextNode"],
        node_map: Dict[str, "TextNode"],
        bm25: Optional["BM25Retriever"],
        # Any: config.get_embedding_model/get_vector_store are untyped factories.
        embed_model: Optional[Any] = None,
        vector_store: Optional[Any] = None,
        load_error: Optional[str] = None,
        vector_error: Optional[str] = None,
    ) -> None:
        self.nodes = nodes
        self.node_map = node_map
        self.bm25 = bm25
        self.embed_model = embed_model
        self.vector_store = vector_store
        self.load_error = load_error
        self.vector_error = vector_error

    @classmethod
    def from_chunks(cls, path: Path = CHUNKS_PATH) -> "Retriever":
        """Explicit construction: chunks.json -> nodes -> BM25 + vector handles."""
        load_error: Optional[str] = None
        vector_error: Optional[str] = None

        try:
            nodes = load_nodes(path)
        except FileNotFoundError:
            warnings.warn(f"retrieval degraded: {_CHUNKS_BUILD_HINT}")
            nodes = []
            load_error = _CHUNKS_BUILD_HINT
        except ValueError as exc:
            warnings.warn(f"retrieval degraded: {exc}")
            nodes = []
            load_error = str(exc)

        # Soft-delete: keep only active nodes in map (archived excluded)
        node_map = {n.id_: n for n in nodes if _is_active(n)}

        bm25: Optional[BM25Retriever] = None
        if node_map:
            try:
                from llama_index.retrievers.bm25 import BM25Retriever  # type: ignore

                bm25 = BM25Retriever.from_defaults(
                    nodes=list(node_map.values()),
                    similarity_top_k=len(node_map),
                    language="en",
                    verbose=False,
                )
            except Exception as exc:
                warnings.warn(f"BM25 init failed ({exc}); continuing without BM25")
                detail = f"BM25 init failed: {exc}"
                load_error = (
                    detail if load_error is None else load_error + f" | {detail}"
                )

        # Embedding model + vector store are optional (degrades to BM25-only).
        embed_model: Optional[Any] = None
        vector_store: Optional[Any] = None
        try:
            from chat.config import (
                get_embedding_model,
                get_vector_store,
            )

            embed_model = get_embedding_model()
            vector_store = get_vector_store()
        except Exception as exc:
            vector_error = str(exc)
            warnings.warn(f"vector retrieval unavailable ({exc}); BM25-only")

        return cls(
            nodes, node_map, bm25, embed_model, vector_store, load_error, vector_error
        )

    def vector_candidates(
        self, question: str, limit: Optional[int] = None
    ) -> RankedCandidates:
        """Rank nodes by cosine similarity. Ids best-first, capped by ``limit``."""
        if self.vector_store is None or self.embed_model is None:
            return RankedCandidates(
                [], {}, self.vector_error or "vector store unavailable"
            )

        try:
            q_emb = self.embed_model.get_query_embedding(question)

            from llama_index.core.vector_stores.types import VectorStoreQuery  # type: ignore

            available = max(1, len(self.node_map))
            candidate_limit = max(1, min(available, limit or available))
            res = self.vector_store.query(
                VectorStoreQuery(
                    query_embedding=q_emb,
                    similarity_top_k=candidate_limit,
                    mode="default",
                )
            )

            ids, sims, store_nodes = _ids_from_store_result(res)
            if not ids:
                # No filter is applied, so zero rows with zero error means the
                # table is empty. Flag it instead of serving BM25-only results.
                if self.node_map:
                    return RankedCandidates(
                        [], {}, "vector store returned no candidates (index empty?)"
                    )
                return RankedCandidates([], {}, None)

            # Soft-delete: apply _is_active to the vector store's own nodes.
            kept, nodes = _active_candidates(ids, store_nodes, self.node_map)
            return RankedCandidates(kept, sims, None, nodes)

        except Exception as exc:
            return RankedCandidates([], {}, str(exc))

    def bm25_candidates(
        self, question: str, limit: Optional[int] = None
    ) -> RankedCandidates:
        """Rank active nodes with BM25. Ids best-first, capped by ``limit``."""
        if self.bm25 is None:
            return RankedCandidates([], {}, None)

        try:
            # llama-index-retrievers-bm25 0.4.0 reads the cap from
            # ``self.similarity_top_k``. Copy it so a per-call cap cannot leak.
            retriever = copy.copy(self.bm25)
            retriever.similarity_top_k = limit or len(self.node_map)
            hits = retriever.retrieve(question)
            ids: List[str] = []
            scores: Dict[str, float] = {}
            for item in hits:
                node = getattr(item, "node", item)
                nid = getattr(node, "id_", None)
                score = getattr(item, "score", None)
                if nid and nid in self.node_map:
                    ids.append(nid)
                    if score is not None:
                        scores[nid] = float(score)
            return RankedCandidates(ids, scores, None)
        except Exception as exc:
            warnings.warn(f"BM25 retrieval failed ({exc})")
            return RankedCandidates([], {}, str(exc))

    def retrieve(self, question: str, top_k: Optional[int] = None) -> RetrievalResponse:
        """Run hybrid retrieval: BM25 + vector, fused by fused score."""
        t0 = time.perf_counter()
        arm_top_k = max(1, env_int("RAG_RETRIEVAL_ARM_TOP_K", 30))

        t_arm = time.perf_counter()
        vec = self.vector_candidates(question, limit=arm_top_k)
        vec_ms = (time.perf_counter() - t_arm) * 1000
        t_arm = time.perf_counter()
        bm25 = self.bm25_candidates(question, limit=arm_top_k)
        bm25_ms = (time.perf_counter() - t_arm) * 1000

        if self.load_error:
            # chunks.json missing / BM25 init failed: hybrid retrieval cannot run.
            raise RetrievalUnavailable(f"index load error: {self.load_error}")
        if vec.error:
            if "too large to process" in vec.error.lower():
                # llama.cpp refused the input length: user-fixable, never retried.
                raise RetrievalUnavailable(
                    f"vector search failed: {vec.error}", kind="too_large"
                )
            # One transient retry: an embedding blip must not fail the turn.
            t_arm = time.perf_counter()
            vec = self.vector_candidates(question, limit=arm_top_k)
            vec_ms = (time.perf_counter() - t_arm) * 1000
            if vec.error:
                raise RetrievalUnavailable(f"vector search failed: {vec.error}")
        if bm25.error:
            raise RetrievalUnavailable(f"BM25 search failed: {bm25.error}")
        if not vec.ids and not bm25.ids:
            raise RetrievalUnavailable("no candidates from vector or BM25")

        candidate_count = len(set(vec.ids) | set(bm25.ids))
        results = _reciprocal_rank_fusion(vec, bm25, self.node_map)
        if top_k:
            results = results[:top_k]

        t_done = time.perf_counter()
        timing: Dict[str, float] = {
            "retrieval_ms": vec_ms + bm25_ms,
            "total_ms": (t_done - t0) * 1000,
        }
        return RetrievalResponse(
            results=results,
            candidate_count=candidate_count,
            mode="hybrid",
            query=question,
            timing_ms=timing,
        )


# The process-lifetime instance behind the module-level retrieve() seam.
# It snapshots chunks.json at first use: restart workers after re-indexing.
_DEFAULT: Optional["Retriever"] = None
_DEFAULT_LOCK = threading.Lock()


def _default() -> "Retriever":
    global _DEFAULT
    if _DEFAULT is None:
        with _DEFAULT_LOCK:
            if _DEFAULT is None:
                _DEFAULT = Retriever.from_chunks()
    return _DEFAULT


def retrieve(
    question: str,
    top_k: Optional[int] = None,
) -> RetrievalResponse:
    """Run hybrid RRF retrieval on the default instance (see _default)."""
    return _default().retrieve(question, top_k=top_k)
