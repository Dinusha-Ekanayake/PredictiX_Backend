import smtplib
import logging
from email.message import EmailMessage
from datetime import date, timedelta
from sqlalchemy.orm import Session
from app.models import Asset, Profile, AssetFailurePrediction, DateNotification
from app.core.config import settings

logger = logging.getLogger(__name__)

def send_email(to_email: str, subject: str, content: str):
    """
    Sends an email using the SMTP settings from config.
    """
    if not settings.EMAIL_HOST or not settings.EMAIL_USER or not settings.EMAIL_PASSWORD:
        logger.warning(f"Email settings not fully configured. Skipping email to {to_email}")
        return False

    msg = EmailMessage()
    msg.set_content(content)
    msg["Subject"] = subject
    msg["From"] = settings.EMAIL_USER
    msg["To"] = to_email

    try:
        with smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT) as server:
            server.starttls()
            server.login(settings.EMAIL_USER, settings.EMAIL_PASSWORD)
            server.send_message(msg)
            logger.info(f"Email sent successfully to {to_email}")
            return True
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False

def check_and_send_maintenance_notifications(db: Session):
    """
    Checks for upcoming predicted maintenance dates and sends notifications.
    """
    today = date.today()
    intervals = {
        1: "1_day",
        2: "2_days",
        3: "3_days"
    }
    
    # Target dates
    target_dates = {today + timedelta(days=days): label for days, label in intervals.items()}

    # Query active assets with a predicted maintenance date and assigned user
    predictions = db.query(AssetFailurePrediction, Asset, Profile).join(
        Asset, AssetFailurePrediction.asset_id == Asset.id
    ).join(
        Profile, Asset.assigned_to == Profile.id
    ).filter(
        Asset.status == "active",
        AssetFailurePrediction.predicted_maintenance_date.in_(target_dates.keys())
    ).all()

    for prediction, asset, profile in predictions:
        pred_date = prediction.predicted_maintenance_date
        notification_type = target_dates[pred_date]
        user_email = profile.email
        
        if not user_email:
            continue

        # Check if notification was already sent
        existing_notification = db.query(DateNotification).filter(
            DateNotification.asset_id == asset.id,
            DateNotification.notification_type == notification_type
        ).first()

        if existing_notification:
            continue

        # Prepare email content
        days_remaining = (pred_date - today).days
        subject = f"Maintenance Alert: {asset.asset_name} requires maintenance soon"
        content = f"""
Hello {profile.full_name},

This is a reminder that the asset "{asset.asset_name}" (Code: {asset.asset_code}) is predicted to require maintenance soon.

Predicted Maintenance Date: {pred_date.strftime('%Y-%m-%d')}
Days Remaining: {days_remaining}

Please review the asset and schedule maintenance if necessary.

Best regards,
PredictiX System
"""
        
        # Send email
        email_sent = send_email(user_email, subject, content)

        # Log notification in database
        if email_sent:
            new_notification = DateNotification(
                asset_id=asset.id,
                user_email=user_email,
                notification_type=notification_type
            )
            db.add(new_notification)
            try:
                db.commit()
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to save notification record for asset {asset.id}: {e}")

    return {"status": "success", "message": "Notification check completed."}
