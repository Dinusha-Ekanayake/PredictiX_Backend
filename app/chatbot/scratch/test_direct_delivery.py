import os
from dotenv import load_dotenv
load_dotenv()

from app.services.notification_service import NotificationService

to_email = "aroshnimantha386@gmail.com"
subject = "PredictiX Notification: Direct Inbox Delivery Test"
html_body = """
<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; background-color: #f8fafc; padding: 20px; color: #1e293b;">
    <div style="max-width: 580px; margin: 0 auto; background: #ffffff; border-radius: 12px; border: 1px solid #e2e8f0; overflow: hidden;">
        <div style="background: linear-gradient(135deg, #7c3aed 0%, #4f46e5 100%); color: white; padding: 24px; text-align: center;">
            <h2 style="margin: 0;">PredictiX System Online</h2>
        </div>
        <div style="padding: 24px;">
            <p>Hello Aroshan,</p>
            <p>This notification confirms direct inbox delivery for your account.</p>
            <div style="background: #f1f5f9; border-left: 4px solid #10b981; padding: 14px; margin: 15px 0; border-radius: 4px;">
                <strong>Recipient:</strong> aroshnimantha386@gmail.com<br>
                <strong>Support Contact / Reply-To:</strong> neuromindspredictix@gmail.com<br>
                <strong>Status:</strong> Active &amp; Verified
            </div>
            <p>You will now receive all ticket creation, status update, and FAQ notifications immediately in your inbox.</p>
            <p style="margin-top: 20px;">Best regards,<br><strong>PredictiX Team</strong></p>
        </div>
    </div>
</body>
</html>
"""

print(f"Triggering email send to {to_email}...")
res = NotificationService.send_email([to_email], subject, html_body)
print(f"Result: {res}")
