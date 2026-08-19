import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast
from sqlalchemy.orm import Session
from uuid import UUID

from ..deps import get_db, get_current_user, is_admin_role
from ..models import Notification, Profile
from ..schemas.notification import NotificationCreate, NotificationOut

log = logging.getLogger(__name__)
router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("", response_model=list[NotificationOut])
def list_user_notifications(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
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

    return q.order_by(Notification.created_at.desc()).offset(offset).limit(limit).all()


@router.get("/unread", response_model=list[NotificationOut])
def get_unread_notifications(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
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
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.get("/{notification_id}", response_model=NotificationOut)
def get_notification(
    notification_id: str,
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a specific notification (user can only see their own)"""
    try:
        notif_id = UUID(notification_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid notification id")

    notification = (
        db.query(Notification)
        .filter(
            (Notification.id == notif_id)
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
    try:
        notif_id = UUID(notification_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid notification id")

    notification = (
        db.query(Notification)
        .filter(
            (Notification.id == notif_id)
            & (Notification.user_id == current_user.id)
        )
        .first()
    )

    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    notification.status = "read"
    # read_at is what the UI sorts and groups by, so a status change without a
    # timestamp leaves the row looking unread to anything that reads the date.
    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
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
    ).update(
        {"status": "read", "read_at": datetime.now(timezone.utc)},
        synchronize_session=False,
    )

    db.commit()

    return {"message": "All notifications marked as read"}


@router.delete("/{notification_id}")
def delete_notification(
    notification_id: str,
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a notification (user can only delete their own)"""
    try:
        notif_id = UUID(notification_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid notification id")

    notification = (
        db.query(Notification)
        .filter(
            (Notification.id == notif_id)
            & (Notification.user_id == current_user.id)
        )
        .first()
    )

    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    db.delete(notification)
    db.commit()
    
    return {"message": "Notification deleted"}


# Path is "" to match the GET above. It was "/", which registered this at
# "/notifications/" while the list endpoint sat at "/notifications", so
# "GET /notifications/" matched this route by path and returned 405 Method Not
# Allowed instead of being redirected to the list. Both now live at the same
# path, and Starlette redirects the trailing-slash form as normal.
@router.post("", response_model=NotificationOut)
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

    # Every field NotificationCreate declares is stored: user_id, channel and
    # the three related_* ids. A field accepted by the schema and then dropped
    # would leave the caller with no sign that it was ignored.
    #
    # Targeting another user is an admin action. Without this check any signed
    # in account could post into anyone else's feed.
    target_user_id = current_user.id
    if data.user_id and str(data.user_id) != str(current_user.id):
        if not is_admin_role(current_user):
            raise HTTPException(
                status_code=403,
                detail="Only admins can create notifications for another user",
            )
        target_user_id = data.user_id

    notification = Notification(
        user_id=target_user_id,
        title=data.title,
        message=data.message,
        type=notif_type,
        channel=data.channel or "in_app",
        related_asset_id=data.related_asset_id,
        related_ticket_id=data.related_ticket_id,
        related_report_id=data.related_report_id,
        meta=meta_data,
        status="unread",
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
