#!/usr/bin/env python3
"""Debug login issue for nuwan.gunasekara.tra1@lankalogix.lk"""
import os
import sys
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

# Load env
from dotenv import load_dotenv
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ DATABASE_URL not set in .env")
    sys.exit(1)

print("[*] Connecting to database...")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
db = SessionLocal()

try:
    from app.models import Profile

    email = "nuwan.gunasekara.tra1@lankalogix.lk"
    print(f"\n[*] Looking for user: {email}")

    # Try case-insensitive search
    profile = db.query(Profile).filter(
        func.lower(Profile.email) == email.lower()
    ).first()

    if profile is None:
        print(f"[X] User NOT found in database")
        print("[+] Login should use DEMO FALLBACK account")
        print(f"    Demo password: 'user' (hardcoded)")
    else:
        print(f"[+] User FOUND in database")
        print(f"    ID: {profile.id}")
        print(f"    Email: {profile.email}")
        print(f"    Full Name: {profile.full_name}")
        print(f"    Status: {profile.status}")
        print(f"    Role: {profile.role}")
        print(f"    Warehouse ID: {profile.warehouse_id}")

        meta = profile.meta if isinstance(profile.meta, dict) else {}
        password_hash = meta.get("password_hash", "(none)")
        if password_hash != "(none)":
            print(f"    Password Hash: {password_hash[:50]}...")
        else:
            print(f"    Password Hash: {password_hash}")

        # Check if status is active
        if (profile.status or "").strip().lower() != "active":
            print(f"\n[!] ISSUE: Status is not 'active' - login will FAIL")

        # Check if password is set
        if password_hash != "(none)":
            print(f"\n[!] ISSUE: Password hash exists - demo password 'user' will NOT work")
            print(f"    Try password: {os.getenv('DEFAULT_PASSWORD', 'Predictix@123')}")

finally:
    db.close()

print("\n" + "="*60)
print("TROUBLESHOOTING:")
print("="*60)
print("1. If user NOT found -> Use demo credentials: email='nuwan.gunasekara.tra1@lankalogix.lk', password='user'")
print("2. If user found with status != 'active' -> Update status to 'active' in database")
print("3. If user found with password_hash -> Use DEFAULT_PASSWORD from .env (Predictix@123)")
print("4. If still failing -> Check application logs while trying to login")
