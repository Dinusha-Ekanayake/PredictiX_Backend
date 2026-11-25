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
      verified, then a full access token is issued scoped to that warehouse.
      Access tokens live for ACCESS_TOKEN_TTL_MINUTES (8 hours by default).

GET  /auth/warehouses
    - Returns all active warehouses (used to populate the dropdown).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.config import access_token_ttl_minutes, demo_accounts_enabled
from app.core.rate_limit import login_email_rate_limit, login_rate_limit
from app.core.security import InvalidTokenError, decode_token, encode_token, verify_password
from app.deps import require_super_admin

router = APIRouter(prefix="/auth", tags=["Auth"])
log = logging.getLogger(__name__)

# ─── helpers ──────────────────────────────────────────────────────────────────

def _mask_email(email: str) -> str:
    """Shorten an email for logs so they identify an account without storing it."""
    local, _, domain = (email or "").partition("@")
    return f"{local[:3]}***@{domain}" if domain else "***"


def is_demo_email(email: str) -> bool:
    """True when the email is a built-in demo account and demo logins are enabled."""
    return demo_accounts_enabled() and (email or "").strip().lower() in _DEMO_USERS

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
    # Set only for super_admin, frontend shows the warehouse picker.
    requires_warehouse_selection: bool = False
    selection_token: Optional[str] = None   # short-lived token for step 2
    warehouses: Optional[list[WarehouseOption]] = None

class WarehouseSelectRequest(BaseModel):
    selection_token: str   # from step 1
    warehouse_id: str

# ─── demo fallback accounts (no DB row) ──────────────────────────────────────
# Accepted only while ENABLE_DEMO_ACCOUNTS is true (the default). The passwords
# are public, so a production deployment should turn the flag off.

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

@router.post("/login", response_model=LoginResponse, dependencies=[Depends(login_rate_limit)])
def post_login(request: LoginRequest):
    email = request.email.strip().lower()
    password = request.password.strip()
    login_email_rate_limit(email)

    profile = _lookup_profile(email)
    if profile is not None:
        return _authenticate_profile(profile, email, password)

    if not is_demo_email(email):
        log.info("[LOGIN] ✗ %s | no account", _mask_email(email))
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    return _authenticate_demo(email, password)


# ─── POST /auth/login/select-warehouse ────────────────────────────────────────

@router.post("/login/select-warehouse", response_model=LoginResponse, dependencies=[Depends(login_rate_limit)])
def select_warehouse(request: WarehouseSelectRequest):
    """Step 2 for super_admin: verify the short-lived selection token and
    issue a full JWT scoped to the chosen warehouse."""
    try:
        payload = decode_token(request.selection_token)
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired selection token. Please log in again.")

    if payload.get("type") != "warehouse_selection":
        raise HTTPException(status_code=401, detail="Invalid token type.")

    user_id: str = payload["sub"]
    email: str = payload.get("email", "")
    full_name: str = payload.get("full_name", "")

    # The account may have been demoted or deactivated in the minutes since
    # step 1, so it is checked again before a full token is issued.
    profile = _lookup_profile(email.strip().lower()) if email else None
    if profile is not None:
        if (
            str(profile.id) != user_id
            or (profile.role or "").strip().lower() != "super_admin"
            or (profile.status or "").strip().lower() != "active"
        ):
            raise HTTPException(status_code=401, detail="This account can no longer select a warehouse.")
    elif not is_demo_email(email):
        raise HTTPException(status_code=401, detail="Invalid or expired selection token. Please log in again.")

    # Validate the chosen warehouse exists and is active.
    warehouse = _lookup_warehouse(request.warehouse_id)
    if warehouse is None:
        raise HTTPException(status_code=404, detail="Warehouse not found.")
    if not warehouse.is_active:
        raise HTTPException(status_code=400, detail="This warehouse is currently inactive.")

    wh_id = str(warehouse.id)
    wh_name = warehouse.name

    token = _create_token(user_id, email, "super_admin", warehouse_id=wh_id)
    log.info("[LOGIN] ✓ super_admin %s selected warehouse %s (%s)", _mask_email(email), wh_name, wh_id[:8])

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
def list_warehouses(_=Depends(require_super_admin)):
    """Return all active warehouses, for a signed-in super admin.

    The login picker gets the same list in the /auth/login response, so this
    needs no anonymous access.
    """
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


# GET /auth/test was a development stub that returned {"message": "Auth router
# working"} to anonymous callers. It is removed rather than secured: it proved
# only that the router was mounted, which GET / already covers as the service
# health check, and nothing in the product ever called it.


# ─── internal: authenticate ───────────────────────────────────────────────────

def _authenticate_profile(profile, email: str, password: str) -> LoginResponse:
    role = (profile.role or "").strip().lower()
    status = (profile.status or "").strip().lower()
    full_name = profile.full_name or "Unknown"

    if status != "active":
        log.info("[LOGIN] ✗ %s | inactive account", _mask_email(email))
        raise HTTPException(status_code=401, detail="This account is inactive.")

    # Every account signs in with its own stored bcrypt hash. An account with no
    # hash cannot sign in until an administrator sets a password for it.
    meta = profile.meta if isinstance(profile.meta, dict) else {}
    stored_hash = meta.get("password_hash") or ""
    ok = bool(stored_hash) and verify_password(password, stored_hash)

    if not ok:
        log.info("[LOGIN] ✗ %s | wrong password", _mask_email(email))
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    user_id = str(profile.id)

    # ── super_admin: warehouse picker needed ──────────────────────────────────
    if role == "super_admin":
        warehouses = _fetch_all_warehouses()
        selection_token = _create_selection_token(user_id, email, full_name)
        log.info("[LOGIN] ✓ super_admin %s — awaiting warehouse selection", _mask_email(email))
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
        log.info("[LOGIN] ✓ admin %s | warehouse=%s | id=%s", _mask_email(email), wh_name, user_id[:8])
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
    log.info("[LOGIN] ✓ user %s | id=%s", _mask_email(email), user_id[:8])
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
    if not is_demo_email(email):
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
    log.info("[LOGIN] ✓ (demo) %s | role=%s", _mask_email(email), role)
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
    from sqlalchemy import func
    from sqlalchemy.exc import OperationalError
    from app.db import SessionLocal
    from app.models import Profile

    try:
        db = SessionLocal()
    except Exception as e:
        # DB not configured at all (broken/dev environment), demo fallback is
        # the intended path here.
        log.warning("[LOGIN] DB session unavailable (non-fatal): %s", e)
        return None

    try:
        return db.query(Profile).filter(func.lower(Profile.email) == email).first()
    except OperationalError as e:
        # DB is configured but unreachable (e.g. Supabase pooler saturated).
        # This must NOT fall through to the demo fallback: the account may have
        # a real profile row, and the fallback would silently issue a JWT with
        # a synthesized user-id, a fabricated identity that then resolves
        # MockProfile on every request until the token expires.
        log.error("[LOGIN] DB unreachable during profile lookup: %s", e)
        raise HTTPException(
            status_code=503,
            detail="Database temporarily unavailable. Please try again shortly.",
        )
    except Exception as e:
        log.warning("[LOGIN] DB profile lookup failed (non-fatal): %s", e)
        return None
    finally:
        db.close()


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
    """Issue an access token that lives for ACCESS_TOKEN_TTL_MINUTES.

    Includes warehouse_id when provided.
    """
    now = datetime.now(timezone.utc)
    payload: dict = {
        "sub": user_id,
        "email": email,
        "role": role,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=access_token_ttl_minutes()),
        "type": "access",
    }
    if warehouse_id:
        payload["warehouse_id"] = warehouse_id
    return encode_token(payload)


def _create_selection_token(user_id: str, email: str, full_name: str) -> str:
    """Issue a short-lived (5-min) intermediate token for the warehouse picker."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "full_name": full_name,
        "type": "warehouse_selection",
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=5),
    }
    return encode_token(payload)
