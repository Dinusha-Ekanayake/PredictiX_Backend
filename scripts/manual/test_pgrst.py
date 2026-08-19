"""Manual debug script, inspect the log_api_request PostgREST function/policies.

Run with: python -m scripts.manual.test_pgrst
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
