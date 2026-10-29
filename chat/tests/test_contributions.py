from __future__ import annotations

from chat.domain.user_contributions import UserContributionEvidence


def _evidence(**overrides) -> UserContributionEvidence:
    fields = dict(
        status="OK",
        user_id=7,
        tasks_mapped=518,
        tasks_validated=254,
        tasks_invalidated=65,
        total_hours=225.0,
        contributed_projects_total=27,
    )
    fields.update(overrides)
    return UserContributionEvidence(**fields)


def test_total_is_the_sum_of_the_recorded_actions() -> None:
    assert _evidence().contributions_total == 837


def test_total_follows_the_parts() -> None:
    assert (
        _evidence(
            tasks_mapped=10, tasks_validated=0, tasks_invalidated=0
        ).contributions_total
        == 10
    )


def test_total_is_none_when_nothing_is_known() -> None:
    evidence = _evidence(
        tasks_mapped=None, tasks_validated=None, tasks_invalidated=None
    )
    assert evidence.contributions_total is None


def test_total_ignores_unknown_parts() -> None:
    evidence = _evidence(tasks_mapped=12, tasks_validated=None, tasks_invalidated=None)
    assert evidence.contributions_total == 12


def test_total_is_rendered_before_hours() -> None:
    block = _evidence().to_prompt_block()
    assert "contributions_total_task_actions: 837" in block
    assert block.index("contributions_total_task_actions") < block.index(
        "total_contribution_hours_all_time"
    )


def test_breakdown_is_rendered_next_to_the_total() -> None:
    block = _evidence().to_prompt_block()
    assert "contributions_breakdown: 518 mapped, 254 validated, 65 invalidated" in block


def test_hours_are_still_present_for_time_questions() -> None:
    block = _evidence().to_prompt_block()
    assert "total_contribution_hours_all_time: 225.0" in block
