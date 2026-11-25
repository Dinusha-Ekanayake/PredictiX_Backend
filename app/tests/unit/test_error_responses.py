"""Error responses never carry exception text to the client."""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError

os.environ.setdefault("JWT_SECRET", "unit-test-secret-not-used-anywhere-else")

from app.core.errors import DB_UNAVAILABLE, internal_error  # noqa: E402

SECRET_TEXT = "password=hunter2 host=db.internal SELECT * FROM profiles"


def test_unexpected_error_returns_only_the_fixed_message(caplog):
    exc = internal_error("Summary generation failed.", RuntimeError(SECRET_TEXT))
    assert exc.status_code == 500
    assert exc.detail == "Summary generation failed."
    # The operator still gets the real cause in the log.
    assert SECRET_TEXT in caplog.text


def test_status_code_can_be_chosen():
    assert internal_error("Model not available.", FileNotFoundError("/srv/models/x.pkl"), status_code=503).status_code == 503


def test_dropped_database_connection_is_a_503():
    db_error = OperationalError("SELECT 1", {}, Exception("server closed the connection unexpectedly"))
    exc = internal_error("Dashboard failed.", db_error)
    assert exc.status_code == 503
    assert exc.detail == DB_UNAVAILABLE


def test_admin_dashboard_failure_does_not_leak(monkeypatch):
    import app.routers.admin_dashboard as admin_dashboard

    def boom(*args, **kwargs):
        raise RuntimeError(SECRET_TEXT)

    monkeypatch.setattr(admin_dashboard._cache, "get_or_refresh", boom)
    admin = SimpleNamespace(id="a", role="admin", warehouse_id="w1")
    with pytest.raises(HTTPException) as caught:
        admin_dashboard.get_admin_summary(db=object(), current_user=admin)
    assert caught.value.status_code == 500
    assert "hunter2" not in str(caught.value.detail)


# ── API docs exposure ────────────────────────────────────────────────────────

@pytest.mark.parametrize("env,flag,expected", [
    ("", "", True),
    ("production", "", False),
    ("production", "true", True),
    ("", "false", False),
])
def test_api_docs_are_off_in_production_unless_enabled(monkeypatch, env, flag, expected):
    from app.core.config import api_docs_enabled

    monkeypatch.setenv("ENV", env)
    monkeypatch.setenv("ENABLE_API_DOCS", flag)
    assert api_docs_enabled() is expected


def test_server_refuses_to_start_without_a_jwt_secret(monkeypatch):
    import app.core.config as config

    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setattr(config.settings, "JWT_SECRET", None)
    with pytest.raises(RuntimeError, match="JWT_SECRET is not configured"):
        config.require_runtime_settings()


def test_no_database_means_a_clear_error_only_when_a_session_is_opened(monkeypatch):
    import app.db.session as session

    if session.engine is not None:
        pytest.skip("a database is configured in this environment")
    with pytest.raises(session.DatabaseNotConfigured):
        session.SessionLocal()
