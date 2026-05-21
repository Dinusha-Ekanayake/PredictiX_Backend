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

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import Asset, Department, Profile, Warehouse
from app.schemas.user_profile import (
    UserAssignedAssetOut,
    UserCreate,
    UserItemOut,
    UserUpdate,
)
from app.services.notification_service import NotificationService

log = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["Users"])


def _user_to_item(user: Profile, db: Session) -> UserItemOut:
    department_name = (
        db.query(Department.name).filter(Department.id == user.department_id).scalar()
        if user.department_id else None
    )
    warehouse_name = (
        db.query(Warehouse.name).filter(Warehouse.id == user.warehouse_id).scalar()
        if user.warehouse_id else None
    )
    assigned = (
        db.query(Asset)
        .filter(Asset.assigned_to == str(user.id), Asset.status == "active")
        .count()
    )

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


@router.get("/", response_model=list[UserItemOut])
def list_users(db: Session = Depends(get_db)):
    return [_user_to_item(u, db) for u in db.query(Profile).all()]


@router.post("/", response_model=UserItemOut)
def create_user(data: UserCreate, db: Session = Depends(get_db)):
    dept = db.query(Department).filter(Department.name == data.department).first()
    wh = db.query(Warehouse).filter(Warehouse.name == data.warehouse).first()

    new_id = uuid.uuid4()
    profile = Profile(
        id=new_id,
        employee_id=data.id,
        full_name=data.name,
        email=data.email,
        phone=data.contactNumber,
        role=data.role,
        status=data.status,
        department_id=dept.id if dept else None,
        warehouse_id=wh.id if wh else None,
        meta={"address": data.address},
    )

    try:
        db.add(profile)
        db.commit()
    except Exception:
        db.rollback()
        log.exception("User creation failed")
        raise HTTPException(status_code=500, detail="User creation failed")

    try:
        NotificationService.notify_on_new_user(db, str(new_id))
    except Exception:
        log.exception("New-user notification failed (non-fatal)")

    return _user_to_item(profile, db)


@router.put("/{user_id}", response_model=UserItemOut)
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


@router.get("/{user_id}/assets", response_model=list[UserAssignedAssetOut])
def list_user_assets(user_id: str, db: Session = Depends(get_db)):
    assets = (
        db.query(Asset)
        .filter(Asset.assigned_to == user_id, Asset.status == "active")
        .all()
    )

    result = []
    for asset in assets:
        wh = db.query(Warehouse).filter(Warehouse.id == asset.warehouse_id).first()
        result.append(UserAssignedAssetOut(
            assignment_id=str(asset.id),
            asset_id=str(asset.id),
            asset_code=asset.asset_code,
            name=asset.asset_name,
            asset_type=asset.asset_type,
            category=asset.category,
            location=wh.name if wh else "Unknown",
            status=asset.status or "active",
            healthPercent=float(asset.criticality_score or 100),
            nextServiceDate=asset.next_service_date.isoformat() if asset.next_service_date else None,
        ))
    return result
