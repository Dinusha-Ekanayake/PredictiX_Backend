from app.db import SessionLocal
from app.services.service_reminder_service import run_auto_reminder_sweep

db = SessionLocal()
try:
    result = run_auto_reminder_sweep(db)
    print("sweep result:", result)
finally:
    db.close()
