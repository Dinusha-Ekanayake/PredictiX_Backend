"""Users router — admin-facing CRUD with the frontend's flat UserItemOut shape.

Distinct from /profiles in that it returns the denormalised UserItemOut
shape (department/warehouse as names, name parts split) used by the
user management screens.

    GET    /users                    list all users (UserItemOut)
    POST   /users                    create a new user
    PUT    /users/{user_id}          update a user
    GET    /users/{user_id}/assets   assets assigned to a user
"""
from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import os

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.deps import get_db, get_current_user, require_admin, require_user, active_warehouse_id
from app.models import Asset, Department, PdmBatchPrediction, Profile, Warehouse
from app.services.reference_data_cache import get_department_names, get_warehouse_names
from app.schemas.user_profile import (
    UserAssignedAssetOut,
    UserCreate,
    UserItemOut,
    UserUpdate,
)
from app.services.notification_service import NotificationService

log = logging.getLogger(__name__)
# Any authenticated user may READ the user list (needed by the ticket UI's
# assignee dropdown / name resolution). Mutating endpoints (create/update/delete)
# are individually guarded with require_admin below.
router = APIRouter(
    prefix="/users",
    tags=["Users"],
    dependencies=[Depends(require_user)],
)


def _default_password() -> str:
    """Read DEFAULT_PASSWORD from env, stripping surrounding spaces/quotes."""
    raw = os.getenv("DEFAULT_PASSWORD", "Predictix@123")
    cleaned = raw.strip().strip('"').strip("'").strip()
    return cleaned or "Predictix@123"


def _supabase_admin_client():
    """Build a Supabase Admin client using the service-role key.

    Raises HTTPException(502) if the auth provider isn't configured.
    """
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    supabase_url = os.getenv("SUPABASE_URL")
    if not service_key or not supabase_url:
        raise HTTPException(
            status_code=502,
            detail="Auth provider is not configured (missing service-role key).",
        )
    from supabase import create_client

    return create_client(supabase_url, service_key)


def _create_supabase_auth_user(email: str, password: str) -> str:
    """Create a Supabase auth user via the Admin API (service-role key) and
    return its id. The profiles.id FK references auth.users.id, so the auth
    user MUST exist before the profile row is inserted.

    Raises HTTPException with a clean status on any failure (409 if the email
    already exists, 502/400 otherwise) so the caller never leaks a bare 500.
    """
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    supabase_url = os.getenv("SUPABASE_URL")
    if not service_key or not supabase_url:
        raise HTTPException(
            status_code=502,
            detail="Auth provider is not configured (missing service-role key).",
        )

    # Admin client must use the service-role key (the shared `supabase` client
    # is created with the anon/SUPABASE_KEY and can't perform admin auth ops).
    try:
        from supabase import create_client

        admin = create_client(supabase_url, service_key)
        resp = admin.auth.admin.create_user(
            {"email": email, "password": password, "email_confirm": True}
        )
        user = getattr(resp, "user", None)
        auth_id = getattr(user, "id", None) if user else None
        if not auth_id:
            raise HTTPException(
                status_code=502,
                detail="Auth provider did not return a user id.",
            )
        return str(auth_id)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        log.warning("Supabase admin create_user failed for %s: %s", email, msg)
        low = msg.lower()
        if "already" in low and ("registered" in low or "exist" in low):
            raise HTTPException(
                status_code=409, detail="A user with this email already exists."
            )
        raise HTTPException(
            status_code=502,
            detail=f"Failed to create auth user: {msg}",
        )


def _build_item(
    user: Profile,
    dept_names: dict,
    warehouse_names: dict,
    asset_counts: dict,
) -> UserItemOut:
    """Build a UserItemOut from in-memory lookup maps — no DB calls."""
    department_name = dept_names.get(user.department_id) if user.department_id else None
    warehouse_name = warehouse_names.get(user.warehouse_id) if user.warehouse_id else None
    assigned = asset_counts.get(str(user.id), 0)

    name_parts = (user.full_name or "").split(" ")
    first_name = name_parts[0] if name_parts else ""
    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
    address = user.meta.get("address", "") if isinstance(user.meta, dict) else ""

    return UserItemOut(
        id=str(user.id),
        firstName=first_name,
        lastName=last_name,
        name=user.full_name or "Unknown",
        email=user.email or "",
        address=address,
        contactNumber=user.phone or "",
        warehouse=warehouse_name or "Not assigned",
        role=user.role or "user",
        department=department_name or "Not assigned",
        status=user.status or "inactive",
        assignedAssets=assigned,
    )


def _user_to_item(
    user: Profile,
    db: Session,
    known_department_name: str | None = None,
    known_warehouse_name: str | None = None,
) -> UserItemOut:
    """Single-user variant (used by create/update).

    Callers that already looked up the Department/Warehouse row (e.g. to
    resolve name -> id) can pass the name straight through via
    known_department_name/known_warehouse_name to skip the re-fetch here.
    """
    dept_names = {}
    if user.department_id:
        if known_department_name is not None:
            dept_names[user.department_id] = known_department_name
        else:
            name = db.query(Department.name).filter(Department.id == user.department_id).scalar()
            if name is not None:
                dept_names[user.department_id] = name
    warehouse_names = {}
    if user.warehouse_id:
        if known_warehouse_name is not None:
            warehouse_names[user.warehouse_id] = known_warehouse_name
        else:
            name = db.query(Warehouse.name).filter(Warehouse.id == user.warehouse_id).scalar()
            if name is not None:
                warehouse_names[user.warehouse_id] = name
    assigned = (
        db.query(func.count(Asset.id))
        .filter(Asset.assigned_to == str(user.id), cast(Asset.status, String) == "active")
        .scalar()
        or 0
    )
    asset_counts = {str(user.id): assigned}
    return _build_item(user, dept_names, warehouse_names, asset_counts)


def _fetch_asset_counts() -> dict:
    with SessionLocal() as s:
        return {
            str(assigned_to): count
            for assigned_to, count in s.query(Asset.assigned_to, func.count(Asset.id))
            .filter(Asset.assigned_to.isnot(None), cast(Asset.status, String) == "active")
            .group_by(Asset.assigned_to)
            .all()
        }


def _fetch_users(
    scoped_wh: str | None, limit: int, offset: int, include_unassigned: bool = True
) -> list[Profile]:
    """Profiles for the user directory, scoped to one warehouse.

    ``include_unassigned`` controls the ``warehouse_id IS NULL`` arm. Admins
    need it: that is how a newly-created account with no site yet shows up so
    it can be assigned one. Regular users do not — for them it only leaked the
    global super-admin accounts (which carry no warehouse) into what is
    presented as their warehouse team directory, exposing those names, emails
    and phone numbers to all 1,255 staff across all three sites.
    """
    with SessionLocal() as s:
        q = s.query(Profile)
        if scoped_wh:
            if include_unassigned:
                q = q.filter(
                    (Profile.warehouse_id == scoped_wh) | (Profile.warehouse_id.is_(None))
                )
            else:
                q = q.filter(Profile.warehouse_id == scoped_wh)
        users = q.order_by(Profile.full_name).offset(offset).limit(limit).all()
        s.expunge_all()  # detach so attributes stay readable after the session closes
        return users


@router.get("/", response_model=list[UserItemOut])
def list_users(
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    current_user: Profile = Depends(get_current_user),
):
    # The 4 lookups below are independent reads (no shared state), so they run
    # concurrently on separate DB sessions instead of 4 sequential round-trips.
    # Each round-trip costs ~150-800ms of real network latency to the remote
    # Supabase region — sequentially that summed to ~1.5-2.5s; concurrently it's
    # roughly the slowest single query.
    scoped_wh = active_warehouse_id(current_user)
    # Only staff who manage accounts need to see profiles with no warehouse yet.
    manages_accounts = (current_user.role or "").strip().lower() in ("admin", "super_admin")
    with ThreadPoolExecutor(max_workers=4) as executor:
        dept_future = executor.submit(get_department_names)
        wh_future = executor.submit(get_warehouse_names)
        assets_future = executor.submit(_fetch_asset_counts)
        users_future = executor.submit(
            _fetch_users, scoped_wh, limit, offset, manages_accounts
        )

        dept_names = dept_future.result()
        warehouse_names = wh_future.result()
        asset_counts = assets_future.result()
        users = users_future.result()

    return [_build_item(u, dept_names, warehouse_names, asset_counts) for u in users]


@router.post("/", response_model=UserItemOut, dependencies=[Depends(require_admin)])
def create_user(data: UserCreate, db: Session = Depends(get_db)):
    dept = db.query(Department).filter(Department.name == data.department).first()
    wh = db.query(Warehouse).filter(Warehouse.name == data.warehouse).first()

    # Hash the supplied password, or fall back to the configured default
    # so users created by the frontend (which sends no password yet) can log in.
    raw_password = (data.password or "").strip() or _default_password()

    # profiles.id has an FK to Supabase auth.users.id (profiles_id_fkey), so the
    # auth user must be created FIRST and its id reused as the profile id.
    new_id = uuid.UUID(_create_supabase_auth_user(data.email, raw_password))

    meta = {
        "address": data.address,
        "password_hash": hash_password(raw_password),
    }

    try:
        # Supabase has an on-auth-user-created trigger that auto-inserts a bare
        # profiles row (email only). So UPSERT: update that row if present,
        # otherwise insert a fresh one.
        profile = db.query(Profile).filter(Profile.id == new_id).first()
        if profile is None:
            profile = Profile(id=new_id)
            db.add(profile)

        profile.employee_id = data.id
        profile.full_name = data.name
        profile.email = data.email
        profile.phone = data.contactNumber
        profile.role = data.role
        profile.status = data.status
        profile.department_id = dept.id if dept else None
        profile.warehouse_id = wh.id if wh else None
        profile.meta = meta

        db.commit()
        db.refresh(profile)
    except Exception:
        db.rollback()
        log.exception("User creation failed")
        raise HTTPException(status_code=500, detail="User creation failed")

    try:
        NotificationService.notify_on_new_user(db, str(new_id))
    except Exception:
        log.exception("New-user notification failed (non-fatal)")

    return _user_to_item(
        profile, db,
        known_department_name=dept.name if dept else None,
        known_warehouse_name=wh.name if wh else None,
    )


@router.put("/{user_id}", response_model=UserItemOut, dependencies=[Depends(require_admin)])
def update_user(user_id: str, data: UserUpdate, db: Session = Depends(get_db)):
    user = db.query(Profile).filter(Profile.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if data.name:           user.full_name = data.name
    if data.email:          user.email = data.email
    if data.contactNumber:  user.phone = data.contactNumber
    if data.role:           user.role = data.role
    if data.status:         user.status = data.status

    if data.department:
        dept = db.query(Department).filter(Department.name == data.department).first()
        if dept:
            user.department_id = dept.id

    if data.warehouse:
        wh = db.query(Warehouse).filter(Warehouse.name == data.warehouse).first()
        if wh:
            user.warehouse_id = wh.id

    if data.address:
        meta = dict(user.meta or {})
        meta["address"] = data.address
        user.meta = meta

    try:
        db.commit()
        db.refresh(user)
    except Exception:
        db.rollback()
        log.exception("User update failed")
        raise HTTPException(status_code=500, detail="User update failed")

    return _user_to_item(user, db)


@router.delete("/{user_id}", dependencies=[Depends(require_admin)])
def delete_user(user_id: str, db: Session = Depends(get_db)):
    """Delete a user: removes both the profile row and the Supabase auth user.

    Blocks (409) if the user still has assets assigned, to avoid orphaning
    dependent data. On FK/integrity errors the transaction is rolled back and
    a 409 with the DB message is returned; on Supabase failure a 502 is raised.
    """
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="User not found")

    # Guard: don't orphan assets that are still assigned to this user.
    assigned_count = (
        db.query(func.count(Asset.id))
        .filter(Asset.assigned_to == user_id)
        .scalar()
        or 0
    )
    if assigned_count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"User has {assigned_count} assigned asset(s); "
                   "reassign them before deleting.",
        )

    # Delete the profile row first so the auth.users FK isn't violated, then
    # remove the Supabase auth user.
    try:
        db.delete(profile)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        msg = getattr(getattr(exc, "orig", None), "args", [str(exc)])
        detail = msg[0] if msg else str(exc)
        log.warning("User delete blocked by FK/integrity error for %s: %s", user_id, detail)
        raise HTTPException(status_code=409, detail=f"Cannot delete user: {detail}")
    except Exception:
        db.rollback()
        log.exception("User delete failed")
        raise HTTPException(status_code=500, detail="User deletion failed")

    try:
        admin = _supabase_admin_client()
        admin.auth.admin.delete_user(user_id)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        log.warning("Supabase admin delete_user failed for %s: %s", user_id, msg)
        raise HTTPException(
            status_code=502,
            detail=f"Profile removed but failed to delete auth user: {msg}",
        )

    return {"message": "User deleted", "id": user_id}


@router.get("/{user_id}/assets", response_model=list[UserAssignedAssetOut])
def list_user_assets(user_id: str, db: Session = Depends(get_db)):
    assets = (
        db.query(Asset)
        .filter(Asset.assigned_to == user_id, cast(Asset.status, String) == "active")
        .all()
    )

    warehouse_ids = {a.warehouse_id for a in assets if a.warehouse_id is not None}
    warehouse_names = {
        w.id: w.name
        for w in db.query(Warehouse.id, Warehouse.name).filter(Warehouse.id.in_(warehouse_ids)).all()
    } if warehouse_ids else {}

    # Real health, batched into one query. This was asset.criticality_score —
    # how important the asset is, not how healthy — which the UI renders
    # directly as a coloured health bar. See the same fix in profile.py's
    # /me/assets for the measured divergence.
    asset_ids = [a.id for a in assets]
    health_by_asset: dict = {}
    if asset_ids:
        health_by_asset = {
            row.asset_id: row.health_score
            for row in db.query(
                PdmBatchPrediction.asset_id, PdmBatchPrediction.health_score
            ).filter(
                PdmBatchPrediction.asset_id.in_(asset_ids),
                PdmBatchPrediction.status == "ok",
            ).all()
        }

    result = []
    for asset in assets:
        health = health_by_asset.get(asset.id)
        result.append(UserAssignedAssetOut(
            assignment_id=str(asset.id),
            asset_id=str(asset.id),
            asset_code=asset.asset_code,
            name=asset.asset_name,
            asset_type=asset.asset_type,
            category=asset.category,
            location=warehouse_names.get(asset.warehouse_id, "Unknown"),
            status=asset.status or "active",
            healthPercent=float(health) if health is not None else None,
            nextServiceDate=asset.next_service_date.isoformat() if asset.next_service_date else None,
        ))
    return result
