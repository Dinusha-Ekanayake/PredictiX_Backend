"""Manual debug script, list triggers defined on the tickets table.

Run with: python -m scripts.manual.test_triggers
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
    res = conn.execute(text("SELECT tgname, proname FROM pg_trigger JOIN pg_proc ON pg_trigger.tgfoid = pg_proc.oid WHERE tgrelid = 'tickets'::regclass"))
    print("Triggers:", res.fetchall())
