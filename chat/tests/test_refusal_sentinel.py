"""Single-call contract: refusals/sentinel are substituted, never retried."""

from __future__ import annotations

from chat.retrieval.guardrails import REFUSAL_TEMPLATES
from chat.retrieval.llm_answer import LLMService, _sentinel_in
from chat.retrieval.policy import LOW_CONFIDENCE_ANSWER


class _Msg:
    def __init__(self, content: str) -> None:
        self.content = content


class _Choice:
    def __init__(self, content: str) -> None:
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content: str) -> None:
        self.choices = [_Choice(content)]


def _svc_with(monkeypatch, output: str):
    import litellm

    calls = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return _Resp(output)

    monkeypatch.setattr(litellm, "completion", fake_completion)
    svc = LLMService(model="openai/test-model")
    monkeypatch.setattr(svc, "_require_key", lambda: True)
    monkeypatch.setattr(svc, "_build_messages", lambda *a, **k: ("sys", "user"))
    monkeypatch.setattr(svc, "_litellm_kwargs", lambda: {"model": "openai/test-model"})
    return svc, calls


def test_sentinel_detection_is_prefix_aware():
    assert _sentinel_in("UNSAFE_REQUEST") == "UNSAFE_REQUEST"
    assert _sentinel_in("  UNSAFE_REQUEST and more") == "UNSAFE_REQUEST"
    assert _sentinel_in("UNSAFE") is None
    assert _sentinel_in("Regular evidence answer") is None


def test_answer_maps_sentinel_with_single_call(monkeypatch):
    svc, calls = _svc_with(monkeypatch, "UNSAFE_REQUEST")

    out = svc.answer("question", [object()])

    assert out == REFUSAL_TEMPLATES["unsafe"]
    assert "UNSAFE_REQUEST" not in out
    assert len(calls) == 1


def test_answer_substitutes_refusal_copy_with_single_call(monkeypatch):
    svc, calls = _svc_with(monkeypatch, REFUSAL_TEMPLATES["out_of_scope"])

    out = svc.answer("question", [object()])

    assert out == LOW_CONFIDENCE_ANSWER
    assert len(calls) == 1


def test_answer_passes_through_normal_text_with_single_call(monkeypatch):
    svc, calls = _svc_with(monkeypatch, "Lock a task from the project page.")

    out = svc.answer("question", [object()])

    assert out == "Lock a task from the project page."
    assert len(calls) == 1
