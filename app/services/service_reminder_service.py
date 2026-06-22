"""Service reminder logic — autonomous sweep + manual admin trigger.

Reads next_service_date from the assets table. The same _send_and_log()
function is used by both the daily cron job and the admin button.
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import String, cast
from sqlalchemy.orm import Session

from app.models import Asset, Profile, ServiceReminderLog
from app.services.reminder_email_sender import EmailSendError, send_email
from app.services.reminder_email_template import service_reminder_html
log = logging.getLogger(__name__)


def _get_reminder_offsets() -> list[int]:
    raw = os.getenv("SERVICE_REMINDER_OFFSETS", "14,7,3,1")
    try:
        offsets = sorted({int(x.strip()) for x in raw.split(",") if x.strip()}, reverse=True)
        return offsets or [14, 7, 3, 1]
    except ValueError:
        log.warning("Invalid SERVICE_REMINDER_OFFSETS=%r — falling back", raw)
        return [14, 7, 3, 1]


def _already_sent_auto(
    db: Session, asset_id: UUID, service_date: date, offset_days: int
) -> bool:
    return (
        db.query(ServiceReminderLog)
        .filter(
            ServiceReminderLog.asset_id == asset_id,
            ServiceReminderLog.service_date == service_date,
            ServiceReminderLog.reminder_offset_days == offset_days,
            ServiceReminderLog.trigger == "auto",
            ServiceReminderLog.success.is_(True),
        )
        .first()
        is not None
    )


def _resolve_warehouse_name(db: Session, warehouse_id) -> Optional[str]:
    try:
        from app.models import Warehouse
        w = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
        if not w:
            return None
        return (
            getattr(w, "name", None)
            or getattr(w, "warehouse_name", None)
            or getattr(w, "code", None)
        )
    except Exception:
        return None


def _send_and_log(
    db: Session,
    *,
    asset: Asset,
    user: Profile,
    offset_days: int,
    trigger: str,
    sent_by: Optional[UUID] = None,
) -> dict:
    if not user.email:
        log.warning("Asset %s assignee %s has no email — skipping", asset.id, user.id)
        return {"sent": False, "reason": "user_has_no_email", "asset_id": str(asset.id)}

    today = date.today()
    days_remaining = (asset.next_service_date - today).days
    warehouse_name = _resolve_warehouse_name(db, asset.warehouse_id)

    html, plain = service_reminder_html(
        user_name=(user.full_name or user.email.split("@")[0]),
        asset_name=asset.asset_name,
        asset_code=asset.asset_code,
        asset_type=asset.asset_type or "Asset",
        next_service_date=asset.next_service_date,
        days_remaining=days_remaining,
        warehouse_name=warehouse_name,
        dashboard_url=os.getenv("FRONTEND_URL"),
    )

    if days_remaining <= 1:
        subject = f"[PredictiX] Service due tomorrow — {asset.asset_name}"
    else:
        subject = f"[PredictiX] Service reminder ({days_remaining} days) — {asset.asset_name}"

    success = True
    error_message: Optional[str] = None
    try:
        send_email(to_email=user.email, subject=subject, html_body=html, plain_body=plain)
    except EmailSendError as exc:
        success = False
        error_message = str(exc)
        log.warning("Failed to send reminder for asset %s: %s", asset.id, exc)

    db.add(
        ServiceReminderLog(
            asset_id=asset.id,
            user_id=user.id,
            service_date=asset.next_service_date,
            reminder_offset_days=offset_days,
            trigger=trigger,
            sent_by=sent_by,
            email_to=user.email,
            success=success,
            error_message=error_message,
        )
    )
    db.commit()

    return {
        "sent": success,
        "to": user.email,
        "asset_id": str(asset.id),
        "service_date": asset.next_service_date.isoformat(),
        "days_remaining": days_remaining,
        "trigger": trigger,
        "error": error_message,
    }


def send_manual_reminder(db: Session, *, asset_id: UUID, sent_by: UUID) -> dict:
    """Admin button-triggered: send a reminder for one asset, immediately."""
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise ValueError("Asset not found")
    if not asset.next_service_date:
        raise ValueError("Asset has no next_service_date set")
    if not asset.assigned_to:
        raise ValueError("Asset is not assigned to any user")

    user = db.query(Profile).filter(Profile.id == asset.assigned_to).first()
    if not user:
        raise ValueError("Assigned user not found")

    offset_days = max((asset.next_service_date - date.today()).days, 0)
    return _send_and_log(
        db, asset=asset, user=user,
        offset_days=offset_days, trigger="manual", sent_by=sent_by,
    )


def run_auto_reminder_sweep(db: Session) -> dict:
    """Daily job — find assets where next_service_date is close and email assignees."""
    offsets = _get_reminder_offsets()
    today = date.today()
    target_dates = {today + timedelta(days=n): n for n in offsets}

    log.info("Service reminder sweep — offsets=%s, today=%s", offsets, today.isoformat())

    due_assets = (
        db.query(Asset)
        .filter(
            Asset.next_service_date.in_(list(target_dates.keys())),
            Asset.assigned_to.isnot(None),
            cast(Asset.status, String) == "active",
        )
        .all()
    )

    stats = {"checked": len(due_assets), "sent": 0, "skipped": 0, "failed": 0}

    for asset in due_assets:
        offset = target_dates[asset.next_service_date]

        if _already_sent_auto(db, asset.id, asset.next_service_date, offset):
            stats["skipped"] += 1
            continue

        user = db.query(Profile).filter(Profile.id == asset.assigned_to).first()
        if not user:
            log.warning("Asset %s assigned_to=%s but profile not found", asset.id, asset.assigned_to)
            stats["skipped"] += 1
            continue

        result = _send_and_log(
            db, asset=asset, user=user, offset_days=offset, trigger="auto"
        )
        if result["sent"]:
            stats["sent"] += 1
        else:
            stats["failed"] += 1

    log.info("Service reminder sweep complete — %s", stats)
    return stats