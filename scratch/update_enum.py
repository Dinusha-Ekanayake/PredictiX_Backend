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
