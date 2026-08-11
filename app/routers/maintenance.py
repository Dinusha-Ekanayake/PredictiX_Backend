from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast
from sqlalchemy.orm import Session
from app.deps import get_db, get_current_user, is_admin_role, require_admin, require_user
from app.models import Asset, MaintenanceEvent
from app.schemas.maintenance import (
    MaintenanceEventCreate,
    MaintenanceEventUpdate,
    MaintenanceEventOut,
)

router = APIRouter(
    prefix="/maintenance",
    tags=["Maintenance"],
    dependencies=[Depends(require_user)],
)


@router.post("/", response_model=MaintenanceEventOut, dependencies=[Depends(require_admin)])
def create_maintenance_event(payload: MaintenanceEventCreate, db: Session = Depends(get_db)):
    asset = db.query(Asset).filter(Asset.id == payload.asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    obj = MaintenanceEvent(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/", response_model=list[MaintenanceEventOut])
def list_maintenance_events(
    asset_id: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    q = db.query(MaintenanceEvent)

    # Regular users only see maintenance history for assets assigned to
    # them — otherwise the shared asset-details panel's Maintenance Logs
    # tab (called with ?asset_id=) would expose service notes/costs for
    # any asset in the fleet, including ones assigned to other employees.
    if not is_admin_role(current_user):
        uid = str(getattr(current_user, "id", ""))
        q = q.join(Asset, MaintenanceEvent.asset_id == Asset.id).filter(
            cast(Asset.assigned_to, String) == uid
        )

    if asset_id:
        q = q.filter(MaintenanceEvent.asset_id == asset_id)
    if event_type:
        q = q.filter(MaintenanceEvent.event_type == event_type)
    return q.order_by(MaintenanceEvent.created_at.desc()).offset(offset).limit(limit).all()


@router.get("/{event_id}", response_model=MaintenanceEventOut)
def get_maintenance_event(
    event_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    obj = db.query(MaintenanceEvent).filter(MaintenanceEvent.id == event_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Maintenance event not found")

    # Same ownership rule as list_maintenance_events above — a regular user
    # may only fetch a single event for an asset assigned to them.
    if not is_admin_role(current_user):
        uid = str(getattr(current_user, "id", ""))
        asset = db.query(Asset).filter(Asset.id == obj.asset_id).first()
        if not asset or str(asset.assigned_to) != uid:
            raise HTTPException(status_code=404, detail="Maintenance event not found")

    return obj


@router.put("/{event_id}", response_model=MaintenanceEventOut, dependencies=[Depends(require_admin)])
def update_maintenance_event(event_id: str, payload: MaintenanceEventUpdate, db: Session = Depends(get_db)):
    obj = db.query(MaintenanceEvent).filter(MaintenanceEvent.id == event_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Maintenance event not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(obj, key, value)

    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{event_id}", dependencies=[Depends(require_admin)])
def delete_maintenance_event(event_id: str, db: Session = Depends(get_db)):
    obj = db.query(MaintenanceEvent).filter(MaintenanceEvent.id == event_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Maintenance event not found")
    db.delete(obj)
    db.commit()
    return {"message": "Maintenance event deleted"}