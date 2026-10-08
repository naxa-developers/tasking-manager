"""Health/readiness payload pins for chat/health.py (no DB, no network)."""

from __future__ import annotations

import asyncio
import json

from chat import health
from chat.service import RagService


class _FakeDB:
    def __init__(self, count=5):
        self.count = count

    async def fetch_one(self, query=None, values=None):
        return {"n": self.count}


class _Cfg:
    def __init__(self, api_key="k", api_base=None):
        self.api_key = api_key
        self.api_base = api_base

    def require_api_key(self):
        if not self.api_key:
            raise RuntimeError("no key")
        return self.api_key


def _fake_stack(monkeypatch, tmp_path, *, generation=None, embedding=None, chunks=5):
    """Available RAG stack with fake providers and a chunks.json fixture."""
    monkeypatch.setattr(RagService, "is_available", staticmethod(lambda: True))
    monkeypatch.setattr(
        RagService, "unavailable_reason", staticmethod(lambda: "import boom")
    )
    monkeypatch.setattr(
        "chat.retrieval.config.get_generation_config", lambda: generation or _Cfg()
    )
    monkeypatch.setattr(
        "chat.retrieval.config.get_embedding_config", lambda: embedding or _Cfg()
    )
    path = tmp_path / "chunks.json"
    if chunks is not None:
        path.write_text(json.dumps({"count": chunks}))
    monkeypatch.setattr("chat.retrieval.query_kb.CHUNKS_PATH", path)
    monkeypatch.setenv("PGVECTOR_TABLE", "kb_nodes")
    monkeypatch.delenv("RAG_READY_REQUIRE_PROBE", raising=False)
    monkeypatch.delenv("RAG_READY_CACHE_TTL", raising=False)
    health._PROBE_CACHE.clear()
    return path


def test_unavailable_stack_reports_unavailable(monkeypatch):
    monkeypatch.setattr(RagService, "is_available", staticmethod(lambda: False))

    payload = asyncio.run(health.rag_health(_FakeDB()))

    assert payload == {
        "status": "unavailable",
        "reason": "RAG components failed to load; see server logs",
    }


def test_empty_index_reports_unavailable(monkeypatch, tmp_path):
    _fake_stack(monkeypatch, tmp_path)

    payload = asyncio.run(health.rag_health(_FakeDB(count=0)))

    assert payload["status"] == "unavailable"
    assert "KB index empty" in payload["reason"]
    assert payload["indexed_nodes"] == 0


def test_healthy_payload_with_matching_chunks(monkeypatch, tmp_path):
    _fake_stack(monkeypatch, tmp_path, chunks=5)

    payload = asyncio.run(health.rag_health(_FakeDB(count=5)))

    assert payload["status"] == "ok"
    assert payload["indexed_nodes"] == 5
    assert payload["table"] == "kb_nodes"
    assert payload["generation"] == "configured"
    assert payload["embedding"] == "configured"
    assert payload["chunks_file_count"] == 5
    assert payload["index_mismatch"] is False
    assert "bm25" not in payload
    assert "reason" not in payload


def test_mismatched_chunks_make_readiness_not_ready(monkeypatch, tmp_path):
    _fake_stack(monkeypatch, tmp_path, chunks=4)

    health_payload = asyncio.run(health.rag_health(_FakeDB(count=5)))
    ready_payload = asyncio.run(health.rag_readiness(_FakeDB(count=5)))

    assert health_payload["status"] == "ok"
    assert health_payload["index_mismatch"] is True
    assert ready_payload["status"] == "not_ready"
    assert (
        "chunks.json missing or out of sync with the pgvector index"
        in ready_payload["reasons"]
    )


def test_missing_provider_key_degrades(monkeypatch, tmp_path):
    _fake_stack(monkeypatch, tmp_path, generation=_Cfg(api_key=None))

    payload = asyncio.run(health.rag_health(_FakeDB()))

    assert payload["status"] == "degraded"
    assert payload["generation"] == "missing_key"
    assert payload["embedding"] == "configured"
    assert payload["reason"] == "generation key missing"


def test_missing_chunks_file_marks_bm25_unavailable(monkeypatch, tmp_path):
    _fake_stack(monkeypatch, tmp_path, chunks=None)

    payload = asyncio.run(health.rag_health(_FakeDB()))
    ready_payload = asyncio.run(health.rag_readiness(_FakeDB()))

    assert payload["status"] == "ok"
    assert payload["bm25"] == "unavailable (chunks.json missing)"
    assert "index_mismatch" not in payload
    assert ready_payload["status"] == "not_ready"


def test_ready_when_healthy_and_probes_skipped(monkeypatch, tmp_path):
    _fake_stack(monkeypatch, tmp_path, chunks=5)

    payload = asyncio.run(health.rag_readiness(_FakeDB(count=5)))

    assert payload["status"] == "ready"
    assert payload["reasons"] == []
    assert payload["checks"]["generation_probe"] == "skipped (no api_base)"
    assert payload["checks"]["embedding_probe"] == "skipped (no api_base)"
    assert payload["checks"]["health"]["indexed_nodes"] == 5


def test_kb_table_validates_env_name(monkeypatch):
    monkeypatch.setenv("PGVECTOR_TABLE", "custom_table")
    assert health._kb_table() == "data_custom_table"

    monkeypatch.setenv("PGVECTOR_TABLE", "bad name; drop")
    assert health._kb_table() == "data_kb_nodes"
