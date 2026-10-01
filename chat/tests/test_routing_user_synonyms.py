"""Personal-data paraphrases route to live data; badge how-tos stay KB."""

from chat.retrieval.domain.routing import route_query

SYNONYM_CASES = (
    ("what's my rank", ("user_profile",)),
    ("did i get any badges yet", ("user_profile",)),
    ("any badges for me", ("user_profile",)),
    ("did i earn any badges", ("user_profile",)),
    ("am i in any teams", ("user_teams",)),
    ("how long have i been mapping for", ("user_activity",)),
    ("tasks im sitting on", ("mywork",)),
)


def test_personal_synonyms_route_domain():
    for question, ops in SYNONYM_CASES:
        route = route_query(question)
        assert route.route == "DOMAIN", question
        assert set(route.ops) == set(ops), question


def test_badge_howto_stays_kb():
    route = route_query("how do i earn badges?")
    assert route.route == "KB"
    assert route.ops == ()


def test_queue_phrasing_is_not_mywork():
    route = route_query("how many tasks are sitting on the validation queue?")
    assert "mywork" not in route.ops
