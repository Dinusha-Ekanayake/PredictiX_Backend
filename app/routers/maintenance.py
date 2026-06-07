from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.deps import get_db
from app.models import MaintenanceEvent
from app.schemas.maintenance import (
    MaintenanceEventCreate,
    MaintenanceEventUpdate,
    MaintenanceEventOut,
)
from app.services.in_app_notification_service import InAppNotificationService
from app.models import Asset

router = APIRouter(prefix="/maintenance", tags=["Maintenance"])


@router.post("/", response_model=MaintenanceEventOut)
def create_maintenance_event(payload: MaintenanceEventCreate, db: Session = Depends(get_db)):
    obj = MaintenanceEvent(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    
    # Notify assigned user
    try:
        asset = db.query(Asset).filter(Asset.id == obj.asset_id).first()
        if asset and asset.assigned_to:
            InAppNotificationService.notify_user(
                db=db,
                user_id=str(asset.assigned_to),
                title="Maintenance Scheduled",
                message=f"Heads up! Asset {asset.asset_code or 'assigned to you'} is scheduled for maintenance: {obj.title}.",
                priority="medium",
                notification_type="general",
                link_url=f"/user/assets/{asset.id}"
            )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Failed to send maintenance notification: %s", exc)
        
    return obj


@router.get("/", response_model=list[MaintenanceEventOut])
def list_maintenance_events(
    asset_id: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(MaintenanceEvent)
    if asset_id:
        q = q.filter(MaintenanceEvent.asset_id == asset_id)
    if event_type:
        q = q.filter(MaintenanceEvent.event_type == event_type)
    return q.order_by(MaintenanceEvent.created_at.desc()).all()


@router.get("/{event_id}", response_model=MaintenanceEventOut)
def get_maintenance_event(event_id: str, db: Session = Depends(get_db)):
    obj = db.query(MaintenanceEvent).filter(MaintenanceEvent.id == event_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Maintenance event not found")
    return obj


@router.put("/{event_id}", response_model=MaintenanceEventOut)
def update_maintenance_event(event_id: str, payload: MaintenanceEventUpdate, db: Session = Depends(get_db)):
    obj = db.query(MaintenanceEvent).filter(MaintenanceEvent.id == event_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Maintenance event not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(obj, key, value)

    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{event_id}")
def delete_maintenance_event(event_id: str, db: Session = Depends(get_db)):
    obj = db.query(MaintenanceEvent).filter(MaintenanceEvent.id == event_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Maintenance event not found")
    db.delete(obj)
    db.commit()
    return {"message": "Maintenance event deleted"}