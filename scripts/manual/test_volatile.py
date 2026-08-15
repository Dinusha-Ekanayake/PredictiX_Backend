"""Manual debug script — list volatile functions in the public schema.

Run with: python -m scripts.manual.test_volatile
"""
import sys
from pathlib import Path

# Repository root on sys.path so `import app` works however this is invoked.
# Located by walking up to the directory holding the app package, so moving
# this file cannot break it.
_here = Path(__file__).resolve()
_root = next(p for p in _here.parents if (p / "app" / "__init__.py").exists())
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from sqlalchemy import text

from app.db.session import engine
with engine.connect() as conn:
    try:
        res = conn.execute(text("SELECT proname, provolatile FROM pg_proc JOIN pg_namespace ON pg_namespace.oid = pg_proc.pronamespace WHERE nspname = 'public' AND provolatile = 'v'"))
        for row in res.fetchall():
            print(row)
    except Exception as e:
        print("Error:", e)
