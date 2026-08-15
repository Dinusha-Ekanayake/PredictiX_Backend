"""Manual debug script — inspect row-level-security policies on the tickets table.

Run with: python -m scripts.manual.test_rls
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
    res = conn.execute(text("SELECT pol.polname, pol.polcmd, pg_get_expr(pol.polqual, pol.polrelid) AS qual FROM pg_policy pol JOIN pg_class c ON c.oid = pol.polrelid WHERE c.relname = 'tickets'"))
    print(res.fetchall())
    
    # Also check if it's a view
    res = conn.execute(text("SELECT table_type FROM information_schema.tables WHERE table_name = 'tickets'"))
    print("Type:", res.fetchall())
