"""Routing invariants for organisation and leaderboard questions."""

from chat.retrieval.domain.routing import route_query


def test_my_org_projects_routes_to_org_op():
    for phrase in (
        "What projects is my organization currently running?",
        "What projects is my organisation running?",
        "Which projects are my org running?",
    ):
        route = route_query(phrase)
        assert "user_org_projects" in route.ops, phrase


def test_org_howto_stays_kb():
    route = route_query("How do I get my organization added to Tasking Manager?")
    assert "user_org_projects" not in route.ops


def test_org_leaderboard_uses_global_stats():
    route = route_query(
        "Which countries or organizations have the most active projects?"
    )
    assert route.ops == ("global_stats",), route.ops


def test_trending_without_org_stays_trending():
    route = route_query("What are the most active/trending projects right now?")
    assert route.ops == ("trending_projects",), route.ops
