"""Manual debug script — inspect the log_api_request PostgREST function/policies.

Run with: python -m scripts.manual.test_pgrst
"""
from sqlalchemy import text

from app.db.session import engine
with engine.connect() as conn:
    try:
        res = conn.execute(text("SHOW ALL"))
        for row in res:
            if 'pgrst' in row[0] or 'pre_request' in row[0]:
                print(row)
    except Exception as e:
        print("Error showing all:", e)
        
    try:
        res = conn.execute(text("SELECT * FROM pg_proc WHERE proname = 'pre_request'"))
        print(res.fetchall())
    except Exception as e:
        print(e)
