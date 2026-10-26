"""Contract tests for the LLM router. No network, no real model.

The router's job is: one structured model call, then deterministic validation
into ``DomainRoute``. Intent classification is the model's; project ids,
filters, allowlists, and the route shape are application code.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from chat.retrieval.domain.dispatch import default_fetchers
from chat.retrieval.domain.llm_router import (
    OP_NAMES,
    PROJECT_OPS,
    DomainRoute,
    RouterConfig,
    route_question,
)
from chat.retrieval.config import get_router_config


def _run(coro):
    return asyncio.run(coro)


def _response(payload):
    content = payload if isinstance(payload, str) else json.dumps(payload)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _route(question, payload, *, history=None, completion=None):
    completion = completion or AsyncMock(return_value=_response(payload))
    with patch("chat.retrieval.domain.llm_router.litellm.acompletion", new=completion):
        route = _run(
            route_question(
                question,
                history=history or [],
                config=RouterConfig(model="test-model"),
            )
        )
    return route, completion


def _payload(ops=None, project_id=None, filters=None, needs_docs=False):
    return {
        "ops": ops or [],
        "project_id": project_id,
        "filters": filters or {},
        "needs_docs": needs_docs,
    }


def test_catalog_matches_dispatch_registry():
    assert set(OP_NAMES) == set(default_fetchers())
    assert set(PROJECT_OPS) <= set(OP_NAMES)


def test_domain_route_maps_ops_and_project():
    route, _ = _route(
        "How many tasks are in project 42?",
        _payload(ops=["stats"], project_id=42),
    )
    assert route.route == "DOMAIN"
    assert route.ops == ("stats",)
    assert route.project_id == 42
    assert route.needs_project_id is False
    assert route.filters == {}


def test_both_route_when_docs_are_needed():
    route, _ = _route(
        "How many tasks are in project 42 and how do I validate them?",
        _payload(ops=["stats"], project_id=42, needs_docs=True),
    )
    assert route.route == "BOTH"
    assert route.ops == ("stats",)
    assert route.project_id == 42


def test_kb_route_when_no_operations():
    route, _ = _route(
        "How do I validate a task?",
        _payload(ops=[], needs_docs=True),
    )
    assert route.route == "KB"
    assert route.ops == ()
    assert route.project_id is None


def test_unknown_operation_is_dropped_not_fatal():
    route, _ = _route(
        "How many tasks are in project 42?",
        _payload(ops=["stats", "invented_op"], project_id=42),
    )
    assert route.route == "DOMAIN"
    assert route.ops == ("stats",)


def test_operations_are_deduplicated_and_capped_at_four():
    route, _ = _route(
        "Tell me everything about project 42",
        _payload(
            ops=[
                "summary",
                "stats",
                "teams",
                "chat",
                "project_activity",
                "summary",
            ],
            project_id=42,
        ),
    )
    assert route.ops == ("summary", "stats", "teams", "chat")


def test_ungrounded_model_project_id_is_ignored():
    route, _ = _route(
        "How many tasks are left?",
        _payload(ops=["stats"], project_id=99),
    )
    assert route.project_id is None
    assert route.needs_project_id is True
    assert route.ops == ("stats",)


def test_question_project_id_wins_over_model_echo():
    route, _ = _route(
        "How many tasks are in project 42?",
        _payload(ops=["stats"], project_id=99),
    )
    assert route.project_id == 42


def test_two_question_project_ids_ask_for_clarification():
    route, _ = _route(
        "Compare project 42 and project 43 task counts",
        _payload(ops=["stats"], project_id=42),
    )
    assert route.project_id is None
    assert route.needs_project_id is True
    assert route.ops == ("stats",)


def test_history_supplies_the_project_id():
    history = [{"role": "user", "content": "Tell me about project 7"}]
    route, _ = _route(
        "What teams are working on it?",
        _payload(ops=["teams"]),
        history=history,
    )
    assert route.project_id == 7
    assert route.route == "DOMAIN"
    assert route.needs_project_id is False


def test_project_operation_without_any_id_asks_for_clarification():
    route, _ = _route(
        "How many tasks are left in the project?",
        _payload(ops=["stats"]),
    )
    assert route.route == "KB"
    assert route.ops == ("stats",)
    assert route.needs_project_id is True


def test_optional_project_operation_without_id_does_not_clarify():
    route, _ = _route(
        "What projects have I favorited?",
        _payload(ops=["favorites"]),
    )
    assert route.route == "DOMAIN"
    assert route.project_id is None
    assert route.needs_project_id is False


def test_filters_are_normalized_and_allowlisted():
    route, _ = _route(
        "Show me beginner projects in Nepal",
        _payload(
            ops=["project_search"],
            filters={
                "difficulty": "beginner",
                "country": "nepal",
                "unknown_key": "x",
            },
        ),
    )
    assert route.filters == {"difficulty": "EASY", "country": "Nepal"}


def test_filters_are_ignored_for_non_filter_operations():
    route, _ = _route(
        "What is the status of project 42?",
        _payload(
            ops=["summary"],
            project_id=42,
            filters={"country": "Nepal"},
        ),
    )
    assert route.filters == {}


def test_invalid_filter_values_are_dropped():
    route, _ = _route(
        "Show me projects",
        _payload(
            ops=["project_search"],
            filters={
                "difficulty": "impossible",
                "action": "delete",
                "team_id": "abc",
                "expiring_days": "0",
            },
        ),
    )
    assert route.filters == {}
    assert route.ops == ("project_search",)


def test_organisation_info_requires_its_filter():
    route, _ = _route(
        "Tell me about the HOT organisation",
        _payload(ops=["organisation_info"]),
    )
    assert route.route == "KB"
    assert route.ops == ()


def test_team_detail_requires_its_filter():
    route, _ = _route(
        "Show me team 12",
        _payload(ops=["team_detail"]),
    )
    assert route.ops == ()
    assert route.route == "KB"


def test_required_filters_keep_the_operation():
    route, _ = _route(
        "Which projects are run by HOT?",
        _payload(ops=["project_search"], filters={"organisation": "HOT"}),
    )
    assert route.ops == ("project_search",)
    assert route.filters == {"organisation": "HOT"}


def test_transport_error_falls_back_to_kb():
    completion = AsyncMock(side_effect=RuntimeError("model down"))
    route, _ = _route("How do I validate a task?", _payload(), completion=completion)
    assert route.route == "KB"
    assert route.ops == ()


def test_invalid_json_falls_back_to_kb():
    route, _ = _route("How do I validate a task?", "not json")
    assert route.route == "KB"


def test_fenced_json_is_parsed():
    payload = "```json\n" + json.dumps(_payload(ops=["stats"], project_id=42)) + "\n```"
    route, _ = _route("How many tasks are in project 42?", payload)
    assert route.ops == ("stats",)
    assert route.project_id == 42


def test_empty_question_never_calls_the_model():
    completion = AsyncMock()
    route, _ = _route("   ", _payload(), completion=completion)
    assert route.route == "KB"
    completion.assert_not_awaited()


def test_request_shape_and_prompt_catalogue():
    route, completion = _route(
        "What is the status of project 42?",
        _payload(ops=["summary"], project_id=42),
        history=[
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ],
    )
    kwargs = completion.await_args.kwargs
    assert kwargs["model"] == "test-model"
    assert kwargs["temperature"] == 0.0
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["num_retries"] == 0
    messages = kwargs["messages"]
    system = messages[0]["content"]
    assert messages[0]["role"] == "system"
    for op in OP_NAMES:
        assert op in system
    assert messages[-1] == {
        "role": "user",
        "content": "What is the status of project 42?",
    }
    assert any(message["content"] == "hello" for message in messages)
    assert route.ops == ("summary",)


def test_router_config_defaults_to_generation_model(monkeypatch):
    monkeypatch.setenv("LITELLM_MODEL", "openai/test-generation")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("GENERATION_API_BASE", "http://local/v1")
    monkeypatch.delenv("RAG_ROUTER_MODEL", raising=False)
    monkeypatch.delenv("RAG_ROUTER_API_KEY", raising=False)
    monkeypatch.delenv("RAG_ROUTER_API_BASE", raising=False)
    config = get_router_config()
    assert config.model == "openai/test-generation"
    assert config.api_key == "test-key"
    assert config.api_base == "http://local/v1"
    assert config.temperature == 0.0


def test_router_config_model_override(monkeypatch):
    monkeypatch.setenv("LITELLM_MODEL", "openai/test-generation")
    monkeypatch.setenv("RAG_ROUTER_MODEL", "openai/test-router")
    monkeypatch.setenv("RAG_ROUTER_API_KEY", "router-key")
    monkeypatch.delenv("RAG_ROUTER_API_BASE", raising=False)
    config = get_router_config()
    assert config.model == "openai/test-router"
    assert config.api_key == "router-key"


def test_router_config_override_does_not_inherit_generation_base(monkeypatch):
    monkeypatch.setenv("LITELLM_MODEL", "openai/test-generation")
    monkeypatch.setenv("GENERATION_API_BASE", "http://local/v1")
    monkeypatch.setenv("RAG_ROUTER_MODEL", "openai/gpt-4o-mini")
    monkeypatch.setenv("RAG_ROUTER_API_KEY", "router-key")
    monkeypatch.delenv("RAG_ROUTER_API_BASE", raising=False)
    config = get_router_config()
    assert config.api_base is None


def test_router_config_explicit_base_override(monkeypatch):
    monkeypatch.setenv("RAG_ROUTER_MODEL", "openai/gpt-4o-mini")
    monkeypatch.setenv("RAG_ROUTER_API_BASE", "https://api.openai.com/v1")
    monkeypatch.delenv("LITELLM_MODEL", raising=False)
    config = get_router_config()
    assert config.api_base == "https://api.openai.com/v1"


def test_build_messages_keeps_last_two_complete_turns():
    from chat.retrieval.domain.llm_router import _build_messages

    history = [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "second question"},
        {"role": "assistant", "content": "second answer"},
        {"role": "user", "content": "third question"},
        {"role": "assistant", "content": "third answer"},
    ]
    contents = [m["content"] for m in _build_messages("current", history)]
    assert "second question" in contents
    assert "second answer" in contents
    assert "third question" in contents
    assert "third answer" in contents
    assert "first question" not in contents
    assert "first answer" not in contents


def test_build_messages_does_not_truncate_history_content():
    from chat.retrieval.domain.llm_router import _build_messages

    long_answer = "x" * 2000
    history = [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": long_answer},
    ]
    contents = [m["content"] for m in _build_messages("next", history)]
    assert long_answer in contents


def test_build_messages_keeps_trailing_user_turn():
    from chat.retrieval.domain.llm_router import _build_messages

    history = [
        {"role": "user", "content": "oldest question"},
        {"role": "assistant", "content": "oldest answer"},
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "new question without a reply"},
    ]
    contents = [m["content"] for m in _build_messages("current", history)]
    assert "oldest question" not in contents
    assert "old question" in contents
    assert "new question without a reply" in contents
