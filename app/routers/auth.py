from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from jose import jwt
from datetime import datetime, timedelta
import os
from app.db import SessionLocal
from app.models import Profile
from app.deps import get_db

print("[AUTH MODULE] Auth module is being loaded...")

router = APIRouter(prefix="/auth", tags=["Auth"])
print(f"[AUTH MODULE] Router created: {router}")

# ================================
# Schemas
# ================================

class LoginRequest(BaseModel):
    email: str
    password: str
    role: str  # "user" or "admin"

class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    user_id: str
    email: str
    role: str
    full_name: str

# ================================
# Login Endpoint
# ================================

@router.post("/login")
def post_login(request: LoginRequest, db: Session = Depends(get_db)):
    print("[LOGIN ENDPOINT] Called with request:", request)
    
    TEST_USERS = {
        "nuwan.gunasekara.tra1@lankalogix.lk": {
            "password": "nuwan",
            "full_name": "Nuwan Gunasekara",
            "role": "user"
        },
        "anjali.warnakulasuriya.adm1@lankalogix.lk": {
            "password": "admin",
            "full_name": "Anjali Warnakulasuriya",
            "role": "admin"
        }
    }
    
    email = request.email.strip().lower()
    password = request.password.strip()
    role = request.role.upper()
    
    if email not in TEST_USERS:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    user_data = TEST_USERS[email]
    if user_data["password"] != password or user_data["role"].upper() != role:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    import uuid
    user_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, email))
    
    payload = {
        "sub": user_id,
        "email": email,
        "role": user_data["role"],
        "exp": datetime.utcnow() + timedelta(hours=24)
    }
    
    secret = os.getenv("JWT_SECRET", "supersecret")
    algorithm = os.getenv("JWT_ALGORITHM", "HS256")
    token = jwt.encode(payload, secret, algorithm=algorithm)
    
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        user_id=user_id,
        email=email,
        role=user_data["role"],
        full_name=user_data["full_name"]
    )

# ================================
# Test endpoint
# ================================

@router.get("/test")
def test_auth():
    return {"message": "Auth working"}

# Debug: Print all routes after they're registered
print(f"[AUTH MODULE] Final routes in auth.router after all endpoints: {[r.path for r in router.routes]}")
for route in router.routes:
    if hasattr(route, 'methods'):
        print(f"[AUTH MODULE]   {route.path}: {route.methods}")
