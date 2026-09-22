#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import threading
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

if TYPE_CHECKING:  # annotations only; runtime imports stay lazy (see from_chunks)
    from llama_index.core.schema import QueryBundle, TextNode
    from llama_index.retrievers.bm25 import BM25Retriever

RETRIEVAL_DIR = Path(__file__).resolve().parent

# Constants (align with eval/harness recipe)

CANDIDATE_K = 50  # maximum candidates per retriever (never backfilled)
DEFAULT_TOP_K = 5
TOP_K_MIN = 1
TOP_K_MAX = 5
CHUNKS_PATH = RETRIEVAL_DIR / "data" / "chunks.json"
_CHUNKS_BUILD_HINT = (
    f"chunks.json not found at {CHUNKS_PATH} — run python chat/retrieval/chunk.py "
    "--kb chat/knowledge-base --write chat/retrieval/data/chunks.json"
)


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
    denied_count: int
    denied_reasons: List[str]
    candidate_count: int
    mode: str
    query: str
    timing_ms: Dict[str, float] = field(default_factory=dict)
    degraded: bool = False
    degraded_reason: Optional[str] = None
    permission_denied: bool = False
    permission_topic: str = ""
    permission_required_roles: List[str] = field(default_factory=list)


def _is_active(node: "TextNode") -> bool:
    """Soft-delete filter — archived nodes are hidden at retrieval."""
    try:
        status = (node.metadata or {}).get("status", "active")
        return str(status).lower() != "archived"
    except Exception:
        return True


def load_nodes(path: Path) -> List["TextNode"]:
    """Read chunks.json and rebuild TextNodes. Pure: no cache, no state."""
    from llama_index.core.schema import TextNode  # type: ignore

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

    nodes: List[TextNode] = []
    for index, entry in enumerate(raw_chunks):
        if not isinstance(entry, dict):
            warnings.warn(f"chunks.json entry #{index} is not an object; skipping")
            continue
        nid = entry.get("id") or entry.get("node_id") or entry.get("chunk_id") or ""
        text = entry.get("text") or entry.get("content") or ""
        metadata = entry.get("metadata") or {}
        if not metadata:
            # Fallback: entry itself may be metadata
            metadata = {k: v for k, v in entry.items() if k not in {"id", "text", "content"}}
        # Soft-delete is handled after load; preserve all metadata
        try:
            node = TextNode(text=text, id_=nid, metadata=metadata)
            # Preserve embedding if present in payload (optional, not required for BM25)
            if entry.get("embedding"):
                node.embedding = entry["embedding"]
            nodes.append(node)
        except Exception as exc:
            warnings.warn(
                f"chunks.json entry #{index} could not be rebuilt ({exc}); skipping"
            )
            continue
    return nodes


@dataclass
class RankedCandidates:
    """One retriever's ranked output: best-first node ids, scores, and nodes."""
    ids: List[str]
    scores: Dict[str, float]
    error: Optional[str] = None
    nodes: Dict[str, "TextNode"] = field(default_factory=dict)


class _RankCapture:
    """Per-call record of one retrieval arm's ranked output and latency."""

    def __init__(self) -> None:
        self.ranked = RankedCandidates([], {})
        self.elapsed_ms = 0.0


_CANDIDATE_RETRIEVER_CLS = None


def _candidate_retriever_class():
    """Return the thin BaseRetriever adapter over RankedCandidates producers."""
    global _CANDIDATE_RETRIEVER_CLS
    if _CANDIDATE_RETRIEVER_CLS is None:
        from llama_index.core.base.base_retriever import BaseRetriever  # type: ignore
        from llama_index.core.schema import NodeWithScore  # type: ignore

        class _CandidateRetriever(BaseRetriever):
            def __init__(
                self,
                produce: Callable[[str], RankedCandidates],
                node_map: Dict[str, "TextNode"],
                capture: _RankCapture,
            ) -> None:
                self._produce = produce
                self._node_map = node_map
                self._capture = capture
                self._last_query: Optional[str] = None
                self._last_nodes: List["NodeWithScore"] = []
                super().__init__()

            def _retrieve(self, query_bundle: "QueryBundle") -> List["NodeWithScore"]:
                question = query_bundle.query_str
                if question != self._last_query:
                    t0 = time.perf_counter()
                    ranked = self._produce(question)
                    self._capture.elapsed_ms += (time.perf_counter() - t0) * 1000
                    self._capture.ranked = ranked
                    self._last_query = question
                    # Prefer the arm's own nodes; fall back to node_map for id-only arms.
                    self._last_nodes = [
                        NodeWithScore(
                            node=ranked.nodes.get(nid) or self._node_map[nid],
                            score=ranked.scores.get(nid),
                        )
                        for nid in ranked.ids
                        if nid in ranked.nodes or nid in self._node_map
                    ]
                return list(self._last_nodes)

        _CANDIDATE_RETRIEVER_CLS = _CandidateRetriever
    return _CANDIDATE_RETRIEVER_CLS


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
                    similarity_top_k=min(CANDIDATE_K, len(node_map)),
                    language="en",
                    verbose=False,
                )
            except Exception as exc:
                warnings.warn(f"BM25 init failed ({exc}); continuing without BM25")
                detail = f"BM25 init failed: {exc}"
                load_error = detail if load_error is None else load_error + f" | {detail}"

        # Embedding model + vector store are optional (degrades to BM25-only).
        embed_model: Optional[Any] = None
        vector_store: Optional[Any] = None
        try:
            from chat.retrieval.config import (
                get_embedding_model,
                get_vector_store,
            )

            embed_model = get_embedding_model()
            vector_store = get_vector_store()
        except Exception as exc:
            vector_error = str(exc)
            warnings.warn(f"vector retrieval unavailable ({exc}); BM25-only")

        return cls(nodes, node_map, bm25, embed_model, vector_store, load_error, vector_error)

    def vector_candidates(self, question: str) -> RankedCandidates:
        """Rank nodes by cosine similarity. Ids best-first, capped at CANDIDATE_K."""
        if self.vector_store is None or self.embed_model is None:
            return RankedCandidates([], {}, self.vector_error or "vector store unavailable")

        try:
            q_emb = self.embed_model.get_query_embedding(question)

            from llama_index.core.vector_stores.types import VectorStoreQuery  # type: ignore

            res = self.vector_store.query(
                VectorStoreQuery(
                    query_embedding=q_emb, similarity_top_k=CANDIDATE_K, mode="default"
                )
            )

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

            if not ids:
                # A configured store querying a loaded index always returns
                # rows (no filter is applied): zero rows with zero error means
                # the table is empty. Flag it instead of silently serving
                # BM25-only results as healthy.
                if self.node_map:
                    return RankedCandidates(
                        [], {}, "vector store returned no candidates (index empty?)"
                    )
                return RankedCandidates([], {}, None)

            # Soft-delete: apply _is_active to the vector store's own nodes.
            nodes: Dict[str, "TextNode"] = {}
            kept: List[str] = []
            for nid in ids:
                node = store_nodes.get(nid) or self.node_map.get(nid)
                if node is None or not _is_active(node):
                    continue
                nodes[nid] = node
                kept.append(nid)
            return RankedCandidates(kept[:CANDIDATE_K], sims, None, nodes)

        except Exception as exc:
            return RankedCandidates([], {}, str(exc))

    def bm25_candidates(self, question: str) -> RankedCandidates:
        """Rank active nodes with BM25. Ids best-first, capped at CANDIDATE_K."""
        if self.bm25 is None:
            return RankedCandidates([], {}, None)

        try:
            hits = self.bm25.retrieve(question)
            ids: List[str] = []
            scores: Dict[str, float] = {}
            for item in hits[:CANDIDATE_K]:
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

    def retrieve(self, question: str, top_k: int = DEFAULT_TOP_K) -> RetrievalResponse:
        """Run hybrid retrieval: BM25 + vector, fused, top_k by fused score."""
        from llama_index.core.llms import MockLLM  # type: ignore
        from llama_index.core.retrievers import QueryFusionRetriever  # type: ignore

        adapter_cls = _candidate_retriever_class()
        vec_cap = _RankCapture()
        bm25_cap = _RankCapture()
        vec_r = adapter_cls(self.vector_candidates, self.node_map, vec_cap)
        bm25_r = adapter_cls(self.bm25_candidates, self.node_map, bm25_cap)

        t0 = time.perf_counter()

        # Run each arm once up front (memoized); the both-empty case returns early.
        vec_r.retrieve(question)
        bm25_r.retrieve(question)
        t_arms = time.perf_counter()

        vec = vec_cap.ranked
        bm25 = bm25_cap.ranked

        degraded = False
        degraded_reason: Optional[str] = None
        if self.load_error:
            # chunks.json missing / BM25 init failed: vector-only retrieval, say so.
            degraded = True
            degraded_reason = (
                f"index load error ({self.load_error}); degraded retrieval"
            )
        if vec.error:
            vec_reason = f"vector degraded ({vec.error}); BM25-only fusion"
            degraded = True
            degraded_reason = (
                f"{degraded_reason} | {vec_reason}" if degraded_reason else vec_reason
            )
        if bm25.error:
            bm25_reason = f"BM25 degraded ({bm25.error}); vector-only fusion"
            degraded = True
            degraded_reason = (
                f"{degraded_reason} | {bm25_reason}"
                if degraded_reason
                else bm25_reason
            )
        if not vec.ids and not bm25.ids:
            return RetrievalResponse(
                results=[],
                denied_count=0,
                denied_reasons=[],
                candidate_count=0,
                mode="hybrid",
                query=question,
                timing_ms={"retrieval_ms": (t_arms - t0) * 1000},
                degraded=True,
                degraded_reason="no candidates from vector or BM25",
            )

        candidate_count = len(set(vec.ids) | set(bm25.ids))

        # num_queries=1: fuse the original query only; MockLLM avoids Settings.llm.
        fusion = QueryFusionRetriever(
            retrievers=[vec_r, bm25_r],
            llm=MockLLM(),
            mode="reciprocal_rerank",
            similarity_top_k=top_k,
            num_queries=1,
            use_async=False,
            verbose=False,
        )
        fused_nodes = fusion.retrieve(question)

        vec_rank_index = {nid: idx + 1 for idx, nid in enumerate(vec.ids)}
        bm25_rank_index = {nid: idx + 1 for idx, nid in enumerate(bm25.ids)}
        results = []
        seen_ids: set = set()
        for nws in fused_nodes:
            nid = nws.node.id_
            if nid in seen_ids:
                # Fusion keys by node hash; keep one logical result per node_id (store content).
                continue
            # Prefer the vector store's node; fall back to BM25/chunks node or fused node.
            node = vec.nodes.get(nid) or self.node_map.get(nid) or nws.node
            seen_ids.add(nid)
            results.append(
                ScoredNode(
                    node=node,
                    vector_rank=vec_rank_index.get(nid),
                    bm25_rank=bm25_rank_index.get(nid),
                    vector_score=vec.scores.get(nid),
                    bm25_score=bm25.scores.get(nid),
                    fused_score=float(nws.score or 0.0),
                )
            )

        t_done = time.perf_counter()
        timing: Dict[str, float] = {
            "retrieval_ms": vec_cap.elapsed_ms + bm25_cap.elapsed_ms,
            "total_ms": (t_done - t0) * 1000,
        }
        return RetrievalResponse(
            results=results,
            denied_count=0,
            denied_reasons=[],
            candidate_count=candidate_count,
            mode="hybrid",
            query=question,
            timing_ms=timing,
            degraded=degraded,
            degraded_reason=degraded_reason,
        )


# The single process-lifetime instance behind the module-level retrieve() seam.
# It snapshots chunks.json text/BM25 state at first use: after re-indexing the
# KB, restart RAG workers/processes to pick up the new index.
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
    top_k: int = DEFAULT_TOP_K,
) -> RetrievalResponse:
    """Run hybrid RRF retrieval on the default instance (see _default)."""
    return _default().retrieve(question, top_k=top_k)


def retrieve_standalone(question: str, top_k: int) -> int:
    resp = retrieve(question, top_k=top_k)
    print(f"Mode: hybrid  TopK: {top_k}")
    print(f"Query: {resp.query!r}")
    print(f"Candidates: {resp.candidate_count}  Returned: {len(resp.results)}")
    if resp.degraded:
        print(f"Degraded: {resp.degraded_reason}")
    if resp.denied_reasons:
        print("Denied reasons:", " | ".join(resp.denied_reasons))
    print(f"Timing: {resp.timing_ms}")
    for idx, scored in enumerate(resp.results, start=1):
        meta = scored.node.metadata
        snippet = scored.node.text[:220].replace("\n", " ")
        print(
            f"\n[{idx}] {scored.node.id_}  fused={scored.fused_score:.4f}"
            f"  title={meta.get('title','')!r}"
            f"  nv={meta.get('needs_verification', False)}"
        )
        print(f"     {snippet}...")
        # Developer provenance
        src = meta.get("source_refs") or meta.get("sources") or []
        if src:
            print(f"     sources: {src[:2]}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Hybrid retrieval (standalone, single TMBot voice)")
    parser.add_argument("question", nargs="?", help="Question to retrieve for")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, help="Evidence passages to return")
    args = parser.parse_args()

    if not args.question:
        parser.print_help()
        return 2
    return retrieve_standalone(args.question, args.top_k)


if __name__ == "__main__":
    raise SystemExit(main())
