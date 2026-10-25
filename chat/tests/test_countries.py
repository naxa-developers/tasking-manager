"""Country matcher: case-insensitive, multiword, allowlist-only."""

from chat.retrieval.domain.countries import find_country


def test_lowercase_and_multiword_countries():
    assert find_country("show me projects in nepal") == "Nepal"
    assert find_country("show me projects in sri lanka") == "Sri Lanka"
    assert find_country("projects from kenya") == "Kenya"


def test_benign_phrases_are_not_countries():
    assert find_country("projects in my opinion") is None
    assert find_country("a project near the border") is None


def test_definite_article_and_common_aliases():
    assert find_country("show me projects in the UK") == "United Kingdom"
    assert find_country("projects in the United States") == "United States"
    assert find_country("projects in the Netherlands") == "Netherlands"
    assert find_country("projects in the Czech Republic") == "Czechia"
    assert find_country("projects in guinea bissau") == "Guinea-Bissau"
    assert find_country("projects in timor leste") == "Timor-Leste"


def test_definite_article_does_not_create_false_positives():
    assert find_country("projects near the border") is None
    assert find_country("projects in the field") is None
