"""Discovery filter grammar: plural difficulty and 'need mapping'."""

from chat.retrieval.domain.routing import route_query


def test_plural_difficulty_routes_project_search():
    route = route_query("projects for beginners")
    assert route.route == "DOMAIN"
    assert route.ops == ("project_search",)
    assert route.filters == {"difficulty": "EASY"}


def test_need_mapping_routes_project_search_with_map_action():
    route = route_query("Which projects need mapping right now?")
    assert route.route == "DOMAIN"
    assert route.ops == ("project_search",)
    assert route.filters.get("action") == "map"


def test_count_with_difficulty_filter_stays_project_search():
    route = route_query("how many beginner projects are there?")
    assert route.route == "DOMAIN"
    assert route.ops == ("project_search",)
    assert route.filters == {"difficulty": "EASY"}
