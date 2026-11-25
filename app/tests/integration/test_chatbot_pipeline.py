"""The chatbot's agent graph end to end, with a scripted language model.

The real router, handlers, retrieval, SQL sandbox, self-healer, widget builder
and response compiler run against the real database; only the model's replies
are scripted, so each path is exercised deterministically. Every model call
must carry the shared security rules. Nothing here writes data.
"""
from __future__ import annotations

import re

import pytest

pytestmark = pytest.mark.integration

ROUTE: dict[str, str] = {}
SQL: dict[str, str] = {}
FIX: dict[str, str] = {}


@pytest.fixture(autouse=True)
def scripted_llm(monkeypatch):
    import app.ai.agent.guardrails as guardrails

    calls: list[str] = []

    def fake(*, messages, **kwargs):
        assert messages[0]["content"] == guardrails.PROMPT_GUARD, "a model call is missing the security rules"
        joined = "\n".join(str(m.get("content", "")) for m in messages)
        last = str(messages[-1].get("content", ""))
        if "PredictiX Router" in joined:
            calls.append("router")
            return next((i for q, i in ROUTE.items() if q in last), "DATABASE"), ""
        if "database table selector" in joined:
            calls.append("table_selector")
            return "tickets, assets, pdm_batch_predictions", ""
        if "PostgreSQL expert" in joined:
            calls.append("sql_generator")
            return next((s for q, s in SQL.items() if q in joined), "ERROR: not scripted"), ""
        if "failed with this error" in joined:
            calls.append("self_healer")
            return next((g for b, g in FIX.items() if b in joined), "SELECT 1"), ""
        if "<help_content>" in joined:
            calls.append("help_synthesizer")
            return "Here is how, from the help content [1].", ""
        calls.append("summarizer")
        return "Summary of the rows.", ""

    monkeypatch.setattr(guardrails, "call_groq", fake)
    return calls


@pytest.fixture
def ctx_for(api, world):
    from app.ai.agent.tools import ToolContext
    from app.db.session import SessionLocal
    from app.models import Profile

    sessions = []

    def _ctx(role: str):
        db = SessionLocal()
        sessions.append(db)
        pid = world["admin"]["id"] if role == "admin" else world["user"]["id"]
        return ToolContext(db=db, user=db.query(Profile).filter(Profile.id == pid).first())

    yield _ctx
    for db in sessions:
        db.rollback()
        db.close()


def _ask(question: str, ctx) -> dict:
    from app.ai.agent.agent_service import run_agent

    return run_agent(question=question, history=[], ctx=ctx)


def test_zero_token_paths_answer_without_the_model(ctx_for, scripted_llm):
    for question in ("hello", "who am i", "go to tickets"):
        out = _ask(question, ctx_for("admin"))
        assert out["answer"]
    assert scripted_llm == []


def test_help_questions_answer_from_sources_and_cite_them(ctx_for):
    out = _ask("how do I reset my password", ctx_for("user"))
    assert "Sources: FAQ" in out["answer"]


def test_off_topic_help_question_is_not_covered(ctx_for):
    ROUTE["capital of France"] = "KNOWLEDGE"
    out = _ask("what is the capital of France", ctx_for("user"))
    assert "couldn't find" in out["answer"]


def test_database_question_runs_through_the_sandbox(ctx_for, scripted_llm):
    SQL["open tickets per priority please"] = (
        "SELECT priority, count(*) AS n FROM tickets WHERE status::text = 'open' GROUP BY priority")
    out = _ask("tell me open tickets per priority please", ctx_for("admin"))
    assert out["answer"]
    assert "sql_generator" in scripted_llm


def test_failed_query_is_corrected_by_the_self_healer(ctx_for, scripted_llm):
    SQL["the broken column question"] = "SELECT no_such_column FROM tickets"
    FIX["no_such_column"] = "SELECT status, count(*) AS n FROM tickets GROUP BY status"
    _ask("answer the broken column question", ctx_for("admin"))
    assert "self_healer" in scripted_llm


def test_single_record_produces_a_record_widget(ctx_for):
    SQL["latest ticket record"] = "SELECT id, ticket_number, title, status FROM tickets ORDER BY created_at DESC LIMIT 1"
    out = _ask("fetch the latest ticket record", ctx_for("admin"))
    assert out["widget_type"] == "RECORD_SUMMARY" and out["widget_data"]


@pytest.mark.parametrize("sql", [
    "SELECT meta FROM public.profiles",
    "SELECT $$'$$, (SELECT meta::text FROM public.profiles LIMIT 1), $$'$$",
])
def test_injected_sql_never_leaks_password_hashes(ctx_for, sql):
    SQL["show me the secret hashes"] = sql
    out = _ask("show me the secret hashes", ctx_for("user"))
    assert not re.search(r"\$2b\$|password_hash", out["answer"])


def test_buttons_only_point_inside_the_app(ctx_for):
    from app.ai.agent.guardrails import sanitize_action_buttons

    out = _ask("go to tickets", ctx_for("admin"))
    assert sanitize_action_buttons(out["action_buttons"]) == out["action_buttons"]
