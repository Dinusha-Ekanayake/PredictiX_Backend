import sys
from pathlib import Path

# Repository root on sys.path so `import app` works however this is invoked.
# Located by walking up to the directory holding the app package, so moving
# this file cannot break it.
_here = Path(__file__).resolve()
_root = next(p for p in _here.parents if (p / "app" / "__init__.py").exists())
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from app.db import SessionLocal
from app.services.service_reminder_service import run_auto_reminder_sweep

db = SessionLocal()
try:
    result = run_auto_reminder_sweep(db)
    print("sweep result:", result)
finally:
    db.close()
