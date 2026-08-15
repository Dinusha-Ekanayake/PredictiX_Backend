from sqlalchemy.orm import Session
import logging
import asyncio
from datetime import datetime, timezone
from app.models import Notification, Profile, UserNotificationPreference
from app.routers.websockets import notifier
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


class InAppNotificationService:
    @staticmethod
    def _create_notifications_bulk(
        db: Session,
        user_ids: list,
        title: str,
        message: str,
        priority: str,
        notification_type: str,
        link_url: str = None,
        meta: dict = None,
    ) -> list:
        """Create a notification for every id in user_ids with ONE preference
        query, ONE bulk insert, and ONE commit — instead of the naive
        per-user loop (which was N users x [1 preference query + 1 insert +
        1 commit], e.g. ~20-30 round-trips to notify 9 admins). Per-user
        side effects (websocket push, email) still happen individually
        since those aren't DB calls and inherently can't be batched, but
        they run against data already fetched here — no extra queries.
        """
        user_ids = [str(uid) for uid in user_ids if uid]
        if not user_ids:
            return []

        try:
            prefs = (
                db.query(UserNotificationPreference)
                .filter(
                    UserNotificationPreference.user_id.in_(user_ids),
                    UserNotificationPreference.notification_type == notification_type,
                )
                .all()
            )
            prefs_by_user: dict[str, list[UserNotificationPreference]] = {}
            for p in prefs:
                prefs_by_user.setdefault(str(p.user_id), []).append(p)

            # Only fetch profiles up front if any user might need email/sms —
            # decided per-user below, but the query itself is one IN(...) call
            # regardless of how many of them actually end up needing it.
            # Contact info is copied into plain dicts (not kept as live ORM
            # objects) because expire_on_commit=True (the session default)
            # expires every tracked object on the commit below — touching an
            # attribute on a stale ORM object after that silently re-issues
            # a fresh per-object SELECT, defeating the whole point of the
            # batched fetch.
            contact_by_id = {
                str(u.id): {"email": u.email, "phone": u.phone}
                for u in db.query(Profile).filter(Profile.id.in_(user_ids)).all()
            }

            to_insert: list[Notification] = []
            channel_plan: dict[str, dict[str, bool]] = {}

            for user_id in user_ids:
                user_prefs = prefs_by_user.get(user_id, [])
                in_app_enabled = True
                email_enabled = False
                sms_enabled = False
                for p in user_prefs:
                    if p.channel == "in_app":
                        in_app_enabled = p.enabled
                    elif p.channel == "email":
                        email_enabled = p.enabled
                    elif p.channel == "sms":
                        sms_enabled = p.enabled
                if len(user_prefs) == 0:
                    email_enabled = True  # Default true if no prefs set

                channel_plan[user_id] = {
                    "in_app": in_app_enabled,
                    "email": email_enabled,
                    "sms": sms_enabled,
                }

                if in_app_enabled:
                    meta_data = dict(meta or {})
                    if priority:
                        meta_data["priority"] = priority
                    if link_url:
                        meta_data["link_url"] = link_url
                    to_insert.append(
                        Notification(
                            user_id=user_id,
                            title=title,
                            message=message,
                            type=notification_type,
                            meta=meta_data,
                        )
                    )

            # Snapshot the id/created_at each Notification will have BEFORE
            # insert — id is a client-side default (models.Notification.id =
            # Column(..., default=uuid.uuid4)) so it's already known; the
            # timestamp is approximated as "now" for the websocket push
            # rather than round-tripping to read back the server default.
            # This is what lets the commit below be the last DB call in this
            # function — no post-commit refresh() per notification.
            now = datetime.now(timezone.utc)
            websocket_payloads = [
                {
                    "id": str(n.id),
                    "title": n.title,
                    "message": n.message,
                    "type": n.type,
                    "status": "unread",
                    "created_at": now.isoformat(),
                    "meta": n.meta,
                    "user_id": str(n.user_id),
                }
                for n in to_insert
            ]

            created: list[Notification] = []
            if to_insert:
                db.add_all(to_insert)
                db.commit()
                created = to_insert

            # Per-user side effects — no further DB queries, only network
            # calls (websocket push, outbound email) using data captured
            # above (payloads) / before the commit (contact_by_id) so
            # nothing here touches an expired ORM object.
            for payload in websocket_payloads:
                InAppNotificationService._push_websocket(payload)

            for user_id in user_ids:
                plan = channel_plan.get(user_id, {})
                contact = contact_by_id.get(user_id, {})
                if plan.get("email"):
                    InAppNotificationService._send_email_alert(contact.get("email"), title, message, link_url)
                if plan.get("sms"):
                    InAppNotificationService._send_sms_alert(contact.get("phone"), title, message)

            return created
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to create in-app notifications (bulk, {len(user_ids)} recipients): {str(e)}")
            return []

    @staticmethod
    def _push_websocket(payload: dict) -> None:
        """payload is a plain dict (see websocket_payloads in
        _create_notifications_bulk) — never a live ORM object, since those
        can be expired by the commit that happens right before this runs."""
        user_id = payload.pop("user_id")
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(notifier.send_personal_message(payload, user_id))
        except RuntimeError:
            # No running event loop
            asyncio.run(notifier.send_personal_message(payload, user_id))

    @staticmethod
    def _send_email_alert(email: str | None, title: str, message: str, link_url: str = None) -> None:
        if not email:
            return
        subject = f"PredictiX Alert: {title}"
        html_body = f"<html><body><h3>{title}</h3><p>{message}</p>"
        if link_url:
            html_body += f"<p><a href='{link_url}'>View Details</a></p>"
        html_body += "</body></html>"
        NotificationService.send_email([email], subject, html_body)

    @staticmethod
    def _send_sms_alert(phone: str | None, title: str, message: str) -> None:
        phone = phone or "UNKNOWN"
        logger.info(f"[SMS SENT TO {phone}]: {title} - {message}")

    @staticmethod
    def _create_notification(
        db: Session,
        user_id: str,
        title: str,
        message: str,
        priority: str,
        notification_type: str,
        link_url: str = None,
        meta: dict = None,
    ):
        """Single-recipient convenience wrapper around the bulk path."""
        created = InAppNotificationService._create_notifications_bulk(
            db, [user_id], title, message, priority, notification_type, link_url, meta
        )
        return created[0] if created else None

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
        meta: dict = None,
        warehouse_id: str = None,
    ):
        """Notify admins. When warehouse_id is given, scopes to admins whose
        profile.warehouse_id matches PLUS every super_admin (who operate
        across all warehouses) — mirrors the scoping used everywhere else
        in the app (see app.deps.active_warehouse_id / is_admin_role)."""
        query = db.query(Profile.id).filter(Profile.role.in_(["admin", "super_admin"]))
        if warehouse_id:
            query = query.filter(
                (Profile.role == "super_admin") | (Profile.warehouse_id == warehouse_id)
            )
        admin_ids = [row[0] for row in query.all()]
        return InAppNotificationService._create_notifications_bulk(
            db, admin_ids, title, message, priority, notification_type, link_url, meta
        )

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
        user_ids = [
            row[0] for row in
            db.query(Profile.id).filter(Profile.department_id == dept.id).all()
        ]
        return InAppNotificationService._create_notifications_bulk(
            db, user_ids, title, message, priority, notification_type, link_url, meta
        )

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
        user_ids = [row[0] for row in db.query(Profile.id).all()]
        return InAppNotificationService._create_notifications_bulk(
            db, user_ids, title, message, priority, notification_type, link_url, meta
        )
