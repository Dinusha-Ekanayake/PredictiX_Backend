from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.deps import get_db
from app.models import Notification

router = APIRouter(prefix="/notifications", tags=["Notifications"])

@router.get("/user/{user_id}")
def list_user_notifications(user_id: str, db: Session = Depends(get_db)):
    return (
        db.query(Notification)
        .filter(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
        .all()
    )