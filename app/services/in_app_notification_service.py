from sqlalchemy.orm import Session
from app.models import Notification, Profile, UserNotificationPreference
import json
import logging

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
            # Check if user has opted out of this notification type
            prefs = db.query(UserNotificationPreference).filter(
                UserNotificationPreference.user_id == user_id,
                UserNotificationPreference.notification_type == notification_type
            ).first()
            
            if prefs and not prefs.enabled:
                return None
                
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
