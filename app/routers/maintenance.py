from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast
from sqlalchemy.orm import Session
from app.deps import get_db, get_current_user, is_admin_role, require_admin, require_user
from app.models import Asset, MaintenanceEvent, Profile
from app.routers.assets import _assert_asset_in_scope
from app.schemas.maintenance import (
    MaintenanceEventCreate,
    MaintenanceEventUpdate,
    MaintenanceEventOut,
    MaintenanceLogRequest,
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


#: Mirrors the ``maintenance_event_type`` Postgres enum. Validated here so an
#: unknown value is a 422 rather than a driver-level 500 on INSERT.
_VALID_EVENT_TYPES = {
    "inspection", "scheduled_service", "preventive", "corrective",
    "repair", "replacement", "breakdown", "other",
}


@router.post(
    "/log-maintenance/{asset_id}",
    response_model=MaintenanceEventOut,
    dependencies=[Depends(require_admin)],
    summary="Record a completed service against an asset",
)
def log_maintenance(
    asset_id: UUID,
    payload: MaintenanceLogRequest,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    """Record a completed service and advance the asset's service state.

    The asset page has always called this path, but the route did not exist —
    every "Log Maintenance" save returned 404. ``POST /maintenance/`` could not
    stand in for it: that endpoint is a bare row insert which needs
    ``asset_id`` and ``event_type`` in the body, and has nowhere to put
    ``next_service_date``, so using it would have silently dropped the service
    schedule update that is the point of logging the work.

    Logging a service therefore does three things in one transaction:

    * writes the ``maintenance_events`` row, attributed to the caller;
    * moves the asset's ``last_service_date`` to when the work was done and
      ``next_service_date`` to the date the operator scheduled;
    * advances ``current_mileage`` when the reported odometer is higher.

    Mileage only ever moves forward: an odometer below the recorded mileage is
    rejected rather than silently winding the asset back. The dialog checks
    this too, but a client-side check is a convenience, not a guarantee.
    """
    event_type = (payload.event_type or "scheduled_service").strip().lower()
    if event_type not in _VALID_EVENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid event_type '{payload.event_type}'. "
                   f"Valid: {sorted(_VALID_EVENT_TYPES)}",
        )

    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    _assert_asset_in_scope(asset, current_user)

    if (
        payload.odometer_reading is not None
        and asset.current_mileage is not None
        and payload.odometer_reading < asset.current_mileage
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Odometer reading ({payload.odometer_reading}) is below the "
                f"asset's recorded mileage ({asset.current_mileage})."
            ),
        )

    performed_at = payload.performed_at or datetime.now(timezone.utc)

    event = MaintenanceEvent(
        asset_id=asset.id,
        event_type=event_type,
        title=payload.title.strip(),
        description=payload.description,
        # Audit trail: who logged it, taken from the token rather than the body.
        performed_by=current_user.id,
        performed_at=performed_at,
        odometer_reading=payload.odometer_reading,
        downtime_hours=payload.downtime_hours,
        cost_amount=payload.cost_amount,
        currency="LKR",
        vendor_name=payload.vendor_name,
        notes=payload.notes,
    )
    db.add(event)

    asset.last_service_date = performed_at.date()
    if payload.next_service_date is not None:
        asset.next_service_date = payload.next_service_date
    if payload.odometer_reading is not None and (
        asset.current_mileage is None or payload.odometer_reading > asset.current_mileage
    ):
        asset.current_mileage = payload.odometer_reading

    try:
        db.commit()
    except Exception:
        # One transaction covers the event and the asset update — a partial
        # write would leave a service recorded against stale service dates.
        db.rollback()
        raise
    db.refresh(event)
    return event


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