"""Pins for chunks.json loading and vector-candidate parsing (pre-refactor)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from llama_index.core.schema import TextNode

from chat.retrieval.query_kb import Retriever, load_nodes


def _write(tmp_path, payload):
    path = tmp_path / "chunks.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class TestLoadNodes:
    def test_list_payload_preserves_embedding(self, tmp_path):
        path = _write(
            tmp_path,
            [
                {
                    "id": "n1",
                    "text": "hello",
                    "metadata": {"title": "T"},
                    "embedding": [0.1, 0.2],
                }
            ],
        )
        nodes = load_nodes(path)
        assert [n.id_ for n in nodes] == ["n1"]
        assert nodes[0].text == "hello"
        assert nodes[0].metadata == {"title": "T"}
        assert nodes[0].embedding == [0.1, 0.2]

    def test_chunks_wrapper_payload(self, tmp_path):
        path = _write(tmp_path, {"chunks": [{"id": "n1", "text": "hello"}]})
        nodes = load_nodes(path)
        assert [n.id_ for n in nodes] == ["n1"]

    def test_metadata_falls_back_to_entry_fields(self, tmp_path):
        path = _write(tmp_path, [{"id": "n1", "text": "hello", "title": "T"}])
        nodes = load_nodes(path)
        assert nodes[0].metadata == {"title": "T"}

    def test_non_object_entry_skipped_with_warning(self, tmp_path):
        path = _write(tmp_path, [42])
        with pytest.warns(UserWarning, match=r"entry #0 is not an object; skipping"):
            nodes = load_nodes(path)
        assert nodes == []

    def test_unrebuildable_entry_skipped_with_warning(self, tmp_path):
        path = _write(tmp_path, [{"id": {"k": 1}, "text": "x"}])
        with pytest.warns(UserWarning, match=r"entry #0 could not be rebuilt"):
            nodes = load_nodes(path)
        assert nodes == []

    def test_bad_json_raises_value_error(self, tmp_path):
        path = tmp_path / "chunks.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError, match="not valid JSON"):
            load_nodes(path)

    def test_non_list_payload_raises_value_error(self, tmp_path):
        path = _write(tmp_path, {"other": []})
        with pytest.raises(ValueError, match="must be a list"):
            load_nodes(path)


class _Embed:
    def get_query_embedding(self, question):
        return [0.1, 0.2]


class _Store:
    def __init__(self, res):
        self.res = res

    def query(self, vector_store_query):
        return self.res


def _retriever(res, node_map=None):
    return Retriever(
        [],
        node_map if node_map is not None else {},
        None,
        embed_model=_Embed(),
        vector_store=_Store(res),
    )


def _node(nid, status="active"):
    return TextNode(text=f"text {nid}", id_=nid, metadata={"status": status})


class TestVectorCandidates:
    def test_ids_and_similarities_shape(self):
        res = SimpleNamespace(ids=["a", "b"], similarities=[0.9, 0.8], nodes=[])
        ret = _retriever(res, {"a": _node("a"), "b": _node("b")})
        cand = ret.vector_candidates("q")
        assert cand.ids == ["a", "b"]
        assert cand.scores == {"a": 0.9, "b": 0.8}
        assert set(cand.nodes) == {"a", "b"}
        assert cand.error is None

    def test_nodes_only_shape_uses_score(self):
        item = SimpleNamespace(node=_node("n1"), score=0.7)
        res = SimpleNamespace(nodes=[item])
        ret = _retriever(res, {"n1": _node("n1")})
        cand = ret.vector_candidates("q")
        assert cand.ids == ["n1"]
        assert cand.scores == {"n1": 0.7}

    def test_store_node_wins_over_node_map_for_activity(self):
        item = SimpleNamespace(node=_node("a", status="archived"), score=0.5)
        res = SimpleNamespace(nodes=[item])
        ret = _retriever(res, {"a": _node("a")})
        cand = ret.vector_candidates("q")
        assert cand.ids == []
        assert cand.error is None

    def test_inactive_node_filtered(self):
        res = SimpleNamespace(ids=["a", "b"], similarities=[0.9, 0.8], nodes=[])
        ret = _retriever(res, {"a": _node("a"), "b": _node("b", status="archived")})
        cand = ret.vector_candidates("q")
        assert cand.ids == ["a"]

    def test_empty_store_with_loaded_index_flags_error(self):
        res = SimpleNamespace(ids=[], similarities=[], nodes=[])
        ret = _retriever(res, {"a": _node("a")})
        cand = ret.vector_candidates("q")
        assert cand.ids == []
        assert cand.error == "vector store returned no candidates (index empty?)"

    def test_empty_store_without_node_map_is_silent(self):
        res = SimpleNamespace(ids=[], similarities=[], nodes=[])
        ret = _retriever(res, {})
        cand = ret.vector_candidates("q")
        assert cand.ids == []
        assert cand.error is None

    def test_missing_handles_returns_vector_error(self):
        ret = Retriever(
            [],
            {},
            None,
            embed_model=None,
            vector_store=None,
            vector_error="no store",
        )
        cand = ret.vector_candidates("q")
        assert cand.error == "no store"
