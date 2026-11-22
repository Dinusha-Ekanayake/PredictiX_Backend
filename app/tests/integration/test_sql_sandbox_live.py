"""The chatbot SQL sandbox against the real database.

Unit tests cover the validator alone. These check what only Postgres can:
that the scoped views really narrow rows, hide columns, and that the
transaction cannot write even if the validator were bypassed. Everything runs
in a transaction that is rolled back.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

DATA = json.loads((Path(__file__).resolve().parents[1] / "data" / "adversarial.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def sandbox(api, world):
    from app.ai.agent.safe_sql import SqlScope, run_scoped_query
    from app.db.session import engine

    admin = SqlScope.build(user_id=world["admin"]["id"], is_admin=True, warehouse_id=world["admin"]["wh"])
    user = SqlScope.build(user_id=world["user"]["id"], is_admin=False, warehouse_id=world["user"]["wh"])
    homeless = SqlScope.build(user_id=world["admin"]["id"], is_admin=True, warehouse_id=None)
    return engine, run_scoped_query, {"admin": admin, "user": user, "homeless": homeless}


def test_admin_sees_exactly_their_warehouse(sandbox, world):
    engine, run, scopes = sandbox
    seen = run(engine, "SELECT count(*) AS n FROM assets", scopes["admin"])[0]["n"]
    with engine.connect() as c:
        own = c.execute(text("SELECT count(*) FROM assets WHERE warehouse_id::text = :w"), {"w": world["admin"]["wh"]}).scalar()
        total = c.execute(text("SELECT count(*) FROM assets")).scalar()
        c.rollback()
    assert seen == own < total


def test_admin_without_a_warehouse_sees_nothing(sandbox):
    engine, run, scopes = sandbox
    assert run(engine, "SELECT count(*) AS n FROM assets", scopes["homeless"])[0]["n"] == 0


def test_password_hashes_are_not_reachable(sandbox):
    engine, run, scopes = sandbox
    with pytest.raises(Exception, match="meta"):
        run(engine, "SELECT meta FROM profiles", scopes["user"])


def test_tables_the_chatbot_does_not_need_are_empty(sandbox):
    engine, run, scopes = sandbox
    assert run(engine, "SELECT count(*) AS n FROM faqs", scopes["admin"])[0]["n"] == 0


@pytest.mark.parametrize("sql", DATA["sql_benign"][:10])
def test_realistic_queries_run(sandbox, sql):
    engine, run, scopes = sandbox
    assert isinstance(run(engine, sql, scopes["admin"]), list)


def test_writes_are_blocked_even_without_the_validator(sandbox, monkeypatch):
    import app.ai.agent.safe_sql as safe_sql

    engine, run, scopes = sandbox
    monkeypatch.setattr(safe_sql, "validate_generated_sql", lambda s: s)
    with engine.connect() as c:
        seq = c.execute(text("SELECT schemaname || '.' || sequencename FROM pg_sequences LIMIT 1")).scalar()
        c.rollback()
    with pytest.raises(Exception, match="read-only"):
        run(engine, f"SELECT nextval('{seq}')", scopes["admin"])


def test_nothing_persists_after_a_query(sandbox):
    engine, run, scopes = sandbox
    run(engine, "SELECT 1 AS one", scopes["admin"])
    with engine.connect() as c:
        temp_views = c.execute(text("SELECT count(*) FROM pg_class WHERE relpersistence = 't' AND relkind = 'v'")).scalar()
        c.rollback()
    assert temp_views == 0
