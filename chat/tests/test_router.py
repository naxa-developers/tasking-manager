from __future__ import annotations

from chat.router import RouterOutput, _validate_output


def decide(**payload):
    return _validate_output(RouterOutput.model_validate(payload))


def test_kb_route_ignores_ops() -> None:
    decision = decide(route="KB", ops=["stats"])
    assert decision.route == "KB"
    assert decision.ops == ()


def test_unknown_ops_are_dropped() -> None:
    decision = decide(route="DOMAIN", ops=["stats", "drop_database"], project_id=42)
    assert decision.ops == ("stats",)


def test_domain_route_without_ops_falls_back_to_kb() -> None:
    decision = decide(route="DOMAIN", ops=[])
    assert decision.route == "KB"


def test_project_op_without_project_id_is_not_runnable() -> None:
    decision = decide(route="DOMAIN", ops=["stats"], project_id=None)
    assert decision.route == "KB"
    assert decision.degraded is True


def test_project_op_with_project_id_runs() -> None:
    decision = decide(route="DOMAIN", ops=["stats"], project_id=42)
    assert decision.route == "DOMAIN"
    assert decision.ops == ("stats",)
    assert decision.project_id == 42


def test_personal_op_needs_no_project() -> None:
    decision = decide(route="DOMAIN", ops=["mywork"])
    assert decision.ops == ("mywork",)
    assert decision.project_id is None


def test_both_route_keeps_kb_and_domain() -> None:
    decision = decide(route="BOTH", ops=["user_contributions"])
    assert decision.route == "BOTH"
    assert decision.wants_kb is True
    assert decision.wants_domain is True


def test_string_project_id_is_coerced() -> None:
    decision = decide(route="DOMAIN", ops=["stats"], project_id="project 4212")
    assert decision.project_id == 4212


def test_boolean_project_id_is_rejected() -> None:
    decision = decide(route="DOMAIN", ops=["stats"], project_id=True)
    assert decision.project_id is None


def test_filters_are_allowlisted_per_op() -> None:
    decision = decide(
        route="DOMAIN",
        ops=["project_search"],
        filters={"country": "Nepal", "team_id": "7"},
    )
    assert decision.filters == {"country": "Nepal"}


def test_filters_are_dropped_when_no_filter_op_selected() -> None:
    decision = decide(
        route="DOMAIN", ops=["stats"], project_id=1, filters={"country": "Nepal"}
    )
    assert decision.filters == {}


def test_organisation_info_without_filter_is_not_runnable() -> None:
    decision = decide(route="DOMAIN", ops=["organisation_info"], filters={})
    assert decision.route == "KB"
    assert decision.degraded is True


def test_difficulty_synonym_is_normalized() -> None:
    decision = decide(
        route="DOMAIN", ops=["project_search"], filters={"difficulty": "beginner"}
    )
    assert decision.filters == {"difficulty": "EASY"}


def test_route_is_uppercased() -> None:
    decision = decide(route="both", ops=["user_contributions"])
    assert decision.route == "BOTH"


def test_garbage_route_is_kb() -> None:
    decision = decide(route="SQL", ops=["stats"])
    assert decision.route == "KB"


def test_out_of_scope_is_terminal() -> None:
    decision = decide(route="OUT_OF_SCOPE", ops=["stats"], project_id=42)
    assert decision.route == "OUT_OF_SCOPE"
    assert decision.ops == ()
    assert decision.project_id is None
    assert decision.is_out_of_scope is True
    assert decision.wants_kb is False
    assert decision.wants_domain is False
