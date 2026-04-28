from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.deps import get_db
from app.models import DateNotification
from app.services.notification_service import check_and_send_maintenance_notifications
from pydantic import BaseModel
from datetime import datetime

router = APIRouter(prefix="/date-notifications", tags=["Maintenance Date Notifications"])

class DateNotificationOut(BaseModel):
    id: str
    asset_id: str
    user_email: str
    notification_type: str
    sent_at: datetime

    class Config:
        from_attributes = True

@router.post("/trigger")
def trigger_notifications(db: Session = Depends(get_db)):
    """
    Manually triggers the maintenance date notification check.
    """
    result = check_and_send_maintenance_notifications(db)
    return result

@router.get("/", response_model=list[DateNotificationOut])
def get_sent_notifications(db: Session = Depends(get_db)):
    """
    Retrieves a list of sent notifications.
    """
    notifications = db.query(DateNotification).order_by(DateNotification.sent_at.desc()).all()
    # Convert UUIDs to strings for pydantic serialization
    results = []
    for notif in notifications:
        results.append({
            "id": str(notif.id),
            "asset_id": str(notif.asset_id),
            "user_email": notif.user_email,
            "notification_type": notif.notification_type,
            "sent_at": notif.sent_at
        })
    return results
