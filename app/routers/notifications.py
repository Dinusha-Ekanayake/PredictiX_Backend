import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast
from sqlalchemy.orm import Session
from uuid import UUID

from ..deps import get_db, get_current_user
from ..models import Notification, Profile
from ..schemas.notification import NotificationCreate, NotificationOut

log = logging.getLogger(__name__)
router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("/", response_model=list[NotificationOut])
def list_user_notifications(
    status: str | None = Query(default=None),
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get all notifications for current authenticated user.
    Optional filter by status (unread, read, etc.)
    """
    log.debug("list_user_notifications called with status=%s", status)
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
        & (cast(Notification.status, String) == "unread")
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


@router.post("/", response_model=NotificationOut)
async def create_notification(
    data: NotificationCreate,
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a notification directly in the DB and broadcast via WS"""
    meta_data = data.meta or {}
    if data.priority:
        meta_data["priority"] = data.priority
    if data.link_url:
        meta_data["link_url"] = data.link_url

    notif_type = data.type or "system"
    if notif_type == "system_toast":
        notif_type = "system"

    notification = Notification(
        user_id=current_user.id,
        title=data.title,
        message=data.message,
        type=notif_type,
        meta=meta_data,
        status="unread"
    )
    
    try:
        db.add(notification)
        db.commit()
        db.refresh(notification)
        
        # Broadcast via WebSocket
        from ..routers.websockets import notifier
        payload = {
            "id": str(notification.id),
            "title": notification.title,
            "message": notification.message,
            "type": notification.type,
            "status": notification.status,
            "created_at": notification.created_at.isoformat() if notification.created_at else None,
            "meta": notification.meta,
            "is_from_client": True
        }
        await notifier.send_personal_message(payload, str(current_user.id))
        
        return notification
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
