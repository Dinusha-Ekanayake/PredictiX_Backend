import os
from dotenv import load_dotenv
load_dotenv()

from app.services.notification_service import NotificationService

subject = "PredictiX System: Live Test Email Confirmation"
html_body = """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: 'Segoe UI', Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 20px; color: #1e293b; }
        .container { max-width: 580px; margin: 0 auto; background: #ffffff; border-radius: 12px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }
        .header { background: linear-gradient(135deg, #7c3aed 0%, #4f46e5 100%); color: #ffffff; padding: 28px 24px; text-align: center; }
        .header h1 { margin: 0; font-size: 22px; font-weight: 700; }
        .content { padding: 28px 24px; }
        .badge { display: inline-block; background-color: #10b981; color: #ffffff; padding: 4px 12px; border-radius: 9999px; font-size: 12px; font-weight: 600; margin-bottom: 16px; }
        .box { background: #f1f5f9; border-left: 4px solid #7c3aed; padding: 16px; border-radius: 6px; margin: 20px 0; font-size: 14px; line-height: 1.6; }
        .footer { background: #f8fafc; border-top: 1px solid #e2e8f0; padding: 16px 24px; text-align: center; font-size: 12px; color: #64748b; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>PredictiX Smart Asset Management</h1>
        </div>
        <div class="content">
            <span class="badge">System Online</span>
            <h2>Test Email Verification</h2>
            <p>Hello Aroshan,</p>
            <p>This is a live test email confirming that the <strong>PredictiX Email Notification Service</strong> is operational and delivering messages to your account.</p>
            
            <div class="box">
                <strong>Recipient:</strong> aroshnimantha386@gmail.com<br>
                <strong>Delivery Provider:</strong> Brevo Email API<br>
                <strong>Sender:</strong> PredictiX System (neuromindspredictix@gmail.com)<br>
                <strong>Status:</strong> Active & Verified
            </div>

            <p>You will receive automatic alerts whenever tickets are created, assigned, or updated, as well as when new FAQs are published.</p>
            
            <p style="margin-top: 24px;">Best regards,<br><strong>PredictiX Core System</strong></p>
        </div>
        <div class="footer">
            <p>This is an automated system test message from PredictiX.</p>
        </div>
    </div>
</body>
</html>
"""

print("Sending test email to aroshnimantha386@gmail.com...")
success = NotificationService.send_email(
    to_emails=["aroshnimantha386@gmail.com"],
    subject=subject,
    html_body=html_body
)
print(f"DELIVERY STATUS: {'SUCCESS' if success else 'FAILED'}")
