import sys
from pathlib import Path

# Put the repository root on sys.path so `import app` works however this script
# is invoked. Located by walking up to the directory that contains the app
# package, rather than by counting parents, so moving this file cannot break it.
_here = Path(__file__).resolve()
_root = next(p for p in _here.parents if (p / "app" / "__init__.py").exists())
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import os
from sqlalchemy import text
from app.db import SessionLocal

def update_enum():
    db = SessionLocal()
    try:
        db.execute(text("ALTER TYPE app_role ADD VALUE IF NOT EXISTS 'super_admin';"))
        db.commit()
        print("Enum updated.")
    except Exception as e:
        print("Error:", e)
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    update_enum()
