"""Manual debug script — list volatile functions in the public schema.

Run with: python -m scripts.manual.test_volatile
"""
from sqlalchemy import text

from app.db.session import engine
with engine.connect() as conn:
    try:
        res = conn.execute(text("SELECT proname, provolatile FROM pg_proc JOIN pg_namespace ON pg_namespace.oid = pg_proc.pronamespace WHERE nspname = 'public' AND provolatile = 'v'"))
        for row in res.fetchall():
            print(row)
    except Exception as e:
        print("Error:", e)
