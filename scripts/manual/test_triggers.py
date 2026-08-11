"""Manual debug script — list triggers defined on the tickets table.

Run with: python -m scripts.manual.test_triggers
"""
from sqlalchemy import text

from app.db.session import engine
with engine.connect() as conn:
    res = conn.execute(text("SELECT tgname, proname FROM pg_trigger JOIN pg_proc ON pg_trigger.tgfoid = pg_proc.oid WHERE tgrelid = 'tickets'::regclass"))
    print("Triggers:", res.fetchall())
