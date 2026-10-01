"""The pid -> summary default must not swallow procedural asks."""

from chat.retrieval.domain.routing import route_query


def test_procedural_project_question_stays_kb():
    route = route_query(
        "How do I request help or a mentor on a task I'm stuck on in project 42"
    )
    assert route.route == "KB"
    assert route.ops == ()


def test_named_project_still_defaults_to_summary():
    route = route_query("Who owns project 5?")
    assert route.route == "DOMAIN"
    assert route.ops == ("summary",)
    assert route.project_id == 5


def test_summary_keyword_with_howto_is_both():
    route = route_query("How do I see project 42's status?")
    assert route.route == "BOTH"
    assert route.ops == ("summary",)


def test_procedural_wrappers_keep_live_evidence():
    for question in (
        "How can I find out who owns project 5?",
        "How do I see the contact for project 42?",
        "Can you guide me to project 42's stats?",
    ):
        route = route_query(question)
        assert route.route == "BOTH", question
        assert route.ops == ("summary",), question
