"""FastAPI dependencies: database session and current-user resolution."""
import logging
import os
from typing import Generator, Optional

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.core.config import jwt_secret, jwt_algorithm

log = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_db() -> Generator[Session, None, None]:
    """Yield a SQLAlchemy session.

    If the database is not configured at all (neither DATABASE_URL nor
    DATABASE_PASSWORD set — i.e. a broken/dev environment), raise a clean
    503 instead of yielding None. Previously this yielded None, which made
    every router that assumed a real Session crash with an opaque 500
    (AttributeError: 'NoneType' has no attribute 'query'). A 503 tells the
    caller the service is unavailable, which is the accurate signal.

    Endpoints that historically tolerated a None db still work: they simply
    never reach their `if db is None` branch because this raises first.
    """
    if not os.getenv("DATABASE_PASSWORD") and not os.getenv("DATABASE_URL"):
        raise HTTPException(
            status_code=503,
            detail="Database is not configured — set DATABASE_URL / DATABASE_PASSWORD.",
        )

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Optional[Session] = Depends(get_db),
):
    """Decode JWT and return the matching Profile.

    Falls back to a lightweight in-memory profile when the DB row is
    missing — supports development logins for accounts that exist in
    auth's TEST_USERS but not yet in the profiles table.
    """
    try:
        payload = jwt.decode(
            token,
            jwt_secret(),
            algorithms=[jwt_algorithm()],
        )
    except JWTError as exc:
        log.warning("JWT decode failed: %s", exc)
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    from app.models import Profile  # local import to avoid circular deps

    if db is not None:
        user = db.query(Profile).filter(Profile.id == user_id).first()
        if user:
            # Re-check status on every request, not just at login — otherwise
            # deactivating a user has no effect until their JWT naturally
            # expires (up to 24h), since the token itself carries no status.
            if (user.status or "").strip().lower() != "active":
                raise HTTPException(status_code=401, detail="Account is not active")

            # Super admin JWT carries the warehouse they selected at login.
            # Override the profile's warehouse_id so all downstream queries
            # are automatically scoped to the chosen warehouse.
            jwt_warehouse_id = payload.get("warehouse_id")
            if jwt_warehouse_id:
                user.warehouse_id = jwt_warehouse_id
            return user

    return _build_mock_profile(
        user_id=user_id,
        email=payload.get("email", "test@example.com"),
        role=payload.get("role", "user"),
        warehouse_id=payload.get("warehouse_id"),
        db=db,
    )


def _build_mock_profile(*, user_id: str, email: str, role: str, warehouse_id: Optional[str] = None, db: Optional[Session]):
    """Construct a duck-typed Profile when the DB record is missing."""
    from app.models import Department
    from app.routers.auth import _DEMO_USERS

    # Known demo accounts have a declared full_name — use it instead of
    # deriving one from the email, which yields artifacts like "... Adm1".
    demo = _DEMO_USERS.get(email.lower())
    display_name = demo["full_name"] if demo else email.split("@")[0].replace(".", " ").title()

    department_id = None
    if db is not None:
        from app.models import Warehouse
        
        keyword_to_dept = {
            "transportation": "Transportation",
            "electrical": "Electrical",
            "software": "Software",
            "mechanical": "Mechanical",
        }
        dept_name = next(
            (name for kw, name in keyword_to_dept.items() if kw in email.lower()),
            "Transportation",
        )
        dept = db.query(Department).filter(Department.name == dept_name).first()
        if dept:
            department_id = dept.id
            
        if not warehouse_id:
            first_wh = db.query(Warehouse).filter(Warehouse.is_active == True).first()
            if first_wh:
                warehouse_id = str(first_wh.id)

    class MockProfile:
        def __init__(self) -> None:
            self.id = user_id
            self.email = email
            self.role = role
            self.full_name = display_name
            self.phone = None
            self.status = "active"
            self.warehouse_id = warehouse_id
            self.department_id = department_id
            self.meta = {}
            self.employee_id = f"EMP-{user_id[:8]}"
            self.avatar_url = None

    return MockProfile()


# ─── Role-based access dependencies ────────────────────────────────────────────
# These build on get_current_user (which already validates the JWT). Attach them
# either per-endpoint (Depends(...)) or router-wide (router = APIRouter(
# dependencies=[Depends(require_user)])) to gate access. require_user only
# requires a valid token; require_admin additionally requires an admin role.

# Roles allowed to perform admin actions. super_admin is included on purpose so
# super admins are not locked out of admin-only endpoints.
ADMIN_ROLES = {"admin", "super_admin"}


def _role_of(user) -> str:
    return (getattr(user, "role", "") or "").strip().lower()


def require_user(current_user=Depends(get_current_user)):
    """Dependency: request must carry a valid JWT (any authenticated role).

    get_current_user already raises 401 on a missing/invalid token, so simply
    depending on it is enough — this wrapper exists to give routers a clearly
    named, intention-revealing gate.
    """
    return current_user


def require_admin(current_user=Depends(get_current_user)):
    """Dependency: request must be an authenticated admin or super_admin."""
    if _role_of(current_user) not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


def is_super_admin(user) -> bool:
    return _role_of(user) == "super_admin"


def is_admin_role(user) -> bool:
    """True if the user is an admin OR super_admin.

    Use this for inline role checks inside endpoints instead of comparing
    role == "admin" directly, so super_admins are never locked out of the
    admin operations they are entitled to perform.
    """
    return _role_of(user) in ADMIN_ROLES


def assert_asset_in_scope(asset, current_user) -> None:
    """Block admins/super_admins from reading/writing an asset outside their
    active warehouse. Raises 404 (not 403) so the asset's existence isn't
    revealed across warehouse boundaries — mirrors assets.py's own
    `_assert_asset_in_scope`, exposed here so every asset-detail router
    (sensor readings, predictions, survival curves, etc.) can share the
    identical check instead of re-implementing it. Non-admin users are not
    scoped by this; per-endpoint ownership rules (if any) apply separately.
    """
    if _role_of(current_user) in ADMIN_ROLES:
        wh_id = active_warehouse_id(current_user)
        if wh_id and str(getattr(asset, "warehouse_id", None)) != wh_id:
            raise HTTPException(status_code=404, detail="Asset not found")


def active_warehouse_id(user) -> Optional[str]:
    """The warehouse a request is scoped to.

    Both regular admins and super_admins operate inside exactly one warehouse at
    a time. get_current_user already resolves this: a regular admin's warehouse
    comes from their profile, and a super_admin's comes from the warehouse they
    picked at login (carried in the JWT and written onto user.warehouse_id).
    Returning it as a string keeps callers uniform for filtering.

    The difference between the two roles is *not* what they can do once scoped
    (identical admin operations) but that a super_admin may pick ANY warehouse at
    login while a regular admin is pinned to their own — so both are enforced the
    same way here, via the single active warehouse on the token.
    """
    wid = getattr(user, "warehouse_id", None)
    if not wid:
        raise HTTPException(status_code=400, detail="User is not assigned to any warehouse")
    return str(wid)
