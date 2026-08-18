import os
from dotenv import load_dotenv
load_dotenv()

from app.services.reminder_email_sender import send_email as send_smtp
from app.services.notification_service import NotificationService

to_email = "aroshnimantha386@gmail.com"

subject = "PredictiX Notification: Live System Test"
html_body = """
<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; background-color: #f1f5f9; padding: 20px;">
    <div style="max-width: 580px; margin: 0 auto; background: #ffffff; border-radius: 12px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);">
        <div style="background: linear-gradient(135deg, #7c3aed 0%, #4f46e5 100%); color: white; padding: 24px; text-align: center;">
            <h2 style="margin: 0; font-size: 22px;">PredictiX Notification System</h2>
        </div>
        <div style="padding: 24px; color: #1e293b;">
            <p style="font-size: 16px;">Hello Aroshan,</p>
            <p>This is a live test email sent directly from your PredictiX System.</p>
            
            <div style="background: #f8fafc; border-left: 4px solid #7c3aed; padding: 15px; margin: 20px 0; border-radius: 4px;">
                <strong>Recipient:</strong> aroshnimantha386@gmail.com<br>
                <strong>Status:</strong> Active & Connected<br>
                <strong>System:</strong> PredictiX Smart Asset Management
            </div>

            <p>Your ticket creation, assignment, and status update notifications are fully active.</p>
            
            <p style="margin-top: 24px;">Best regards,<br><strong>PredictiX Team</strong></p>
        </div>
    </div>
</body>
</html>
"""

print(f"Sending live email to {to_email} via SMTP...")
send_smtp(
    to_email=to_email,
    subject=subject,
    html_body=html_body,
)
print("SUCCESS: Test email delivered via SMTP!")

print(f"Sending live email to {to_email} via Brevo...")
NotificationService.send_email([to_email], subject, html_body)
print("SUCCESS: Test email dispatched via Brevo API!")
