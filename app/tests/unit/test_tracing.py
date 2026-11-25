"""AI audit traces: recording, clipping and safe saving. No database needed."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.ai.agent.tracing as tracing

USER = SimpleNamespace(id="33333333-3333-3333-3333-333333333333", role="user",
                       warehouse_id="11111111-1111-1111-1111-111111111111")


@pytest.fixture(autouse=True)
def _no_open_trace():
    tracing._current.set(None)
    yield
    tracing._current.set(None)


def test_recording_outside_a_trace_does_nothing():
    tracing.record("retrieval", hits=[])
    assert tracing.current_trace() is None
    assert tracing.finish_trace(answer="x") is None


def test_trace_collects_ordered_steps_and_is_saved(monkeypatch):
    saved = {}
    monkeypatch.setattr(tracing, "_save", lambda trace, answer, status: saved.update(trace=trace, answer=answer, status=status))
    trace = tracing.start_trace(channel="chatbot", user=USER, question="how do I log out")
    tracing.set_intent("FAQ")
    tracing.record("intent", intent="FAQ", decided_by="keyword rules")
    tracing.record("retrieval", hits=[{"source": "faq", "id": "1", "title": "how to log out", "score": 0.7}])
    trace_id = tracing.finish_trace(answer="Use the logout option.")

    assert trace_id == trace.trace_id and tracing.current_trace() is None
    kinds = [s["kind"] for s in saved["trace"].steps]
    assert kinds == ["intent", "retrieval", "result"]
    assert saved["trace"].intent == "FAQ" and saved["trace"].warehouse_id == USER.warehouse_id
    assert all("t_ms" in s for s in saved["trace"].steps)


def test_long_values_and_step_count_are_bounded(monkeypatch):
    monkeypatch.setattr(tracing, "_save", lambda *a: None)
    trace = tracing.start_trace(channel="chatbot", user=USER, question="q")
    tracing.record("llm_call", reply_preview="x" * 10_000, items=list(range(500)))
    step = trace.steps[0]
    assert len(step["reply_preview"]) < tracing.MAX_TEXT + 20
    assert len(step["items"]) == 50
    for _ in range(tracing.MAX_STEPS + 50):
        tracing.record("noise")
    assert len(trace.steps) == tracing.MAX_STEPS


def test_a_failed_save_never_breaks_the_answer(monkeypatch):
    class _Broken:
        def __enter__(self):
            raise RuntimeError("database down")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("app.db.session.SessionLocal", lambda: _Broken())
    tracing.start_trace(channel="chatbot", user=USER, question="q")
    assert tracing.finish_trace(answer="still answered")  # returns the id, does not raise


def test_model_calls_are_recorded_by_the_guarded_wrapper(monkeypatch):
    import app.ai.agent.guardrails as guardrails

    monkeypatch.setattr(tracing, "_save", lambda *a: None)
    monkeypatch.setattr(guardrails, "call_groq", lambda *, messages, **kw: ("reply text", ""))
    trace = tracing.start_trace(channel="chatbot", user=USER, question="q")
    guardrails.guarded_call_groq(messages=[{"role": "system", "content": "You are the table selector"},
                                           {"role": "user", "content": "q"}], model="m1")
    call = trace.steps[-1]
    assert call["kind"] == "llm_call" and call["ok"] and call["model"] == "m1"
    assert call["purpose"].startswith("You are the table selector")
    assert call["reply_preview"] == "reply text"


def test_sandbox_outcomes_are_recorded(monkeypatch):
    from app.ai.agent.safe_sql import SqlScope, UnsafeSQLError, run_scoped_query

    monkeypatch.setattr(tracing, "_save", lambda *a: None)
    trace = tracing.start_trace(channel="chatbot", user=USER, question="q")
    with pytest.raises(UnsafeSQLError):
        run_scoped_query(None, "SELECT * FROM public.profiles", SqlScope.build(user_id=None, is_admin=False, warehouse_id=None))
    step = trace.steps[-1]
    assert step["kind"] == "sql" and step["outcome"] == "refused by sandbox" and "schema" in step["reason"]
