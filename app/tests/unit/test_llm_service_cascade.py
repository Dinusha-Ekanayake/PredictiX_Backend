"""Groq access layer: model cascade, empty replies, reasoning headroom, key rotation. No network."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.ai.services.llm_service as llm


def _reply(content, finish="stop"):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish)])


class FakeClient:
    """Answers per model from a script; records every request."""

    def __init__(self, script, calls, key):
        self.script, self.calls, self.key = script, calls, key
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append((self.key, kwargs["model"], kwargs))
        outcome = self.script.get((self.key, kwargs["model"]), self.script.get(kwargs["model"]))
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture()
def groq(monkeypatch):
    state = {"script": {}, "calls": [], "keys": ["key-a"]}
    monkeypatch.setattr(llm, "_get_api_keys", lambda: list(state["keys"]))
    monkeypatch.setattr(llm, "_get_client", lambda idx=None: (FakeClient(state["script"], state["calls"], state["keys"][idx or 0]), idx or 0))
    monkeypatch.setattr(llm, "MODEL_CASCADE", ["m-first", "openai/gpt-oss-120b", "m-last"])
    monkeypatch.setattr(llm, "DEFAULT_MODEL", "m-first")
    monkeypatch.setattr(llm, "_UNAVAILABLE_MODELS", set())
    monkeypatch.setattr(llm, "_ACTIVE_KEY_INDEX", 0)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    return state


def _models(state):
    return [m for _, m, _ in state["calls"]]


def test_the_first_working_model_answers(groq):
    groq["script"]["m-first"] = _reply("KNOWLEDGE")
    assert llm.call_groq(messages=[{"role": "user", "content": "q"}]) == ("KNOWLEDGE", "")


def test_an_empty_reply_is_never_returned_and_the_next_model_is_tried(groq):
    groq["script"]["m-first"] = _reply("", finish="length")
    groq["script"]["openai/gpt-oss-120b"] = _reply("   ")
    groq["script"]["m-last"] = _reply("DATABASE")
    assert llm.call_groq(messages=[{"role": "user", "content": "q"}])[0] == "DATABASE"
    assert _models(groq) == ["m-first", "openai/gpt-oss-120b", "m-last"]


def test_reasoning_models_get_low_effort_and_headroom(groq):
    groq["script"]["openai/gpt-oss-120b"] = _reply("ok")
    llm.call_groq(messages=[{"role": "user", "content": "q"}], model="openai/gpt-oss-120b", max_tokens=20)
    sent = groq["calls"][0][2]
    assert sent["reasoning_effort"] == "low"
    assert sent["max_tokens"] == 20 + llm.REASONING_HEADROOM


def test_ordinary_models_get_the_requested_budget(groq):
    groq["script"]["m-first"] = _reply("ok")
    llm.call_groq(messages=[{"role": "user", "content": "q"}], max_tokens=20)
    sent = groq["calls"][0][2]
    assert sent["max_tokens"] == 20 and "reasoning_effort" not in sent


def test_a_model_no_key_has_is_remembered_and_skipped(groq):
    groq["script"]["m-first"] = RuntimeError("Error code: 404 - model `m-first` does not exist")
    groq["script"]["openai/gpt-oss-120b"] = _reply("ok")
    llm.call_groq(messages=[{"role": "user", "content": "q"}])
    assert "m-first" in llm._UNAVAILABLE_MODELS
    groq["calls"].clear()
    llm.call_groq(messages=[{"role": "user", "content": "q"}])
    assert _models(groq) == ["openai/gpt-oss-120b"]


def test_a_rate_limited_key_is_rotated_for_the_same_model(groq):
    groq["keys"] = ["key-a", "key-b"]
    groq["script"][("key-a", "m-first")] = RuntimeError("Error code: 429 rate_limit_exceeded")
    groq["script"][("key-b", "m-first")] = _reply("ok")
    assert llm.call_groq(messages=[{"role": "user", "content": "q"}])[0] == "ok"
    assert [(k, m) for k, m, _ in groq["calls"]] == [("key-a", "m-first"), ("key-b", "m-first")]
    assert "m-first" not in llm._UNAVAILABLE_MODELS


def test_everything_failing_raises_with_the_last_error(groq):
    for m in ("m-first", "openai/gpt-oss-120b", "m-last"):
        groq["script"][m] = _reply("")
    with pytest.raises(RuntimeError, match="All Groq keys"):
        llm.call_groq(messages=[{"role": "user", "content": "q"}])


def test_the_cascade_can_be_configured(monkeypatch):
    monkeypatch.setenv("GROQ_MODELS", " a/one , b/two ,")
    assert llm._configured_cascade() == ["a/one", "b/two"]
    monkeypatch.delenv("GROQ_MODELS")
    assert llm._configured_cascade() == llm._DEFAULT_CASCADE


def test_the_legacy_answer_never_shows_exception_text(monkeypatch):
    def boom(**kw):
        raise RuntimeError("secret-host.internal:5432 refused")

    monkeypatch.setattr(llm, "call_groq", boom)
    out = llm.ask_llm("ctx", "q")
    assert "secret-host" not in out and "try again" in out
