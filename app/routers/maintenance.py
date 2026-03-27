from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.deps import get_db
from app.models import MaintenanceEvent

router = APIRouter(prefix="/maintenance-events", tags=["Maintenance Events"])

@router.get("/")
def list_maintenance_events(db: Session = Depends(get_db)):
    return db.query(MaintenanceEvent).order_by(MaintenanceEvent.created_at.desc()).all()

@router.get("/{event_id}")
def get_maintenance_event(event_id: str, db: Session = Depends(get_db)):
    obj = db.query(MaintenanceEvent).filter(MaintenanceEvent.id == event_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Maintenance event not found")
    return obj