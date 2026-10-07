"""The op registry and OP_NAMES must stay in lockstep."""

from chat.retrieval.domain.dispatch import OP_NAMES, _default_fetchers


def test_op_registry_covers_all_op_names():
    assert set(_default_fetchers()) == set(OP_NAMES)


def test_created_projects_op_is_registered():
    assert "user_projects_created" in OP_NAMES
    assert "user_projects_created" in _default_fetchers()
