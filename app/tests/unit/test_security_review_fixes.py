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
    from app.routers.assets import _image_extension

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
