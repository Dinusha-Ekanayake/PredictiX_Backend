from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from jose import jwt
from datetime import datetime, timedelta
import os
import uuid

router = APIRouter(prefix="/auth", tags=["Auth"])

print("[AUTH MODULE] Auth module is being loaded...")

# ================================
# Schemas
# ================================

class LoginRequest(BaseModel):
    email: str
    password: str
    role: str  # "admin" or "user"

class UserInfo(BaseModel):
    id: str
    email: str
    user_name: str
    role: str
    full_name: str

class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    user: UserInfo

# ================================
# Test Accounts
# ================================

TEST_USERS = {
    "nuwan.gunasekara.tra1@lankalogix.lk": {
        "password": "user",
        "full_name": "Nuwan Gunasekara",
        "role": "user"
    },
    "anjali.warnakulasuriya.adm1@lankalogix.lk": {
        "password": "admin",
        "full_name": "Anjali Warnakulasuriya",
        "role": "admin"
    }
}

# ================================
# Login Endpoint
# ================================

@router.post("/login", response_model=LoginResponse)
def post_login(request: LoginRequest):
    print("[LOGIN ENDPOINT] Called with request:", request)
    
    email = request.email.strip().lower()
    password = request.password.strip()
    role = request.role.strip().lower()
    
    # Check email exists
    if email not in TEST_USERS:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    
    user_data = TEST_USERS[email]
    
    # Check password
    if user_data["password"] != password:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    
    # Check role matches
    if role and role != user_data["role"]:
        raise HTTPException(
            status_code=401, 
            detail=f"This account is registered as '{user_data['role']}', not '{role}'. Please select the correct role."
        )
    
    # Generate user ID
    user_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, email))
    
    # Create JWT token
    payload = {
        "sub": user_id,
        "email": email,
        "role": user_data["role"],
        "exp": datetime.utcnow() + timedelta(hours=24)
    }
    
    secret = os.getenv("JWT_SECRET", "supersecret")
    algorithm = os.getenv("JWT_ALGORITHM", "HS256")
    access_token = jwt.encode(payload, secret, algorithm=algorithm)
    
    # Create refresh token (same for now, can be different expiry in future)
    refresh_payload = {
        "sub": user_id,
        "email": email,
        "type": "refresh",
        "exp": datetime.utcnow() + timedelta(days=7)
    }
    refresh_token = jwt.encode(refresh_payload, secret, algorithm=algorithm)
    
    print(f"[LOGIN] ✓ {email} | role={user_data['role']} | id={user_id}")
    
    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user=UserInfo(
            id=user_id,
            email=email,
            user_name=email.split("@")[0],
            role=user_data["role"],
            full_name=user_data["full_name"]
        )
    )

# ================================
# Test Endpoint
# ================================

@router.get("/test")
def test_auth():
    return {"message": "Auth router working"}

print(f"[AUTH MODULE] Router created: {router}")
print(f"[AUTH MODULE] Final routes: {[r.path for r in router.routes]}")