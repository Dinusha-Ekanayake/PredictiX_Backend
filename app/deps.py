"""FastAPI dependencies: database session and current-user resolution."""
import logging
import os
from typing import Generator, Optional

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.db import SessionLocal
from app.core.security import InvalidTokenError, decode_token

log = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_db() -> Generator[Session, None, None]:
    """Yield a SQLAlchemy session.

    If the database is not configured at all (neither DATABASE_URL nor
    DATABASE_PASSWORD set, i.e. a broken/dev environment), raise a clean
    503 instead of yielding None. Yielding None makes every router that
    assumes a real Session fail with an opaque 500 (AttributeError:
    'NoneType' has no attribute 'query'), where 503 states accurately that
    the service is unavailable.

    Endpoints that tolerate a None db still work: they simply never reach
    their `if db is None` branch, because this raises first.
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

    A token whose profile row no longer exists is rejected, so deleting an
    account ends its sessions. The one exception is a built-in demo account
    (see app/routers/auth.py), which has no row and gets an in-memory profile
    while demo logins are enabled.
    """
    try:
        payload = decode_token(token)
    except InvalidTokenError as exc:
        log.warning("JWT decode failed: %s", exc)
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    # The 5-minute warehouse-selection token from the super admin login step is
    # signed with the same key, but it is not a session token.
    if payload.get("type", "access") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")

    from app.models import Profile  # local import to avoid circular deps

    if db is not None:
        user = db.query(Profile).filter(Profile.id == user_id).first()
        if user:
            # Re-check status on every request, not just at login, otherwise
            # deactivating a user has no effect until their JWT naturally
            # expires (up to 24h), since the token itself carries no status.
            if (user.status or "").strip().lower() != "active":
                raise HTTPException(status_code=401, detail="Account is not active")

            # A super admin's token carries the warehouse they selected at
            # login, and every downstream query is scoped to it. The value is
            # set as the loaded state rather than as a change, so a commit later
            # in the request never writes it back to their profile row. Admins
            # and users are always scoped by their profile, so a stale token
            # cannot keep them in a warehouse they were moved out of.
            # A commit expires the loaded state and the next read reloads the
            # profile's own warehouse, so the selection is also kept on a plain
            # attribute that active_warehouse_id() reads first.
            jwt_warehouse_id = payload.get("warehouse_id")
            if jwt_warehouse_id and _role_of(user) == "super_admin":
                set_committed_value(user, "warehouse_id", jwt_warehouse_id)
                user._active_warehouse_id = str(jwt_warehouse_id)
            return user

    from app.routers.auth import is_demo_email

    email = payload.get("email") or ""
    if not is_demo_email(email):
        raise HTTPException(status_code=401, detail="Account no longer exists")

    return _build_mock_profile(
        user_id=user_id,
        email=email,
        role=payload.get("role", "user"),
        warehouse_id=payload.get("warehouse_id"),
        db=db,
    )


def _build_mock_profile(*, user_id: str, email: str, role: str, warehouse_id: Optional[str] = None, db: Optional[Session]):
    """Construct a duck-typed Profile when the DB record is missing."""
    from app.models import Department
    from app.routers.auth import _DEMO_USERS

    # Known demo accounts have a declared full_name. Use it instead of
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
    depending on it is enough, this wrapper exists to give routers a clearly
    named, intention-revealing gate.
    """
    return current_user


def require_admin(current_user=Depends(get_current_user)):
    """Dependency: request must be an authenticated admin or super_admin."""
    if _role_of(current_user) not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


def require_super_admin(current_user=Depends(get_current_user)):
    """Dependency: request must be an authenticated super_admin, for
    operations that are fleet-wide/cross-warehouse by nature (e.g.
    triggering a full-fleet batch recompute), where a regular
    warehouse-pinned admin having the same access as an ops-level
    super_admin would let them force an expensive, unscoped operation
    outside their own warehouse boundary."""
    if _role_of(current_user) != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")
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


# Roles a regular admin may give out. Creating or promoting a super admin is a
# super admin's decision alone.
ROLES_ASSIGNABLE_BY_ADMIN = {"user", "admin"}


def assert_can_manage_user(current_user, target) -> None:
    """Allow an admin to read or change `target` only within their scope.

    A super admin may manage anyone. A regular admin may manage users and
    admins of their own active warehouse, never a super admin. Out-of-scope
    targets get 404, so the response does not reveal that the account exists.
    """
    if is_super_admin(current_user):
        return
    if _role_of(target) == "super_admin":
        raise HTTPException(status_code=404, detail="User not found")
    wh_id = scoped_warehouse_id(current_user)
    if wh_id and str(getattr(target, "warehouse_id", None)) != wh_id:
        raise HTTPException(status_code=404, detail="User not found")


def assert_can_assign(
    current_user,
    *,
    role: Optional[str] = None,
    warehouse_id=None,
    clears_warehouse: bool = False,
) -> None:
    """Block a regular admin from granting super admin or moving users elsewhere.

    `clears_warehouse` is set when the request explicitly sets warehouse_id to
    null, which would leave the user outside every warehouse's scope.
    """
    if is_super_admin(current_user):
        return
    if clears_warehouse:
        raise HTTPException(status_code=403, detail="Only a super admin can remove a user's warehouse")
    if role is not None and role.strip().lower() not in ROLES_ASSIGNABLE_BY_ADMIN:
        raise HTTPException(status_code=403, detail="Only a super admin can assign that role")
    wh_id = scoped_warehouse_id(current_user)
    if warehouse_id is not None and wh_id and str(warehouse_id) != wh_id:
        raise HTTPException(status_code=403, detail="Admins can only place users in their own warehouse")


VALID_ROLES = {"user", "admin", "super_admin"}
VALID_STATUSES = {"active", "inactive", "suspended"}
_EMAIL_RE = __import__("re").compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def validate_account_fields(db, target, *, role=None, status=None, email=None) -> None:
    """Reject an invalid role or status, or an email another account already uses.

    Email addresses identify accounts at login, so two profiles must never
    share one.
    """
    from app.models import Profile

    if role is not None and str(role).strip().lower() not in VALID_ROLES:
        raise HTTPException(status_code=422, detail="role must be user, admin or super_admin")
    if status is not None and str(status).strip().lower() not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail="status must be active, inactive or suspended")
    if email is not None:
        normalized = str(email).strip().lower()
        if not _EMAIL_RE.match(normalized):
            raise HTTPException(status_code=422, detail="email is not a valid address")
        from sqlalchemy import func

        clash = db.query(Profile.id).filter(func.lower(Profile.email) == normalized)
        if target is not None:
            clash = clash.filter(Profile.id != target.id)
        if clash.first() is not None:
            raise HTTPException(status_code=409, detail="Another account already uses this email")


def assert_in_active_warehouse(current_user, warehouse_id, what: str = "Record") -> None:
    """404 unless an admin's active warehouse covers `warehouse_id`.

    Super admins act in the warehouse chosen at login, so they are held to it
    the same way. An admin with no warehouse is unscoped.
    """
    wh_id = scoped_warehouse_id(current_user)
    if wh_id and str(warehouse_id) != wh_id:
        raise HTTPException(status_code=404, detail=f"{what} not found")


def assert_asset_in_scope(asset, current_user) -> None:
    """Block admins/super_admins from reading/writing an asset outside their
    active warehouse. Raises 404 (not 403) so the asset's existence isn't
    revealed across warehouse boundaries, mirrors assets.py's own
    `_assert_asset_in_scope`, exposed here so every asset-detail router
    (sensor readings, predictions, survival curves, etc.) can share the
    identical check instead of re-implementing it. Non-admin users are not
    scoped by this; per-endpoint ownership rules (if any) apply separately.
    """
    if _role_of(current_user) in ADMIN_ROLES:
        wh_id = active_warehouse_id(current_user)
        if wh_id and str(getattr(asset, "warehouse_id", None)) != wh_id:
            raise HTTPException(status_code=404, detail="Asset not found")


def user_can_view_asset(asset, current_user) -> bool:
    """True if a non-admin ("user" role) caller may view this asset.

    Same warehouse-wide visibility rule already established for tickets
    (see tickets.py's list_tickets/get_ticket): any user may see any asset
    in their own warehouse, plus any asset specifically assigned to them
    even outside it. Admins/super_admins are scoped separately by
    assert_asset_in_scope above, this only covers the non-admin case,
    which several asset-domain endpoints were found to skip entirely,
    leaving a "user" account with broader read access than a warehouse-
    pinned admin.
    """
    uid = str(getattr(current_user, "id", ""))
    user_wh_id = getattr(current_user, "warehouse_id", None)
    if user_wh_id is not None and str(getattr(asset, "warehouse_id", None)) == str(user_wh_id):
        return True
    return str(getattr(asset, "assigned_to", None)) == uid


def active_warehouse_id(user) -> Optional[str]:
    """The warehouse a request is scoped to.

    Both regular admins and super_admins operate inside exactly one warehouse at
    a time. get_current_user already resolves this: a regular admin's warehouse
    comes from their profile, and a super_admin's comes from the warehouse they
    picked at login (carried in the JWT and written onto user.warehouse_id).
    Returning it as a string keeps callers uniform for filtering.

    The difference between the two roles is *not* what they can do once scoped
    (identical admin operations) but that a super_admin may pick ANY warehouse at
    login while a regular admin is pinned to their own, so both are enforced the
    same way here, via the single active warehouse on the token.
    """
    wid = scoped_warehouse_id(user)
    if not wid:
        raise HTTPException(status_code=400, detail="User is not assigned to any warehouse")
    return wid


def scoped_warehouse_id(user) -> Optional[str]:
    """Like active_warehouse_id, but None instead of an error when there is none."""
    wid = getattr(user, "_active_warehouse_id", None) or getattr(user, "warehouse_id", None)
    return str(wid) if wid else None
