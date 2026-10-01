"""Explanatory sub-clauses next to a live op keep KB evidence (BOTH)."""

from chat.retrieval.domain.routing import route_query

BOTH_CASES = (
    (
        "What's my mapper level, and what do I need to reach the next one?",
        ("user_profile",),
    ),
    (
        "Which projects are beginner-friendly / match my skill level?",
        ("project_search",),
    ),
    (
        "What's project 42's difficulty level and required editor (iD or JOSM)?",
        ("summary",),
    ),
    (
        "Recommend a project based on what I usually map.",
        ("user_recommendations",),
    ),
    (
        "Why was my last task invalidated, what did the validator say?",
        ("user_tasks",),
    ),
    (
        "Who's the contact for project 42?",
        ("summary",),
    ),
    (
        "What does '% validated' mean, and what is project 42's validated percentage?",
        ("stats",),
    ),
    (
        "Recommend a project for me. (new account, nothing mapped yet)",
        ("user_recommendations",),
    ),
)

DOMAIN_ONLY_CASES = (
    ("How many tasks have I mapped so far?", ("user_contributions",)),
    ("recommend a task for me", ("user_recommendations",)),
    ("suggest a project i should map", ("user_recommendations",)),
    ("What is project 42?", ("summary",)),
)


def test_explanatory_questions_keep_kb_evidence():
    for question, ops in BOTH_CASES:
        route = route_query(question)
        assert route.route == "BOTH", question
        assert set(route.ops) == set(ops), question


def test_plain_live_questions_stay_domain_only():
    for question, ops in DOMAIN_ONLY_CASES:
        route = route_query(question)
        assert route.route == "DOMAIN", question
        assert set(route.ops) == set(ops), question
