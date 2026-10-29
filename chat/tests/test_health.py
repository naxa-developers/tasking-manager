from __future__ import annotations

import json

import chat.health as health
from chat.api import router


def test_invalid_table_name_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("PGVECTOR_TABLE", 'bad"; DROP TABLE x;--')
    assert health._kb_table() == "data_kb_nodes"


def test_valid_table_name_is_prefixed(monkeypatch) -> None:
    monkeypatch.setenv("PGVECTOR_TABLE", "kb_nodes_tmkb600")
    assert health._kb_table() == "data_kb_nodes_tmkb600"


def test_chunks_count_reads_top_level_count(monkeypatch, tmp_path) -> None:
    path = tmp_path / "chunks.json"
    path.write_text(json.dumps({"count": 4522, "chunks": []}))
    monkeypatch.setattr(health, "_chunks_path", lambda: path)
    assert health._chunks_file_count() == 4522


def test_chunks_count_falls_back_to_list_length(monkeypatch, tmp_path) -> None:
    path = tmp_path / "chunks.json"
    path.write_text(json.dumps({"chunks": [{"id": 1}, {"id": 2}]}))
    monkeypatch.setattr(health, "_chunks_path", lambda: path)
    assert health._chunks_file_count() == 2


def test_missing_chunks_file_is_none(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(health, "_chunks_path", lambda: tmp_path / "nope.json")
    assert health._chunks_file_count() is None


def test_components_load_in_this_tree() -> None:
    """Every registry op must resolve — health reports a typo, not the turn."""
    assert health._component_error() is None


def test_health_and_ready_routes_are_mounted() -> None:
    paths = {route.path for route in router.routes}
    assert "/rag/health" in paths
    assert "/rag/ready" in paths
