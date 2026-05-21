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

router = APIRouter(prefix="/auth", tags=["Auth"])

# ─── Schemas ───────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str
    role: str  # "ADMIN" or "USER" (frontend sends uppercase)

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
}

# ─── POST /auth/login ──────────────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
def post_login(request: LoginRequest):
    email: str = request.email.strip().lower()
    password: str = request.password.strip()
    # Normalise to lowercase so "ADMIN" == "admin"
    requested_role: str = request.role.strip().lower()

    # 1. Check email exists
    if email not in TEST_USERS:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    user = TEST_USERS[email]

    # 2. Check password
    if user["password"] != password:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    # 3. Check role matches the account type
    if requested_role and requested_role != user["role"]:
        raise HTTPException(
            status_code=401,
            detail=f"This account is registered as '{user['role']}', not '{requested_role}'. "
                   f"Please select the correct role.",
        )

    # 4. Resolve user_id from DB (graceful fallback to deterministic UUID)
    user_id: str = _resolve_user_id(email)

    # 5. Issue JWT
    token: str = _create_token(user_id, email, user["role"])

    print(f"[LOGIN] ✓ {email} | role={user['role']} | id={user_id}")

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


def _create_token(user_id: str, email: str, role: str) -> str:
    """Encode a 24-hour JWT."""
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": datetime.utcnow() + timedelta(hours=24),
    }
    secret: str = os.getenv("JWT_SECRET", "supersecret")
    algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    return jwt.encode(payload, secret, algorithm=algorithm)