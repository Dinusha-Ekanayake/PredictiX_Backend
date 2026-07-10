"""Authentication router.

Flow
----
POST /auth/login
    - Email + password only. Role is detected automatically from the DB.
    - user  → token issued immediately, redirect to user dashboard.
    - admin → token issued immediately (warehouse already fixed to their profile).
    - super_admin → no token yet; returns requires_warehouse_selection=True
                    plus a list of all active warehouses.

POST /auth/login/select-warehouse
    - Super admin submits a warehouse_id they chose from the dropdown.
    - A short-lived (5-min) signed intermediate token from the first step is
      verified, then a full 24-hour JWT is issued scoped to that warehouse.

GET  /auth/warehouses
    - Returns all active warehouses (used to populate the dropdown).
"""
from __future__ import annotations

<<<<<<< HEAD
from datetime import datetime, timedelta
=======
from datetime import datetime, timedelta, timezone
>>>>>>> 35e3ac103591052fc88dd59200e314bb3792f95b
from typing import Optional
import logging
import os
import uuid

from fastapi import APIRouter, HTTPException
from jose import JWTError, jwt
from pydantic import BaseModel

from app.core.security import verify_password
from app.core.config import jwt_secret, jwt_algorithm

router = APIRouter(prefix="/auth", tags=["Auth"])
log = logging.getLogger(__name__)

# ─── helpers ──────────────────────────────────────────────────────────────────

def _default_password() -> str:
    raw = os.getenv("DEFAULT_PASSWORD", "Predictix@123")
    return raw.strip().strip('"').strip("'").strip() or "Predictix@123"

def _secret() -> str:
<<<<<<< HEAD
    return os.getenv("JWT_SECRET", "supersecret")

def _algorithm() -> str:
    return os.getenv("JWT_ALGORITHM", "HS256")
=======
    # Centralised: fails fast if JWT_SECRET is unset (no public-constant fallback).
    return jwt_secret()

def _algorithm() -> str:
    return jwt_algorithm()
>>>>>>> 35e3ac103591052fc88dd59200e314bb3792f95b

# ─── schemas ──────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str

class WarehouseOption(BaseModel):
    id: str
    name: str
    code: str
    city: Optional[str] = None

class LoginResponse(BaseModel):
    # Set when authentication is complete (user / admin).
    access_token: Optional[str] = None
    token_type: str = "bearer"
    user_id: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None        # "user" | "admin" | "super_admin"
    full_name: Optional[str] = None
    warehouse_id: Optional[str] = None
    warehouse_name: Optional[str] = None
    avatar_url: Optional[str] = None
    # Set only for super_admin — frontend shows the warehouse picker.
    requires_warehouse_selection: bool = False
    selection_token: Optional[str] = None   # short-lived token for step 2
    warehouses: Optional[list[WarehouseOption]] = None

class WarehouseSelectRequest(BaseModel):
    selection_token: str   # from step 1
    warehouse_id: str

class GoogleLoginRequest(BaseModel):
    token: str

# ─── demo fallback accounts (no DB row) ──────────────────────────────────────

_DEMO_USERS: dict[str, dict] = {
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

# ─── POST /auth/login ─────────────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
def post_login(request: LoginRequest):
    email = request.email.strip().lower()
    password = request.password.strip()

    profile = _lookup_profile(email)
    if profile is not None:
        return _authenticate_profile(profile, email, password)

    log.info("[LOGIN] No DB profile for %s; trying demo fallback", email)
    return _authenticate_demo(email, password)


# ─── POST /auth/login/select-warehouse ────────────────────────────────────────

@router.post("/login/select-warehouse", response_model=LoginResponse)
def select_warehouse(request: WarehouseSelectRequest):
    """Step 2 for super_admin: verify the short-lived selection token and
    issue a full JWT scoped to the chosen warehouse."""
    try:
        payload = jwt.decode(request.selection_token, _secret(), algorithms=[_algorithm()])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired selection token. Please log in again.")

    if payload.get("type") != "warehouse_selection":
        raise HTTPException(status_code=401, detail="Invalid token type.")

    user_id: str = payload["sub"]
    email: str = payload["email"]
    full_name: str = payload.get("full_name", "")

    # Validate the chosen warehouse exists and is active.
    warehouse = _lookup_warehouse(request.warehouse_id)
    if warehouse is None:
        raise HTTPException(status_code=404, detail="Warehouse not found.")
    if not warehouse.is_active:
        raise HTTPException(status_code=400, detail="This warehouse is currently inactive.")

    wh_id = str(warehouse.id)
    wh_name = warehouse.name

    token = _create_token(user_id, email, "super_admin", warehouse_id=wh_id)
    log.info("[LOGIN] ✓ super_admin %s selected warehouse %s (%s)", email, wh_name, wh_id[:8])

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        user_id=user_id,
        email=email,
        role="super_admin",
        full_name=full_name,
        warehouse_id=wh_id,
        warehouse_name=wh_name,
    )


# ─── GET /auth/warehouses ──────────────────────────────────────────────────────

@router.get("/warehouses", response_model=list[WarehouseOption])
def list_warehouses():
    """Return all active warehouses for the super_admin picker."""
    try:
        from app.db import SessionLocal
        from app.models import Warehouse
        db = SessionLocal()
        try:
            rows = db.query(Warehouse).filter(Warehouse.is_active == True).order_by(Warehouse.name).all()
            return [
                WarehouseOption(id=str(w.id), name=w.name, code=w.code, city=w.city)
                for w in rows
            ]
        finally:
            db.close()
    except Exception as e:
        log.warning("[AUTH] Warehouse list failed: %s", e)
        raise HTTPException(status_code=500, detail="Could not fetch warehouses.")


# ─── GET /auth/test ────────────────────────────────────────────────────────────

@router.get("/test")
def test_auth():
    return {"message": "Auth router working"}


# ─── internal: authenticate ───────────────────────────────────────────────────

def _authenticate_profile(profile, email: str, password: str) -> LoginResponse:
    role = (profile.role or "").strip().lower()
    status = (profile.status or "").strip().lower()
    full_name = profile.full_name or "Unknown"

    if status != "active":
        log.info("[LOGIN] ✗ %s | inactive account", email)
        raise HTTPException(status_code=401, detail="This account is inactive.")

    # Password check: hashed → demo override → default password.
    meta = profile.meta if isinstance(profile.meta, dict) else {}
    stored_hash = meta.get("password_hash") or ""

    if stored_hash:
        ok = verify_password(password, stored_hash)
    else:
        demo_pw = _DEMO_USERS.get(email, {}).get("password")
        ok = password == _default_password() or (demo_pw is not None and password == demo_pw)

    if not ok:
        log.info("[LOGIN] ✗ %s | wrong password", email)
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    user_id = str(profile.id)

    # ── super_admin: warehouse picker needed ──────────────────────────────────
    if role == "super_admin":
        warehouses = _fetch_all_warehouses()
        selection_token = _create_selection_token(user_id, email, full_name)
        log.info("[LOGIN] ✓ super_admin %s — awaiting warehouse selection", email)
        return LoginResponse(
            requires_warehouse_selection=True,
            selection_token=selection_token,
            user_id=user_id,
            email=email,
            role="super_admin",
            full_name=full_name,
            warehouses=warehouses,
        )

    # ── admin: token scoped to their assigned warehouse ───────────────────────
    if role == "admin":
        wh_id = str(profile.warehouse_id) if profile.warehouse_id else None
        wh_name = _warehouse_name(wh_id)
        token = _create_token(user_id, email, role, warehouse_id=wh_id)
        log.info("[LOGIN] ✓ admin %s | warehouse=%s | id=%s", email, wh_name, user_id[:8])
        return LoginResponse(
            access_token=token,
            user_id=user_id,
            email=email,
            role=role,
            full_name=full_name,
            warehouse_id=wh_id,
            warehouse_name=wh_name,
            avatar_url=profile.avatar_url,
        )

    # ── user: token issued immediately ────────────────────────────────────────
    token = _create_token(user_id, email, role)
    log.info("[LOGIN] ✓ user %s | id=%s", email, user_id[:8])
    return LoginResponse(
        access_token=token,
        user_id=user_id,
        email=email,
        role=role,
        full_name=full_name,
        avatar_url=profile.avatar_url,
    )


def _authenticate_demo(email: str, password: str) -> LoginResponse:
    """Fallback for hardcoded demo accounts with no DB row."""
    if email not in _DEMO_USERS:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    demo = _DEMO_USERS[email]
    if demo["password"] != password:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    user_id = _resolve_user_id(email)
    role = demo["role"]
    full_name = demo["full_name"]

    wh_id, wh_name = None, None
    avatar_url = None
    profile = _lookup_profile(email)
    if profile:
        avatar_url = profile.avatar_url
        if role == "admin" and profile.warehouse_id:
            wh_id = str(profile.warehouse_id)
            wh_name = _warehouse_name(wh_id)

    token = _create_token(user_id, email, role, warehouse_id=wh_id)
    log.info("[LOGIN] ✓ (demo) %s | role=%s", email, role)
    return LoginResponse(
        access_token=token,
        user_id=user_id,
        email=email,
        role=role,
        full_name=full_name,
        warehouse_id=wh_id,
        warehouse_name=wh_name,
        avatar_url=avatar_url,
    )


# ─── internal: DB helpers ──────────────────────────────────────────────────────

def _lookup_profile(email: str):
    try:
        from sqlalchemy import func
        from app.db import SessionLocal
        from app.models import Profile
        db = SessionLocal()
        try:
            return db.query(Profile).filter(func.lower(Profile.email) == email).first()
        finally:
            db.close()
    except Exception as e:
        log.warning("[LOGIN] DB profile lookup failed (non-fatal): %s", e)
        return None


def _lookup_warehouse(warehouse_id: str):
    try:
        from app.db import SessionLocal
        from app.models import Warehouse
        db = SessionLocal()
        try:
            return db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
        finally:
            db.close()
    except Exception as e:
        log.warning("[LOGIN] Warehouse lookup failed: %s", e)
        return None


def _warehouse_name(warehouse_id: Optional[str]) -> Optional[str]:
    if not warehouse_id:
        return None
    wh = _lookup_warehouse(warehouse_id)
    return wh.name if wh else None


def _fetch_all_warehouses() -> list[WarehouseOption]:
    try:
        from app.db import SessionLocal
        from app.models import Warehouse
        db = SessionLocal()
        try:
            rows = db.query(Warehouse).filter(Warehouse.is_active == True).order_by(Warehouse.name).all()
            return [
                WarehouseOption(id=str(w.id), name=w.name, code=w.code, city=w.city)
                for w in rows
            ]
        finally:
            db.close()
    except Exception as e:
        log.warning("[LOGIN] Warehouse fetch failed: %s", e)
        return []


def _resolve_user_id(email: str) -> str:
    try:
        from app.db import SessionLocal
        from app.models import Profile
        db = SessionLocal()
        try:
            user = db.query(Profile).filter(Profile.email == email).first()
            if user:
                return str(user.id)
        finally:
            db.close()
    except Exception as e:
        log.warning("[LOGIN] DB user_id lookup failed: %s", e)
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, email))


# ─── internal: token creation ─────────────────────────────────────────────────

def _create_token(user_id: str, email: str, role: str, *, warehouse_id: Optional[str] = None) -> str:
    """Issue a 24-hour JWT. Includes warehouse_id when provided."""
<<<<<<< HEAD
=======
    now = datetime.now(timezone.utc)
>>>>>>> 35e3ac103591052fc88dd59200e314bb3792f95b
    payload: dict = {
        "sub": user_id,
        "email": email,
        "role": role,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(hours=24),
    }
    if warehouse_id:
        payload["warehouse_id"] = warehouse_id
    return jwt.encode(payload, _secret(), algorithm=_algorithm())


def _create_selection_token(user_id: str, email: str, full_name: str) -> str:
    """Issue a short-lived (5-min) intermediate token for the warehouse picker."""
<<<<<<< HEAD
=======
    now = datetime.now(timezone.utc)
>>>>>>> 35e3ac103591052fc88dd59200e314bb3792f95b
    payload = {
        "sub": user_id,
        "email": email,
        "full_name": full_name,
        "type": "warehouse_selection",
<<<<<<< HEAD
        "exp": datetime.utcnow() + timedelta(minutes=5),
=======
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=5),
>>>>>>> 35e3ac103591052fc88dd59200e314bb3792f95b
    }
    return jwt.encode(payload, _secret(), algorithm=_algorithm())


# ─── POST /auth/google-login ─────────────────────────────────────────────────

@router.post("/google-login", response_model=LoginResponse)
def post_google_login(request: GoogleLoginRequest):
    """Google login verification endpoint.
    Verifies the Supabase JWT token, extracts user email, checks Profile,
    and returns a PredictiX JWT or warehouse selection info.
    """
    token = request.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Token is required.")

    # Initialize Supabase client
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        raise HTTPException(status_code=500, detail="Supabase not configured on backend.")

    try:
        from supabase import create_client
        supabase_client = create_client(supabase_url, supabase_key)
        user_resp = supabase_client.auth.get_user(token)
    except Exception as e:
        log.warning("[GOOGLE-LOGIN] Supabase verification failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid Google session.")

    if not user_resp or not user_resp.user:
        raise HTTPException(status_code=401, detail="Invalid Google session.")

    email = (user_resp.user.email or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Google session contains no email.")

    # Get avatar url from Google metadata
    google_avatar = None
    if user_resp.user.user_metadata:
        google_avatar = user_resp.user.user_metadata.get("avatar_url") or user_resp.user.user_metadata.get("picture")

    # Check if this email exists as a Profile in our database.
    profile = _lookup_profile(email)
    if profile is not None:
        role = (profile.role or "").strip().lower()
        status = (profile.status or "").strip().lower()
        full_name = profile.full_name or "Unknown"

        if status != "active":
            log.info("[GOOGLE-LOGIN] ✗ %s | inactive account", email)
            raise HTTPException(status_code=401, detail="This account is inactive.")

        user_id = str(profile.id)

        # Update avatar_url in database to keep it sync'd with Google
        avatar_url = profile.avatar_url
        if google_avatar and profile.avatar_url != google_avatar:
            try:
                from app.db import SessionLocal
                from app.models import Profile
                db = SessionLocal()
                try:
                    db_profile = db.query(Profile).filter(Profile.id == profile.id).first()
                    if db_profile:
                        db_profile.avatar_url = google_avatar
                        db.commit()
                        avatar_url = google_avatar
                        log.info("[GOOGLE-LOGIN] Updated avatar URL in DB for %s", email)
                finally:
                    db.close()
            except Exception as e:
                log.warning("[GOOGLE-LOGIN] Failed to update avatar_url in DB: %s", e)

        # fallback if DB write failed or didn't run
        if not avatar_url:
            avatar_url = google_avatar

        if role == "super_admin":
            warehouses = _fetch_all_warehouses()
            selection_token = _create_selection_token(user_id, email, full_name)
            log.info("[GOOGLE-LOGIN] ✓ super_admin %s — awaiting warehouse selection", email)
            return LoginResponse(
                requires_warehouse_selection=True,
                selection_token=selection_token,
                user_id=user_id,
                email=email,
                role="super_admin",
                full_name=full_name,
                warehouses=warehouses,
                avatar_url=avatar_url,
            )

        if role == "admin":
            wh_id = str(profile.warehouse_id) if profile.warehouse_id else None
            wh_name = _warehouse_name(wh_id)
            jwt_token = _create_token(user_id, email, role, warehouse_id=wh_id)
            log.info("[GOOGLE-LOGIN] ✓ admin %s | warehouse=%s | id=%s", email, wh_name, user_id[:8])
            return LoginResponse(
                access_token=jwt_token,
                user_id=user_id,
                email=email,
                role=role,
                full_name=full_name,
                warehouse_id=wh_id,
                warehouse_name=wh_name,
                avatar_url=avatar_url,
            )

        jwt_token = _create_token(user_id, email, role)
        log.info("[GOOGLE-LOGIN] ✓ user %s | id=%s", email, user_id[:8])
        return LoginResponse(
            access_token=jwt_token,
            user_id=user_id,
            email=email,
            role=role,
            full_name=full_name,
            avatar_url=avatar_url,
        )

    # Fallback to demo users check
    if email in _DEMO_USERS:
        demo = _DEMO_USERS[email]
        user_id = _resolve_user_id(email)
        role = demo["role"]
        full_name = demo["full_name"]

        wh_id, wh_name = None, None
        avatar_url = google_avatar
        profile = _lookup_profile(email)
        if profile:
            avatar_url = profile.avatar_url or google_avatar
            if role == "admin" and profile.warehouse_id:
                wh_id = str(profile.warehouse_id)
                wh_name = _warehouse_name(wh_id)

        jwt_token = _create_token(user_id, email, role, warehouse_id=wh_id)
        log.info("[GOOGLE-LOGIN] ✓ (demo) %s | role=%s", email, role)
        return LoginResponse(
            access_token=jwt_token,
            user_id=user_id,
            email=email,
            role=role,
            full_name=full_name,
            warehouse_id=wh_id,
            warehouse_name=wh_name,
            avatar_url=avatar_url,
        )

    log.info("[GOOGLE-LOGIN] ✗ %s | no profile found", email)
    raise HTTPException(
        status_code=404,
        detail="No profile found for this Google email. Please contact an admin."
    )
