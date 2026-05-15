# from fastapi import APIRouter, Depends, HTTPException, status
# from sqlalchemy.orm import Session
# from pydantic import BaseModel
# from jose import jwt
# from datetime import datetime, timedelta
# import os
# from app.db import SessionLocal
# from app.models import Profile
# from app.deps import get_db

# print("[AUTH MODULE] Auth module is being loaded...")

# router = APIRouter(prefix="/auth", tags=["Auth"])
# print(f"[AUTH MODULE] Router created: {router}")

# # ================================
# # Schemas
# # ================================

# class LoginRequest(BaseModel):
#     email: str
#     password: str
#     role: str  # "user" or "admin"

# class LoginResponse(BaseModel):
#     access_token: str
#     token_type: str
#     user_id: str
#     email: str
#     role: str
#     full_name: str

# # ================================
# # Login Endpoint
# # ================================

# @router.post("/login")
# def post_login(request: LoginRequest, db: Session = Depends(get_db)):
#     print("[LOGIN ENDPOINT] Called with request:", request)
    
#     TEST_USERS = {
#         "nuwan.gunasekara.tra1@lankalogix.lk": {
#             "password": "nuwan",
#             "full_name": "Nuwan Gunasekara",
#             "role": "user"
#         },
#         "anjali.warnakulasuriya.adm1@lankalogix.lk": {
#             "password": "admin",
#             "full_name": "Anjali Warnakulasuriya",
#             "role": "admin"
#         }
#     }
    
#     email = request.email.strip().lower()
#     password = request.password.strip()
#     role = request.role.upper()
    
#     if email not in TEST_USERS:
#         raise HTTPException(status_code=401, detail="Invalid credentials")
    
#     user_data = TEST_USERS[email]
#     if user_data["password"] != password or user_data["role"].upper() != role:
#         raise HTTPException(status_code=401, detail="Invalid credentials")
    
#     import uuid
#     user_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, email))
    
#     payload = {
#         "sub": user_id,
#         "email": email,
#         "role": user_data["role"],
#         "exp": datetime.utcnow() + timedelta(hours=24)
#     }
    
#     secret = os.getenv("JWT_SECRET", "supersecret")
#     algorithm = os.getenv("JWT_ALGORITHM", "HS256")
#     token = jwt.encode(payload, secret, algorithm=algorithm)
    
#     return LoginResponse(
#         access_token=token,
#         token_type="bearer",
#         user_id=user_id,
#         email=email,
#         role=user_data["role"],
#         full_name=user_data["full_name"]
#     )

# # ================================
# # Test endpoint
# # ================================

# @router.get("/test")
# def test_auth():
#     return {"message": "Auth working"}

# # Debug: Print all routes after they're registered
# print(f"[AUTH MODULE] Final routes in auth.router after all endpoints: {[r.path for r in router.routes]}")
# for route in router.routes:
#     if hasattr(route, 'methods'):
#         print(f"[AUTH MODULE]   {route.path}: {route.methods}")

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