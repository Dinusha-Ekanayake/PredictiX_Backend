"""Manual debug script — check for a pgrst pre_request hook in Postgres settings.

Run with: python -m scripts.manual.test_log_api
"""
from sqlalchemy import text

from app.db.session import engine
with engine.connect() as conn:
    try:
        # get definition
        res = conn.execute(text("SELECT pg_get_functiondef(oid) FROM pg_proc WHERE proname = 'log_api_request'"))
        print("Definition:\n", res.fetchone()[0])
        
        # see where it's used
        res = conn.execute(text("SELECT polname, polrelid::regclass, pg_get_expr(polqual, polrelid) FROM pg_policy WHERE pg_get_expr(polqual, polrelid) LIKE '%log_api_request%'"))
        print("Policies:\n", res.fetchall())
        
        # see if it's set as pgrst pre_request in authenticator
        res = conn.execute(text("SELECT * FROM pg_catalog.pg_db_role_setting WHERE setconfig::text LIKE '%log_api_request%'"))
        print("DB Role settings:\n", res.fetchall())
        
        # also check pg_settings
        res = conn.execute(text("SELECT * FROM pg_settings WHERE source = 'database' OR source = 'user'"))
        print("PG Settings:\n", res.fetchall())
        
    except Exception as e:
        print("Error:", e)
