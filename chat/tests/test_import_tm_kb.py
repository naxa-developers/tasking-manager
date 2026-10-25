"""tm-kb -> tasking-manager chunks.json conversion and cache reuse."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chat.retrieval.scripts.import_tm_kb import (
    build_entries,
    build_entry,
    cache_key,
    collect_embeddings,
    read_chunks,
    write_chunks,
    write_embeddings,
)

COMMIT = "3050b123ba5ff17633a97b6ff8e538e414ae705d"


def _chunk(**overrides):
    chunk = {
        "id": "tm-docs/README.md#h=tasking-manager#0#c0",
        "doc_id": "README.md",
        "source_id": "tm-docs",
        "source_type": "documentation",
        "source_title": "Tasking Manager",
        "source_url": "https://github.com/hotosm/tasking-manager/blob/"
        + COMMIT
        + "/README.md",
        "source_commit": COMMIT,
        "heading": "Tasking Manager",
        "section": "Tasking Manager",
        "chunk_index": 0,
        "chunk_token_count": 155,
        "content_hash": "42686b3398acc1c6a5a8db4695470b84cc6776859b066a7712633a0f80199291",
        "audience": "end-user",
        "license": "BSD-2-Clause",
        "hard_split": False,
        "text": "Tasking Manager The most popular tool for teams to coordinate mapping.",
    }
    chunk.update(overrides)
    return chunk


def _write_cache(
    cache_dir: Path, chunk, vector, *, model="test-model", prefix="p", dims=4
):
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = cache_key(chunk["content_hash"], model, prefix, dims)
    payload = {
        "schema_version": 1,
        "content_hash": chunk["content_hash"],
        "model": model,
        "document_prefix": prefix,
        "dimensions": dims,
        "vector": vector,
    }
    (cache_dir / f"{key}.json").write_text(json.dumps(payload), encoding="utf-8")
    return key


def test_build_entry_maps_citation_metadata():
    entry = build_entry(_chunk(), 0)
    metadata = entry["metadata"]
    assert entry["id"] == "tm-docs/README.md#h=tasking-manager#0#c0"
    assert entry["doc_id"] == "tm-docs/README.md"
    assert entry["title"] == "Tasking Manager"
    assert metadata["title"] == "Tasking Manager"
    assert metadata["node_heading"] == "Tasking Manager"
    assert metadata["node_heading_path"] == "Tasking Manager"
    assert metadata["source_refs"] == [
        {
            "type": "documentation",
            "path": "https://github.com/hotosm/tasking-manager/blob/"
            + COMMIT
            + "/README.md",
        }
    ]
    assert metadata["provenance"] == {"commit": COMMIT}
    assert metadata["frozen_commit"] == COMMIT
    assert metadata["status"] == "published"
    assert metadata["needs_verification"] is False
    assert metadata["source_id"] == "tm-docs"
    assert metadata["source_doc_id"] == "README.md"
    assert metadata["content_hash"] == (
        "42686b3398acc1c6a5a8db4695470b84cc6776859b066a7712633a0f80199291"
    )


def test_build_entries_assigns_running_node_index():
    entries = build_entries(
        [
            _chunk(),
            _chunk(
                id="osm-wiki/Overpass_API#h=user#20#c0",
                doc_id="Overpass_API",
                source_id="osm-wiki",
            ),
        ]
    )
    assert [entry["node_index"] for entry in entries] == [0, 1]
    assert entries[1]["doc_id"] == "osm-wiki/Overpass_API"


def test_read_chunks_rejects_missing_text(tmp_path):
    path = tmp_path / "chunks.jsonl"
    path.write_text(json.dumps({"id": "x"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="needs id and text"):
        read_chunks(path)


def test_collect_embeddings_uses_content_hash_cache(tmp_path):
    chunks = [_chunk(), _chunk(id="second", content_hash="b" * 64)]
    entries = build_entries(chunks)
    cache = tmp_path / "cache"
    _write_cache(cache, chunks[0], [0.1, 0.2, 0.3, 0.4])
    _write_cache(cache, chunks[1], [0.5, 0.6, 0.7, 0.8])
    vectors = collect_embeddings(
        entries,
        cache,
        model="test-model",
        document_prefix="p",
        dimensions=4,
    )
    assert vectors == [[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]]


def test_collect_embeddings_reports_a_missing_vector(tmp_path):
    chunks = [_chunk()]
    entries = build_entries(chunks)
    cache = tmp_path / "cache"
    cache.mkdir()
    with pytest.raises(ValueError, match="tm-docs/README.md"):
        collect_embeddings(
            entries,
            cache,
            model="test-model",
            document_prefix="p",
            dimensions=4,
        )


def test_write_chunks_and_embeddings(tmp_path):
    chunks = [_chunk(), _chunk(id="second", content_hash="b" * 64)]
    entries = build_entries(chunks)
    out_chunks = tmp_path / "chunks.json"
    write_chunks(
        entries,
        out_chunks,
        chunks_path=Path("/tmp/source.jsonl"),
        source_sha256="a" * 64,
        chunk_tokens=600,
    )
    payload = json.loads(out_chunks.read_text(encoding="utf-8"))
    assert payload["count"] == 2
    assert payload["source_sha256"] == "a" * 64
    assert payload["chunks"][1]["id"] == "second"

    out_embeddings = tmp_path / "embeddings.npz"
    rows, dims = write_embeddings(entries, [[0.1, 0.2], [0.3, 0.4]], out_embeddings)
    assert (rows, dims) == (2, 2)

    import numpy as np

    data = np.load(out_embeddings, allow_pickle=False)
    assert [str(value) for value in data["ids"].tolist()] == [
        "tm-docs/README.md#h=tasking-manager#0#c0",
        "second",
    ]
    assert data["vectors"].shape == (2, 2)
