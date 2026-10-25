"""index_kb precomputed-vector loading and offline dry-run."""

from __future__ import annotations

import json

import numpy as np
import pytest

from chat.retrieval.scripts.index_kb import (
    _attach_embeddings,
    _load_embeddings,
    main,
)


def _npz(path, ids, vectors):
    np.savez_compressed(
        path,
        ids=np.asarray(ids, dtype=str),
        vectors=np.asarray(vectors, dtype=np.float32),
    )
    return path


def test_load_embeddings_maps_ids_and_dimension(tmp_path):
    path = _npz(tmp_path / "e.npz", ["a", "b"], [[1, 2, 3], [4, 5, 6]])
    vectors, dims = _load_embeddings(path)
    assert dims == 3
    assert vectors["a"] == [1.0, 2.0, 3.0]
    assert vectors["b"] == [4.0, 5.0, 6.0]


def test_load_embeddings_rejects_duplicate_ids(tmp_path):
    path = _npz(tmp_path / "e.npz", ["a", "a"], [[1, 2], [3, 4]])
    with pytest.raises(ValueError, match="duplicate"):
        _load_embeddings(path)


def test_attach_embeddings_requires_every_node():
    class Node:
        id_ = "a"

    node = Node()
    _attach_embeddings([node], {"a": [1.0, 2.0]})
    assert node.embedding == [1.0, 2.0]

    with pytest.raises(ValueError, match="no precomputed vector"):
        _attach_embeddings([Node()], {})


def _write_chunks(path):
    payload = {
        "count": 2,
        "chunks": [
            {"id": "a", "text": "alpha", "metadata": {"title": "A"}},
            {"id": "b", "text": "beta", "metadata": {"title": "B"}},
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_dry_run_with_precomputed_vectors_is_offline(tmp_path):
    chunks = _write_chunks(tmp_path / "chunks.json")
    embeddings = _npz(tmp_path / "e.npz", ["a", "b"], [[1, 2], [3, 4]])
    assert (
        main(
            [
                "--chunks",
                str(chunks),
                "--embeddings",
                str(embeddings),
                "--dry-run",
            ]
        )
        == 0
    )


def test_dry_run_fails_when_a_vector_is_missing(tmp_path):
    chunks = _write_chunks(tmp_path / "chunks.json")
    embeddings = _npz(tmp_path / "e.npz", ["a"], [[1, 2]])
    assert (
        main(
            [
                "--chunks",
                str(chunks),
                "--embeddings",
                str(embeddings),
                "--dry-run",
            ]
        )
        == 2
    )
