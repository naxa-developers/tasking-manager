"""Scope-less platform counts route to global stats; scoped counts do not."""

from chat.retrieval.domain.routing import is_global_stats_intent, route_query

PLATFORM_COUNTS = (
    "How many projects are there?",
    "How many projects are present in Tasking Manager?",
    "How many projects do you have?",
    "What's the total number of projects?",
    "How many organisations are there?",
    "How many campaigns are there?",
    "count of projects please",
    "total projects on tasking manager",
    "How many tasks are there?",
)


def test_platform_counts_route_global_stats():
    for question in PLATFORM_COUNTS:
        route = route_query(question)
        assert route.route == "DOMAIN", question
        assert route.ops == ("global_stats",), question


def test_location_scoped_count_is_not_global():
    assert not is_global_stats_intent("how many tasks in nepal")
    assert not is_global_stats_intent("how many tasks in the project")


def test_project_scoped_count_stays_project_scoped():
    route = route_query("How many tasks are in project 123?")
    assert route.route == "DOMAIN"
    assert route.ops == ("stats",)
    assert route.project_id == 123


def test_count_stem_satisfies_project_stats():
    route = route_query("task counts for project 7")
    assert route.ops == ("stats",)
    assert route.project_id == 7


def test_counts_as_question_stays_kb():
    route = route_query("What counts as a validated task?")
    assert route.route == "KB"
    assert route.needs_project_id is False


def test_incidental_prepositions_do_not_block_platform_counts():
    for question in (
        "How many projects are there? I'm interested in contributing.",
        "How many projects are there from HOT?",
    ):
        route = route_query(question)
        assert route.route == "DOMAIN", question
        assert route.ops == ("global_stats",), question
