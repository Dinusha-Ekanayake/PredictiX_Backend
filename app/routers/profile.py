"""Profiles router.

    GET    /profiles                 list profiles (admin)
    GET    /profiles/{id}            fetch profile (admin)
    PUT    /profiles/{id}            update profile (admin, schema-based)

    GET    /profiles/me              the authenticated user's full profile
    PUT    /profiles/me              update self (name/phone/address)
    GET    /profiles/me/assets       assets assigned to self
    GET    /profiles/me/stats        asset counts for self
    GET    /profiles/me/colleagues   other users in self's department
"""
from __future__ import annotations

import logging

import io
import os
import uuid as _uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models import Asset, Department, Profile, Warehouse
from app.schemas.profile import ProfileOut, ProfileUpdate
from app.schemas.user_profile import UserProfileUpdate
from app.services.notification_service import NotificationService

log = logging.getLogger(__name__)
router = APIRouter(prefix="/profiles", tags=["Profiles"])


# ─── Admin endpoints ──────────────────────────────────────────────────────────

@router.get("/", response_model=list[ProfileOut])
def list_profiles(
    role: str | None = Query(default=None),
    department_id: str | None = Query(default=None),
    warehouse_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(Profile)
    if role:
        q = q.filter(Profile.role == role)
    if department_id:
        q = q.filter(Profile.department_id == department_id)
    if warehouse_id:
        q = q.filter(Profile.warehouse_id == warehouse_id)
    return q.order_by(Profile.full_name).all()


# ─── Self-service endpoints (/profiles/me) ────────────────────────────────────
# NOTE: these literal "/me" routes are defined BEFORE the parametrized
# "/{profile_id}" routes (at the bottom of this file) so that a request to
# /profiles/me is not captured by /{profile_id} with profile_id="me".

def _split_name(full: str | None) -> tuple[str, str]:
    parts = (full or "").split(" ")
    return parts[0] if parts else "", " ".join(parts[1:]) if len(parts) > 1 else ""


def _profile_to_response(user: Profile, db: Session) -> dict:
    """Build the frontend-friendly self-profile shape."""
    department_name = None
    if user.department_id:
        dept = db.query(Department).filter(Department.id == user.department_id).first()
        department_name = dept.name if dept else None

    warehouse_name = None
    if user.warehouse_id:
        wh = db.query(Warehouse).filter(Warehouse.id == user.warehouse_id).first()
        warehouse_name = wh.name if wh else None

    asset_count = (
        db.query(Asset)
        .filter(Asset.assigned_to == str(user.id), Asset.status == "active")
        .count()
    )

    first_name, last_name = _split_name(user.full_name)
    address = user.meta.get("address") if isinstance(user.meta, dict) else None

    return {
        "id": str(user.id),
        "employee_id": user.employee_id,
        "firstName": first_name,
        "lastName": last_name,
        "name": user.full_name or "",
        "email": user.email or "",
        "contactNumber": user.phone,
        "address": address,
        "department": department_name,
        "department_id": str(user.department_id) if user.department_id else None,
        "warehouse": warehouse_name,
        "warehouse_id": str(user.warehouse_id) if user.warehouse_id else None,
        "role": user.role or "",
        "status": user.status or "",
        "assignedAssetsCount": asset_count,
        "avatar_url": user.avatar_url or None,
    }


@router.get("/me")
def get_my_profile(
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    real_user = db.query(Profile).filter(Profile.email == current_user.email).first() or current_user
    return _profile_to_response(real_user, db)


@router.put("/me")
def update_my_profile(
    payload: UserProfileUpdate,
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.firstName is not None or payload.lastName is not None:
        curr_first, curr_last = _split_name(current_user.full_name)
        first = payload.firstName if payload.firstName is not None else curr_first
        last = payload.lastName if payload.lastName is not None else curr_last
        current_user.full_name = f"{first} {last}".strip()

    if payload.contactNumber is not None:
        current_user.phone = payload.contactNumber

    if payload.address is not None:
        meta = dict(current_user.meta or {})
        meta["address"] = payload.address
        current_user.meta = meta

    if db and hasattr(current_user, "__table__"):
        try:
            db.commit()
            db.refresh(current_user)
            NotificationService.notify_on_profile_update(db, str(current_user.id))
        except Exception:
            db.rollback()
            log.exception("Profile update failed")
            raise HTTPException(status_code=500, detail="Profile update failed")

    return _profile_to_response(current_user, db)


@router.post("/me/avatar")
def upload_my_avatar(
    file: UploadFile = File(...),
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image.")

    contents = file.file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File size must be less than 5MB.")

    ext = (file.filename or "avatar.jpg").rsplit(".", 1)[-1].lower()
    if ext not in {"jpg", "jpeg", "png", "gif", "webp"}:
        ext = "jpg"

    user_id = str(current_user.id)
    filename = f"{user_id}/{_uuid.uuid4()}.{ext}"

    try:
        from app.db.supabase_client import supabase
        supabase.storage.from_("avatars").upload(
            path=filename,
            file=contents,
            file_options={"content-type": file.content_type, "upsert": "true"},
        )
        supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
        avatar_url = f"{supabase_url}/storage/v1/object/public/avatars/{filename}"
    except Exception as e:
        log.warning("[AVATAR] Supabase upload failed: %s — falling back to base64", e)
        import base64
        b64 = base64.b64encode(contents).decode()
        avatar_url = f"data:{file.content_type};base64,{b64}"

    real_user = db.query(Profile).filter(Profile.id == current_user.id).first()
    if not real_user:
        raise HTTPException(status_code=404, detail="Profile not found.")

    real_user.avatar_url = avatar_url
    try:
        db.commit()
        db.refresh(real_user)
    except Exception:
        db.rollback()
        log.exception("Failed to save avatar_url")
        raise HTTPException(status_code=500, detail="Failed to save avatar.")

    return {"avatar_url": avatar_url}


@router.get("/me/assets")
def get_my_assets(
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not db:
        return []

    assets = (
        db.query(Asset)
        .filter(Asset.assigned_to == str(current_user.id), Asset.status == "active")
        .all()
    )

    result = []
    for asset in assets:
        location = ""
        if asset.warehouse_id:
            wh = db.query(Warehouse).filter(Warehouse.id == asset.warehouse_id).first()
            if wh:
                location = wh.name
                if wh.city:
                    location += f" - {wh.city}"

        result.append({
            "assignment_id": str(asset.id),
            "asset_id": str(asset.id),
            "asset_code": asset.asset_code,
            "name": asset.asset_name,
            "asset_type": asset.asset_type,
            "category": asset.category,
            "location": location,
            "status": asset.status or "active",
            "healthPercent": float(asset.criticality_score) if asset.criticality_score is not None else 100.0,
            "nextServiceDate": asset.next_service_date.isoformat() if asset.next_service_date else None,
        })
    return result


@router.get("/me/stats")
def get_my_stats(
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not db:
        return {"assignedAssets": 0, "activeAssets": 0}

    count = (
        db.query(Asset)
        .filter(Asset.assigned_to == str(current_user.id), Asset.status == "active")
        .count()
    )
    return {"assignedAssets": count, "activeAssets": count}


@router.get("/me/colleagues")
def get_my_colleagues(
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    real_user = db.query(Profile).filter(Profile.email == current_user.email).first()
    if not real_user or not real_user.department_id:
        return []

    colleagues = (
        db.query(Profile)
        .filter(Profile.department_id == real_user.department_id, Profile.id != real_user.id)
        .all()
    )

    result = []
    for member in colleagues:
        dept = db.query(Department).filter(Department.id == member.department_id).first()
        first_name, last_name = _split_name(member.full_name)
        result.append({
            "id": str(member.id),
            "employee_id": member.employee_id,
            "firstName": first_name,
            "lastName": last_name,
            "name": member.full_name,
            "email": member.email,
            "contactNumber": member.phone,
            "department": dept.name if dept else "Unknown",
            "role": member.role,
            "status": member.status,
        })
    return result


# ─── Admin endpoints with a path param (registered LAST) ──────────────────────
# Must come after the literal "/me*" routes above, otherwise "/{profile_id}"
# greedily matches "me" and shadows the self-service profile endpoint.

@router.get("/{profile_id}", response_model=ProfileOut)
def get_profile(profile_id: str, db: Session = Depends(get_db)):
    obj = db.query(Profile).filter(Profile.id == profile_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Profile not found")
    return obj


@router.put("/{profile_id}", response_model=ProfileOut)
def update_profile(profile_id: str, payload: ProfileUpdate, db: Session = Depends(get_db)):
    obj = db.query(Profile).filter(Profile.id == profile_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Profile not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(obj, key, value)

    db.commit()
    db.refresh(obj)
    return obj
