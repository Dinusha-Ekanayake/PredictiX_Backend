"""Manual smoke test — insert a throwaway ticket row and roll it back.

Run with: python -m scripts.manual.test_insert
"""
from sqlalchemy import text

from app.db.session import engine
with engine.connect() as conn:
    try:
        res = conn.execute(text("INSERT INTO tickets (title, description, created_by) VALUES ('test', 'test', '00000000-0000-0000-0000-000000000000') RETURNING id"))
        print(res.fetchone())
        conn.commit()
    except Exception as e:
        print("Error:", e)
        conn.rollback()
