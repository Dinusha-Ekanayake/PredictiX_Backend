from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast
from sqlalchemy.orm import Session
from uuid import UUID

from ..deps import get_db, get_current_user
from ..models import Notification, Profile
from ..schemas.notification import NotificationCreate, NotificationOut

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("/", response_model=list[NotificationOut])
def list_user_notifications(
    status: str | None = Query(default=None),
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    print(f"DEBUG: list_user_notifications called with status={status}")
    """
    Get all notifications for current authenticated user.
    Optional filter by status (unread, read, etc.)
    """
    q = db.query(Notification).filter(Notification.user_id == current_user.id)
    
    if status:
        q = q.filter(cast(Notification.status, String) == status)
    
    return q.order_by(Notification.created_at.desc()).all()


@router.get("/unread", response_model=list[NotificationOut])
def get_unread_notifications(
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get unread notifications for current user"""
    return (
        db.query(Notification)
        .filter(
            (Notification.user_id == current_user.id)
            & (cast(Notification.status, String) == "unread")
        )
        .order_by(Notification.created_at.desc())
        .all()
    )


@router.get("/{notification_id}", response_model=NotificationOut)
def get_notification(
    notification_id: str,
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a specific notification (user can only see their own)"""
    notification = (
        db.query(Notification)
        .filter(
            (Notification.id == UUID(notification_id))
            & (Notification.user_id == current_user.id)
        )
        .first()
    )
    
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    return notification


@router.put("/{notification_id}/mark-read", response_model=NotificationOut)
def mark_notification_read(
    notification_id: str,
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark a notification as read"""
    notification = (
        db.query(Notification)
        .filter(
            (Notification.id == UUID(notification_id))
            & (Notification.user_id == current_user.id)
        )
        .first()
    )
    
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    notification.status = "read"
    db.commit()
    db.refresh(notification)
    
    return notification


@router.put("/mark-all-read")
def mark_all_notifications_read(
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark all notifications as read for current user"""
    db.query(Notification).filter(
        (Notification.user_id == current_user.id)
        & (Notification.status == "unread")
    ).update({"status": "read"}, synchronize_session=False)
    
    db.commit()
    
    return {"message": "All notifications marked as read"}


@router.delete("/{notification_id}")
def delete_notification(
    notification_id: str,
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a notification (user can only delete their own)"""
    notification = (
        db.query(Notification)
        .filter(
            (Notification.id == UUID(notification_id))
            & (Notification.user_id == current_user.id)
        )
        .first()
    )
    
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    db.delete(notification)
    db.commit()
    
    return {"message": "Notification deleted"}
