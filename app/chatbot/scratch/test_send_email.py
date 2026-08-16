import os
from dotenv import load_dotenv
load_dotenv()

from app.services.notification_service import NotificationService

print("Testing email delivery to aroshnimantha386@gmail.com...")
success = NotificationService.send_email(
    to_emails=["aroshnimantha386@gmail.com"],
    subject="PredictiX Test Email Delivery",
    html_body="<h3>PredictiX Test Email</h3><p>This is a test notification from PredictiX.</p>"
)

print(f"Send email result: {success}")
