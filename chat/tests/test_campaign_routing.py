"""Routing invariants for campaign project-search questions (P1).

Both the front ("campaign <name>") and trailing ("<name> campaign") forms
must yield a project_search route with a campaign filter; prose that merely
mentions the word "campaign" must not.
"""

from chat.retrieval.domain.routing import discovery_filters, route_query

TRAILING_PHRASES = (
    "Which projects are in the Test campaign?",
    "Which projects are part of the Test campaign?",
    "Find the Test campaign projects",
    "tell me about the Test campaign",
)

FRONT_PHRASES = (
    "Show me projects in campaign Test",
    "projects in the campaign called Test",
    "projects in the campaign named Test",
)

PROSE_PHRASES = (
    "how do i create a campaign?",
    "what is a campaign",
    "show me the campaign",
    "my organization added to Tasking Manager",
)


def test_trailing_campaign_routes_project_search_with_filter():
    for phrase in TRAILING_PHRASES:
        route = route_query(phrase)
        assert route.ops == ("project_search",), phrase
        assert route.route == "DOMAIN", phrase
        assert discovery_filters(phrase) == {"campaign": "Test"}, phrase


def test_front_campaign_still_routes_project_search_with_filter():
    for phrase in FRONT_PHRASES:
        route = route_query(phrase)
        assert route.ops == ("project_search",), phrase
        assert discovery_filters(phrase) == {"campaign": "Test"}, phrase


def test_campaign_prose_has_no_campaign_filter():
    for phrase in PROSE_PHRASES:
        assert "campaign" not in discovery_filters(phrase), phrase


def test_r32_verbatim():
    route = route_query("Which projects are in the Test campaign?")
    assert route.ops == ("project_search",)
    assert route.filters == {"campaign": "Test"}
