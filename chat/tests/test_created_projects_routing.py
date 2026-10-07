"""Routing invariants for authored ("created") project questions.

Authorship is its own capability: it must never be answered from mapping or
validation contribution evidence, and vice versa.
"""

from chat.retrieval.domain.routing import (
    discovery_filters,
    is_user_created_projects_intent,
    route_query,
)

CREATED_PHRASES = (
    "how many projects have i created?",
    "how many projects did i create?",
    "which projects did i create",
    "what projects have i created",
    "projects created by me",
    "show me the projects i created",
    "my created projects",
    "how many projects do i own?",
)

CONTRIBUTION_PHRASES = (
    "how many projects have i mapped?",
    "which projects have i worked on?",
    "what projects have i contributed to?",
)


def test_created_phrases_route_to_created_op():
    for phrase in CREATED_PHRASES:
        route = route_query(phrase)
        assert route.ops == ("user_projects_created",), phrase


def test_contribution_phrases_never_route_to_created_op():
    for phrase in CONTRIBUTION_PHRASES:
        route = route_query(phrase)
        assert "user_contributions" in route.ops, phrase
        assert "user_projects_created" not in route.ops, phrase


def test_created_intent_requires_first_person():
    assert not is_user_created_projects_intent("how do i create a project?")
    assert not is_user_created_projects_intent("steps to create a project")


def test_howto_project_creation_stays_kb():
    route = route_query("how do i create a project?")
    assert route.ops == ()


def test_bare_my_projects_stays_ambiguous():
    for phrase in ("my projects", "show me my projects", "list my projects"):
        route = route_query(phrase)
        assert "user_projects_created" not in route.ops, phrase


def test_created_by_me_is_not_an_organisation_filter():
    filters = discovery_filters("projects created by me")
    assert "organisation" not in filters
