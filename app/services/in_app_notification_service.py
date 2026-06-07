from sqlalchemy.orm import Session
from app.models import Notification, Profile, UserNotificationPreference
import json
import logging
import asyncio
from app.routers.websockets import notifier
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

class InAppNotificationService:
    @staticmethod
    def _create_notification(
        db: Session,
        user_id: str,
        title: str,
        message: str,
        priority: str,
        notification_type: str,
        link_url: str = None,
        meta: dict = None
    ):
        try:
            # Check preferences for all channels
            prefs = db.query(UserNotificationPreference).filter(
                UserNotificationPreference.user_id == user_id,
                UserNotificationPreference.notification_type == notification_type
            ).all()
            
            in_app_enabled = True
            email_enabled = False
            sms_enabled = False
            
            for p in prefs:
                if p.channel == "in_app":
                    in_app_enabled = p.enabled
                elif p.channel == "email":
                    email_enabled = p.enabled
                elif p.channel == "sms":
                    sms_enabled = p.enabled
                    
            if len(prefs) == 0:
                email_enabled = True # Default true if no prefs set
                
            notification = None
            if in_app_enabled:
                meta_data = meta or {}
                if priority:
                    meta_data["priority"] = priority
                if link_url:
                    meta_data["link_url"] = link_url
                    
                notification = Notification(
                    user_id=user_id,
                    title=title,
                    message=message,
                    type=notification_type,
                    meta=meta_data
                )
                db.add(notification)
                db.commit()
                db.refresh(notification)
                
                # Push to websocket
                payload = {
                    "id": str(notification.id),
                    "title": notification.title,
                    "message": notification.message,
                    "type": notification.type,
                    "status": notification.status,
                    "created_at": notification.created_at.isoformat() if notification.created_at else None,
                    "meta": notification.meta
                }
                
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(notifier.send_personal_message(payload, str(user_id)))
                except RuntimeError:
                    # No running event loop
                    asyncio.run(notifier.send_personal_message(payload, str(user_id)))
                    
            # Send Email
            if email_enabled:
                user = db.query(Profile).filter(Profile.id == user_id).first()
                if user and user.email:
                    subject = f"PredictiX Alert: {title}"
                    html_body = f"<html><body><h3>{title}</h3><p>{message}</p>"
                    if link_url:
                        html_body += f"<p><a href='{link_url}'>View Details</a></p>"
                    html_body += "</body></html>"
                    
                    NotificationService.send_email(
                        [user.email], 
                        subject, 
                        html_body,
                        template_params={"name": user.full_name, "message": message, "time": ""}
                    )
            
            # Send SMS (Mocked)
            if sms_enabled:
                user = db.query(Profile).filter(Profile.id == user_id).first()
                phone = user.phone if user and user.phone else "UNKNOWN"
                logger.info(f"[SMS SENT TO {phone}]: {title} - {message}")
                print(f"[SMS SENT TO {phone}]: {title} - {message}")

            return notification
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to create in-app notification: {str(e)}")
            return None

    @staticmethod
    def notify_user(
        db: Session,
        user_id: str,
        title: str,
        message: str,
        priority: str = "medium",
        notification_type: str = "system",
        link_url: str = None,
        meta: dict = None
    ):
        return InAppNotificationService._create_notification(
            db, user_id, title, message, priority, notification_type, link_url, meta
        )

    @staticmethod
    def notify_admins(
        db: Session,
        title: str,
        message: str,
        priority: str = "medium",
        notification_type: str = "system",
        link_url: str = None,
        meta: dict = None
    ):
        admins = db.query(Profile).filter(Profile.role == "admin").all()
        created = []
        for admin in admins:
            notif = InAppNotificationService._create_notification(
                db, admin.id, title, message, priority, notification_type, link_url, meta
            )
            if notif:
                created.append(notif)
        return created

    @staticmethod
    def notify_department(
        db: Session,
        department_name: str,
        title: str,
        message: str,
        priority: str = "medium",
        notification_type: str = "system",
        link_url: str = None,
        meta: dict = None
    ):
        from app.models import Department
        dept = db.query(Department).filter(Department.name == department_name).first()
        if not dept:
            return []
        users = db.query(Profile).filter(Profile.department_id == dept.id).all()
        created = []
        for user in users:
            notif = InAppNotificationService._create_notification(
                db, user.id, title, message, priority, notification_type, link_url, meta
            )
            if notif:
                created.append(notif)
        return created

    @staticmethod
    def notify_all_users(
        db: Session,
        title: str,
        message: str,
        priority: str = "low",
        notification_type: str = "system",
        link_url: str = None,
        meta: dict = None
    ):
        users = db.query(Profile).all()
        created = []
        for user in users:
            notif = InAppNotificationService._create_notification(
                db, user.id, title, message, priority, notification_type, link_url, meta
            )
            if notif:
                created.append(notif)
        return created
