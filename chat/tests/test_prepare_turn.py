from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from chat.retrieval.query_kb import RetrievalResponse
from chat.service import _prepare_turn


def _run(coro):
    return asyncio.run(coro)


def _empty_resp(q, top_k=5):
    return RetrievalResponse(
        results=[],
        denied_count=0,
        denied_reasons=[],
        candidate_count=1,
        mode="hybrid",
        query=q,
    )


def _collect_ok(block="Project 5: 10 tasks"):
    async def collect(user_id, route, db):
        return SimpleNamespace(
            status="OK",
            route=route.route,
            project_id=route.project_id,
            block=block,
            citations=(),
        )

    return collect


def _prepare(
    q,
    *,
    retrieve=_empty_resp,
    collect=None,
    prior=None,
    guard=None,
    persist=None,
):
    guards = guard or MagicMock(verdict="ok", gate="scope", reason="")
    patches = [patch("chat.service._persist_user_turn", new=persist or AsyncMock())]
    patches.append(patch("chat.service.retrieve", new=retrieve))
    if collect is not None:
        patches.append(patch("chat.service.collect_evidence", new=collect))
    for started in patches:
        started.start()
    try:
        return _run(
            _prepare_turn(
                q,
                5,
                {"id": 1, "user_id": 7, "message_count": 0, "title": None},
                MagicMock(),
                guards,
                user_id=7,
                prior=prior if prior is not None else [],
            )
        )
    finally:
        for started in reversed(patches):
            started.stop()


class TestPrepareTurnRouting:
    def test_domain_only_skips_kb_retrieval(self):
        def boom(*args, **kwargs):
            raise AssertionError("retrieve must not run for DOMAIN-only")

        prepared = _prepare(
            "how many tasks are in project 123?",
            retrieve=boom,
            collect=_collect_ok(),
        )
        assert prepared.resp.mode == "domain-only"
        assert prepared.resp.results == []
        assert prepared.domain_block == "Project 5: 10 tasks"
        assert prepared.domain_route_str == "DOMAIN"
        assert prepared.scope_verdict == "ok"
        assert prepared.needs_project_id is False

    def test_both_runs_kb_and_domain(self):
        seen = {}

        def capture_retrieve(q, top_k=5):
            seen["q"] = q
            return _empty_resp(q)

        async def capture_collect(user_id, route, db):
            seen["route"] = route
            return SimpleNamespace(
                status="OK",
                route=route.route,
                project_id=route.project_id,
                block="domain block",
                citations=(),
            )

        q = "how many tasks are in project 123 and how do I validate them?"
        prepared = _prepare(q, retrieve=capture_retrieve, collect=capture_collect)
        assert seen["q"] == q
        assert seen["route"].route == "BOTH"
        assert seen["route"].project_id == 123
        assert prepared.domain_block == "domain block"
        assert prepared.scope_verdict == "ok"

    def test_clarify_skips_retrieval(self):
        def boom(*args, **kwargs):
            raise AssertionError("retrieve must not run for clarify")

        prepared = _prepare("how many tasks are left in the project?", retrieve=boom)
        assert prepared.needs_project_id is True
        assert prepared.resp.mode == "clarify"

    def test_followup_merges_history_and_inherits_project_id(self):
        seen = {}

        async def capture_collect(user_id, route, db):
            seen["route"] = route
            return SimpleNamespace(
                status="OK",
                route=route.route,
                project_id=route.project_id,
                block="domain block",
                citations=(),
            )

        prior = [{"role": "user", "content": "how many tasks are in project 123?"}]
        prepared = _prepare(
            "and what about it?",
            collect=capture_collect,
            prior=prior,
            guard=MagicMock(verdict="out_of_scope", gate="scope", reason=""),
        )
        assert seen["route"].ops == ("stats",)
        assert prepared.domain_project_id == 123
        assert prepared.domain_route_str == "DOMAIN"
        assert prepared.scope_verdict == "ok"

    def test_smalltalk_prefix_stripped_for_retrieval(self):
        seen = {}
        persisted = {}

        def capture_retrieve(q, top_k=5):
            seen["q"] = q
            return _empty_resp(q)

        async def capture_persist(session_id, session, q, db):
            persisted["q"] = q

        original = "hi TMBot, how do I validate a task?"
        prepared = _prepare(
            original,
            retrieve=capture_retrieve,
            persist=capture_persist,
        )
        assert seen["q"] == "how do I validate a task?"
        assert persisted["q"] == original
        assert prepared.scope_verdict == "ok"


class TestPrepareTurnThirdParty:
    """Another user's profile ask short-circuits before domain/KB/LLM work."""

    def test_third_party_user_short_circuits(self):
        def boom_retrieve(*args, **kwargs):
            raise AssertionError("retrieve must not run for third-party asks")

        async def boom_collect(*args, **kwargs):
            raise AssertionError("collect_evidence must not run for third-party asks")

        persisted = AsyncMock()
        prepared = _prepare(
            "what badges has alice earned?",
            retrieve=boom_retrieve,
            collect=boom_collect,
            persist=persisted,
        )
        assert prepared.third_party_user is True
        assert prepared.third_party_username == "alice"
        assert prepared.resp.results == []
        assert prepared.resp.candidate_count == 0
        assert prepared.domain_block == ""
        assert prepared.citations == []
        persisted.assert_awaited_once()

    def test_third_party_generic_reference_has_no_username(self):
        def boom_retrieve(*args, **kwargs):
            raise AssertionError("retrieve must not run for third-party asks")

        prepared = _prepare(
            "how do I see another user's contributions?",
            retrieve=boom_retrieve,
        )
        assert prepared.third_party_user is True
        assert prepared.third_party_username is None

    def test_asker_profile_question_still_routes_domain(self):
        prepared = _prepare(
            "what badges have I earned?",
            collect=_collect_ok(),
        )
        assert prepared.third_party_user is False
        assert prepared.third_party_username is None
        assert prepared.domain_route_str == "DOMAIN"
        assert prepared.domain_block == "Project 5: 10 tasks"
