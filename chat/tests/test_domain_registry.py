"""The op registry must cover exactly the closed op vocabulary."""

from chat.retrieval.domain.dispatch import default_fetchers

_EXPECTED_OPS = frozenset(
    {
        "stats",
        "summary",
        "teams",
        "chat",
        "project_activity",
        "project_annotations",
        "similar_projects",
        "campaigns",
        "organisation_info",
        "team_detail",
        "user_interests",
        "user_osm_stats",
        "notifications",
        "project_partners",
        "featured_projects",
        "active_projects",
        "project_contributions",
        "project_tasks",
        "mywork",
        "user_profile",
        "user_contributions",
        "user_projects_created",
        "user_org_projects",
        "user_activity",
        "user_teams",
        "user_tasks",
        "favorites",
        "global_stats",
        "project_search",
        "trending_projects",
        "user_recommendations",
    }
)


def test_op_registry_covers_all_op_names():
    assert set(default_fetchers()) == _EXPECTED_OPS


def test_created_projects_op_is_registered():
    assert "user_projects_created" in default_fetchers()
