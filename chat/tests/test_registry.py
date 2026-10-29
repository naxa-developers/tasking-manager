from __future__ import annotations

from chat.domain.registry import (
    OPS,
    OPS_BY_NAME,
    PROJECT_OPS,
    prompt_catalogue,
    resolve,
)


def test_names_are_unique() -> None:
    names = [op.name for op in OPS]
    assert len(names) == len(set(names))


def test_every_op_resolves_a_callable() -> None:
    """A typo in a loader only shows up here — not at turn time."""
    for op in OPS:
        fetcher = op.load()
        assert callable(fetcher), op.name


def test_project_ops_are_project_scoped() -> None:
    for name in PROJECT_OPS:
        assert OPS_BY_NAME[name].scope == "project"


def test_filter_ops_declare_their_required_keys() -> None:
    assert OPS_BY_NAME["organisation_info"].required_filters == ("organisation",)
    assert OPS_BY_NAME["team_detail"].required_filters == ("team_id",)


def test_prompt_catalogue_lists_every_op() -> None:
    catalogue = prompt_catalogue()
    for op in OPS:
        assert f"- {op.name}:" in catalogue


def test_unknown_op_raises() -> None:
    try:
        resolve("not_an_operation")
    except KeyError:
        return
    raise AssertionError("resolve() should reject unknown operations")


def test_each_handler_accepts_the_arguments_its_scope_passes() -> None:
    """Dispatch calls by scope; a mismatch is a TypeError at turn time."""
    import inspect

    expected = {"personal": 2, "project": 3, "optional_project": 3, "filter": 4}
    for op in OPS:
        signature = inspect.signature(op.load())
        positional = [
            p
            for p in signature.parameters.values()
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        ]
        required = [p for p in positional if p.default is p.empty]
        arity = expected[op.scope]
        assert len(required) <= arity <= len(positional), (
            f"{op.name}: scope {op.scope} passes {arity} args, handler takes "
            f"{len(required)}-{len(positional)}"
        )
