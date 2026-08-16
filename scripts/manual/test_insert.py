"""Manual smoke test — insert a throwaway ticket row and roll it back.

Run with: python -m scripts.manual.test_insert
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
        res = conn.execute(text("INSERT INTO tickets (title, description, created_by) VALUES ('test', 'test', '00000000-0000-0000-0000-000000000000') RETURNING id"))
        print(res.fetchone())
        conn.commit()
    except Exception as e:
        print("Error:", e)
        conn.rollback()
