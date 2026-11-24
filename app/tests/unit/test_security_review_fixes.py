"""Regression tests for issues found in the security review. No database needed."""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

os.environ.setdefault("JWT_SECRET", "unit-test-secret-not-used-anywhere-else")

from app.ai.agent.safe_sql import (  # noqa: E402
    SqlScope,
    UnsafeSQLError,
    build_scope_statements,
    validate_generated_sql,
)

WH = "11111111-1111-1111-1111-111111111111"


@pytest.mark.parametrize("sql", [
    # String forms that hide a subquery from a naive '...' stripper.
    "SELECT $$'$$, (SELECT string_agg(meta::text,',') FROM public.profiles), $$'$$",
    "SELECT E'\\'', (SELECT string_agg(meta::text,',') FROM public.profiles), E'\\''",
    "SELECT U&'\\0061' AS x",
    "SELECT B'101', X'1F'",
    # Functions that run SQL held in a string, or are not on the allowlist.
    "SELECT word FROM ts_stat('select to_tsvector(meta::text) from public.profiles')",
    "SELECT query_to_xml('select 1', true, true, '')",
    'SELECT "pg_read_file"(\'x\')',
    "SELECT row_to_json(p) FROM profiles p",
    "SELECT 'unterminated FROM tickets",
])
def test_review_bypasses_are_rejected(sql):
    with pytest.raises(UnsafeSQLError):
        validate_generated_sql(sql)


@pytest.mark.parametrize("sql", [
    "SELECT title FROM tickets WHERE title ILIKE '%brake%' OR description ILIKE '%10:30%'",
    "SELECT date_trunc('month', created_at) AS m, count(*) FROM tickets GROUP BY 1",
    "SELECT CAST(avg(health_score) AS numeric(10,2)) FROM pdm_batch_predictions",
    "SELECT extract(year FROM created_at), count(*) FILTER (WHERE status::text = 'open') FROM tickets GROUP BY 1",
    "WITH t AS (SELECT priority, count(*) n FROM tickets GROUP BY priority) SELECT priority, rank() OVER (ORDER BY n DESC) FROM t",
    "SELECT count(*) FROM tickets WHERE status::text IN ('open','in_progress') AND title <> 'it''s fine'",
    "SELECT asset_name FROM assets WHERE description ILIKE '%$100%'",
])
def test_ordinary_generated_queries_still_pass(sql):
    assert validate_generated_sql(sql)


def test_admin_without_a_warehouse_sees_nothing():
    sql = build_scope_statements(
        SqlScope.build(user_id=None, is_admin=True, warehouse_id=None),
        {"assets": ["id", "warehouse_id", "assigned_to"]},
    )
    assert "WHERE FALSE" in sql and "WHERE TRUE" not in sql


def test_image_type_comes_from_the_file_bytes():
    from app.services.image_upload_service import image_extension as _image_extension

    assert _image_extension(b"\xff\xd8\xff\xe0rest") == "jpg"
    assert _image_extension(b"\x89PNG\r\n\x1a\nrest") == "png"
    assert _image_extension(b"GIF89a....") == "gif"
    assert _image_extension(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "webp"
    assert _image_extension(b"<svg xmlns='http://www.w3.org/2000/svg'>") is None
    assert _image_extension(b"<html><script>") is None


@pytest.mark.parametrize("path,ok", [
    ("/admin/assets?asset_id=1", True),
    ("//evil.example", False),
    ("https://evil.example", False),
    ("javascript:alert(1)", False),
    (None, False),
])
def test_notification_links_stay_in_the_app(path, ok):
    from app.ai.agent.guardrails import is_in_app_path

    assert is_in_app_path(path) is ok


def test_account_fields_are_validated():
    from app.deps import validate_account_fields

    with pytest.raises(HTTPException):
        validate_account_fields(None, None, role="owner")
    with pytest.raises(HTTPException):
        validate_account_fields(None, None, status="deleted")
    validate_account_fields(None, None, role="admin", status="active")


def test_admin_cannot_clear_a_users_warehouse():
    from app.deps import assert_can_assign

    admin = SimpleNamespace(id="a", role="admin", warehouse_id=WH)
    with pytest.raises(HTTPException) as exc:
        assert_can_assign(admin, clears_warehouse=True)
    assert exc.value.status_code == 403
    assert_can_assign(SimpleNamespace(id="s", role="super_admin", warehouse_id=WH), clears_warehouse=True)


def test_super_admin_selection_survives_a_reload():
    from app.deps import active_warehouse_id

    user = SimpleNamespace(role="super_admin", warehouse_id="home", _active_warehouse_id=WH)
    assert active_warehouse_id(user) == WH


def test_attachment_urls_fail_closed_without_storage(monkeypatch):
    from app.core.storage import is_project_storage_url

    monkeypatch.delenv("SUPABASE_URL", raising=False)
    assert not is_project_storage_url("https://anything.example/x.png")
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    assert is_project_storage_url("https://proj.supabase.co/storage/v1/object/public/ticket-attachments/a.png")
    assert not is_project_storage_url("https://other.supabase.co/storage/v1/object/public/x/a.png")


def test_chatbot_context_never_widens_to_all_warehouses():
    from app.ai.agent.tools import NO_WAREHOUSE, ToolContext

    homeless = ToolContext(db=None, user=SimpleNamespace(id="u", role="admin", warehouse_id=None))
    assert homeless.warehouse_id is None
    assert homeless.scope_warehouse_id == NO_WAREHOUSE

    chosen = ToolContext(db=None, user=SimpleNamespace(id="s", role="super_admin", warehouse_id="home", _active_warehouse_id=WH))
    assert chosen.warehouse_id == WH and chosen.scope_warehouse_id == WH


def test_chatbot_orm_scoping_fails_closed_for_an_admin_without_a_warehouse():
    from sqlalchemy.dialects import postgresql

    from app.ai.agent.scoping import scope_asset_query
    from app.ai.agent.tools import ToolContext
    from app.models import Asset
    from sqlalchemy.orm import Query

    ctx = ToolContext(db=None, user=SimpleNamespace(id="u", role="admin", warehouse_id=None))
    sql = str(scope_asset_query(Query(Asset), ctx).statement.compile(dialect=postgresql.dialect()))
    assert "false" in sql.lower()


# ── help answers (RAG) ────────────────────────────────────────────────────────

_HITS = [
    {"source": "faq", "title": "how to reset my password", "content": "Contact the admins.", "similarity": 0.64},
    {"source": "article", "title": "Brake Health", "content": "Brakes are safety-critical.", "similarity": 0.4},
]


def _help_ctx():
    from app.ai.agent.tools import ToolContext

    return ToolContext(db=None, user=SimpleNamespace(id="u", role="user", warehouse_id=WH, full_name="Ann Lee"))


def test_help_answer_with_nothing_relevant_says_not_covered():
    from app.ai.agent.tools import answer_from_help

    out = answer_from_help("anything", _help_ctx(), [])
    assert "couldn't find" in out["answer"]


def test_help_answer_cites_sources_and_fences_content(monkeypatch):
    import app.ai.agent.guardrails as guardrails
    from app.ai.agent.tools import answer_from_help

    seen = {}

    def fake(*, messages, **kw):
        seen["m"] = messages
        return "Here is how.", ""

    monkeypatch.setattr(guardrails, "call_groq", fake)
    out = answer_from_help("reset password?", _help_ctx(), _HITS)
    # Brake Health (0.40) is far below the best match (0.64), so it is neither
    # sent to the model nor cited.
    assert "Sources: FAQ: how to reset my password*" in out["answer"]
    assert "Brake Health" not in seen["m"][-1]["content"]
    assert "<help_content>" in seen["m"][-1]["content"]
    assert seen["m"][0]["content"] == guardrails.PROMPT_GUARD


def test_help_answer_not_found_from_model_is_reported_honestly(monkeypatch):
    import app.ai.agent.guardrails as guardrails
    from app.ai.agent.tools import answer_from_help

    monkeypatch.setattr(guardrails, "call_groq", lambda **kw: ("NOT_FOUND", ""))
    assert "couldn't find" in answer_from_help("q", _help_ctx(), _HITS)["answer"]


def test_help_answer_falls_back_to_the_top_item_when_the_model_is_down(monkeypatch):
    import app.ai.agent.guardrails as guardrails
    from app.ai.agent.tools import answer_from_help

    def down(**kw):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(guardrails, "call_groq", down)
    out = answer_from_help("q", _help_ctx(), _HITS)
    assert "how to reset my password" in out["answer"] and "Contact the admins." in out["answer"]


def test_record_widget_reaches_the_api_response(monkeypatch):
    import app.routers.chatbot as chatbot

    monkeypatch.setattr(chatbot, "run_agent", lambda **kw: {
        "answer": "card", "action_buttons": [], "tool_trace": [],
        "widget_type": "RECORD_SUMMARY", "widget_data": {"type": "ticket", "id": "1"},
    })
    user = SimpleNamespace(id="u", role="user", warehouse_id=WH)
    resp = chatbot.chatbot_agent(chatbot.AgentRequest(question="latest ticket"), db=None, current_user=user)
    assert resp.widget_type == "RECORD_SUMMARY" and resp.widget_data["type"] == "ticket"


# ── account creation ─────────────────────────────────────────────────────────

_NEW_USER = dict(
    id="U0001E", firstName="Ann", lastName="Lee", name="Ann Lee", email="ann@example.com",
    address="", contactNumber="", warehouse="Colombo", role="user", department="Logistics", status="active",
)


@pytest.mark.parametrize("password", [None, "", "short"])
def test_new_accounts_need_an_admin_set_password(password):
    from pydantic import ValidationError

    from app.schemas.user_profile import UserCreate

    fields = dict(_NEW_USER) if password is None else {**_NEW_USER, "password": password}
    with pytest.raises(ValidationError):
        UserCreate(**fields)
    assert UserCreate(**{**_NEW_USER, "password": "long-enough-1"}).password == "long-enough-1"


def test_there_is_no_shared_default_password():
    import app.routers.users as users

    assert not hasattr(users, "_default_password")


def test_chatbot_users_see_only_their_department_colleagues():
    """The SQL sandbox must not show a user more staff than /profiles/me/colleagues does."""
    from app.ai.agent.safe_sql import _row_filters

    uid = "22222222-2222-2222-2222-222222222222"
    user = _row_filters(SqlScope.build(user_id=uid, is_admin=False, warehouse_id=WH))["profiles"]
    assert f"id::text = '{uid}'" in user
    assert "department_id = (SELECT department_id FROM public.profiles" in user
    assert "department_id IS NOT NULL" in user
    admin = _row_filters(SqlScope.build(user_id=uid, is_admin=True, warehouse_id=WH))["profiles"]
    assert admin == f"warehouse_id::text = '{WH}'"


def test_help_answer_lists_only_the_items_the_model_cited(monkeypatch):
    import app.ai.agent.guardrails as guardrails
    from app.ai.agent.tools import answer_from_help

    close = [_HITS[0], {**_HITS[0], "title": "how to change my password", "similarity": 0.6}]
    monkeypatch.setattr(guardrails, "call_groq", lambda **kw: ("Change it in Settings [2].", ""))
    out = answer_from_help("change password?", _help_ctx(), close)["answer"]
    assert "FAQ: how to change my password" in out
    assert "how to reset my password" not in out


@pytest.mark.parametrize("reply", [
    "I don't have the phone number for that manager.",   # a decline in the model's own words
    "The capital is Colombo.",                           # an answer from general knowledge
    "See item [9].",                                     # a citation of an item that was not given
])
def test_help_answer_citing_nothing_is_not_covered(monkeypatch, reply):
    import app.ai.agent.guardrails as guardrails
    from app.ai.agent.tools import answer_from_help

    monkeypatch.setattr(guardrails, "call_groq", lambda **kw: (reply, ""))
    out = answer_from_help("anything", _help_ctx(), _HITS)["answer"]
    assert "couldn't find" in out and "Sources" not in out
