import os
from sqlalchemy.orm import Session
from app.db import SessionLocal
from app.models import Profile, Warehouse
from app.core.security import hash_password
import uuid

def seed_super_admins():
    db = SessionLocal()
    try:
        # Check if they exist already
        existing = db.query(Profile).filter(Profile.role == "super_admin").count()
        if existing >= 4:
            print(f"Already found {existing} super_admins. Skipping.")
            return

        # Fetch an arbitrary warehouse just to assign them one, though super_admins can log into any
        warehouse = db.query(Warehouse).first()
        wh_id = warehouse.id if warehouse else None

        emails = [
            "super.admin1@lankalogix.lk",
            "super.admin2@lankalogix.lk",
            "super.admin3@lankalogix.lk",
            "super.admin4@lankalogix.lk",
        ]

        added = 0
        from sqlalchemy import text
        import json
        
        for i, email in enumerate(emails, start=1):
            if not db.query(Profile).filter(Profile.email == email).first():
                prof_id = str(uuid.uuid4())
                meta_json = json.dumps({"password_hash": hash_password("admin123")})
                
                db.execute(
                    text("""
                    INSERT INTO profiles (id, email, role, full_name, status, meta, warehouse_id)
                    VALUES (:id, :email, 'super_admin'::app_role, :full_name, 'active', CAST(:meta AS jsonb), :warehouse_id)
                    """),
                    {
                        "id": prof_id,
                        "email": email,
                        "full_name": f"Super Admin {i}",
                        "meta": meta_json,
                        "warehouse_id": wh_id
                    }
                )
                added += 1

        db.commit()
        print(f"Successfully seeded {added} super_admins.")

    except Exception as e:
        print("Error seeding super admins:", e)
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_super_admins()
