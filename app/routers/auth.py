"""Authentication router — issues JWTs for the test accounts.

Replace TEST_USERS with a real DB-backed lookup once the profiles
table is seeded for staging.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from jose import jwt
from datetime import datetime, timedelta
import os
import uuid

from app.core.security import verify_password

router = APIRouter(prefix="/auth", tags=["Auth"])


def _default_password() -> str:
    """Read DEFAULT_PASSWORD from env, stripping surrounding spaces/quotes."""
    raw = os.getenv("DEFAULT_PASSWORD", "Predictix@123")
    cleaned = raw.strip().strip('"').strip("'").strip()
    return cleaned or "Predictix@123"

# ─── Schemas ───────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str
    role: str  # "ADMIN", "USER", "SUPER_ADMIN" (frontend sends uppercase)
    warehouse_id: str | None = None

class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    user_id: str
    email: str
    role: str       # lowercase: "admin" | "user"
    full_name: str

# ─── Test accounts ─────────────────────────────────────────────────────────────
# Replace with real DB lookup once users table is seeded.

TEST_USERS: dict[str, dict] = {
    "nuwan.gunasekara.tra1@lankalogix.lk": {
        "password": "user",
        "full_name": "Nuwan Gunasekara",
        "role": "user",
    },
    "anjali.warnakulasuriya.adm1@lankalogix.lk": {
        "password": "admin",
        "full_name": "Anjali Warnakulasuriya",
        "role": "admin",
    },
    "super.admin1@lankalogix.lk": {
        "password": "super",
        "full_name": "Super Admin 1",
        "role": "super_admin",
    },
    "super.admin2@lankalogix.lk": {
        "password": "super",
        "full_name": "Super Admin 2",
        "role": "super_admin",
    },
    "super.admin3@lankalogix.lk": {
        "password": "super",
        "full_name": "Super Admin 3",
        "role": "super_admin",
    },
    "super.admin4@lankalogix.lk": {
        "password": "super",
        "full_name": "Super Admin 4",
        "role": "super_admin",
    },
}

# ─── POST /auth/login ──────────────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
def post_login(request: LoginRequest):
    email: str = request.email.strip().lower()
    password: str = request.password.strip()
    # Normalise to lowercase so "ADMIN" == "admin"
    requested_role: str = request.role.strip().lower()
    requested_warehouse_id: str | None = request.warehouse_id

    # 1. Try DB-backed authentication first.
    profile = _lookup_profile(email)
    if profile is not None:
        return _login_with_profile(profile, email, password, requested_role, requested_warehouse_id)

    # 2. No DB profile — fall back to the hardcoded demo accounts.
    print(f"[LOGIN] No DB profile for {email}; trying TEST_USERS fallback")
    return _login_with_test_user(email, password, requested_role, requested_warehouse_id)


def _login_with_profile(profile, email: str, password: str, requested_role: str, requested_warehouse_id: str | None) -> LoginResponse:
    """Authenticate against a DB Profile row."""
    profile_role = (profile.role or "").strip().lower()
    profile_status = (profile.status or "").strip().lower()
    full_name = profile.full_name or "Unknown"

    # Reject inactive accounts.
    if profile_status != "active":
        print(f"[LOGIN] ✗ {email} | account inactive (status={profile_status})")
        raise HTTPException(status_code=401, detail="This account is inactive.")

    # Determine which password check applies.
    meta = profile.meta if isinstance(profile.meta, dict) else {}
    stored_hash = meta.get("password_hash") or ""

    if stored_hash:
        ok = verify_password(password, stored_hash)
    elif email in TEST_USERS:
        ok = password == TEST_USERS[email]["password"]
    else:
        ok = password == _default_password()

    if not ok:
        print(f"[LOGIN] ✗ {email} | invalid password")
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    # Validate the declared role against the account role.
    if requested_role and requested_role != profile_role:
        raise HTTPException(
            status_code=401,
            detail=f"This account is registered as '{profile_role}', not '{requested_role}'. "
                   f"Please select the correct role.",
        )

    # Validate the warehouse selection
    if profile_role == "super_admin":
        if not requested_warehouse_id:
            raise HTTPException(status_code=400, detail="Please select a warehouse to log into.")
        active_warehouse_id = requested_warehouse_id
    else:
        # Admins and Users MUST select their own warehouse
        if not requested_warehouse_id or requested_warehouse_id != str(profile.warehouse_id):
            raise HTTPException(
                status_code=401,
                detail="You are only allowed to log into your assigned warehouse. Please select the correct warehouse."
            )
        active_warehouse_id = str(profile.warehouse_id)

    user_id = str(profile.id)
    token = _create_token(user_id, email, profile_role, active_warehouse_id)
    print(f"[LOGIN] OK (DB) {email} | role={profile_role} | id={user_id} | wh={active_warehouse_id}")

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        user_id=user_id,
        email=email,
        role=profile_role,
        full_name=full_name,
    )


def _login_with_test_user(email: str, password: str, requested_role: str, requested_warehouse_id: str | None) -> LoginResponse:
    """Backward-compat path for the hardcoded demo accounts."""
    if email not in TEST_USERS:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    user = TEST_USERS[email]

    if user["password"] != password:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    if requested_role and requested_role != user["role"]:
        raise HTTPException(
            status_code=401,
            detail=f"This account is registered as '{user['role']}', not '{requested_role}'. "
                   f"Please select the correct role.",
        )
        
    if not requested_warehouse_id:
        raise HTTPException(status_code=400, detail="Please select a warehouse to log into.")

    user_id: str = _resolve_user_id(email)
    token: str = _create_token(user_id, email, user["role"], requested_warehouse_id)
    print(f"[LOGIN] ✓ (TEST) {email} | role={user['role']} | id={user_id} | wh={requested_warehouse_id}")

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        user_id=user_id,
        email=email,
        role=user["role"],
        full_name=user["full_name"],
    )

# ─── GET /auth/test ────────────────────────────────────────────────────────────

@router.get("/test")
def test_auth():
    return {"message": "Auth router working"}

# ─── Helpers ───────────────────────────────────────────────────────────────────

def _lookup_profile(email: str):
    """Case-insensitive Profile lookup by email.

    Returns the Profile or None. Any DB failure is swallowed (returns None)
    so login cleanly falls back to the TEST_USERS path — never a 500.
    """
    try:
        from sqlalchemy import func
        from app.db import SessionLocal
        from app.models import Profile
        db = SessionLocal()
        try:
            return (
                db.query(Profile)
                .filter(func.lower(Profile.email) == email)
                .first()
            )
        finally:
            db.close()
    except Exception as e:
        print(f"[LOGIN] DB profile lookup failed (non-fatal): {e}")
        return None


def _resolve_user_id(email: str) -> str:
    """Try to get real user_id from DB; fall back to deterministic UUID."""
    try:
        from app.db import SessionLocal
        from app.models import Profile
        db = SessionLocal()
        try:
            user = db.query(Profile).filter(Profile.email == email).first()
            if user:
                print(f"[LOGIN] Found user in DB: {user.id}")
                return str(user.id)
        finally:
            db.close()
    except Exception as e:
        print(f"[LOGIN] DB lookup failed (non-fatal): {e}")

    fallback = str(uuid.uuid5(uuid.NAMESPACE_DNS, email))
    print(f"[LOGIN] Using deterministic UUID fallback: {fallback}")
    return fallback


def _create_token(user_id: str, email: str, role: str, active_warehouse_id: str) -> str:
    """Encode a 24-hour JWT."""
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "active_warehouse_id": active_warehouse_id,
        "exp": datetime.utcnow() + timedelta(hours=24),
    }
    secret: str = os.getenv("JWT_SECRET", "supersecret")
    algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    return jwt.encode(payload, secret, algorithm=algorithm)