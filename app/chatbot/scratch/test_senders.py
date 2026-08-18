import os
from dotenv import load_dotenv
load_dotenv()

from app.services.reminder_email_sender import send_email as send_smtp
from app.services.notification_service import NotificationService
import requests

to_test = "aroshnimantha386@gmail.com"

print("--- 1. Testing SMTP (Gmail SMTP) ---")
try:
    send_smtp(
        to_email=to_test,
        subject="[PredictiX Direct SMTP Test] System Verification",
        html_body="<h3>PredictiX SMTP Direct Test</h3><p>This email is sent directly via Gmail SMTP relay!</p>"
    )
    print("SMTP Send: SUCCESS!")
except Exception as e:
    print(f"SMTP Send: FAILED - {e}")

print("\n--- 2. Testing Brevo with sender 'neuromindspredictix@11453287.brevo-mail.com' ---")
try:
    api_key = os.getenv("BREVO_API_KEY")
    resp = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={
            "api-key": api_key,
            "Content-Type": "application/json",
            "accept": "application/json",
        },
        json={
            "sender": {"email": "neuromindspredictix@11453287.brevo-mail.com", "name": "PredictiX System"},
            "to": [{"email": to_test}],
            "subject": "[PredictiX Brevo Verified Test] System Verification",
            "htmlContent": "<h3>PredictiX Brevo Verified Domain Test</h3><p>This email is sent using Brevo verified domain!</p>",
        },
        timeout=15,
    )
    print(f"Brevo Verified Send: {resp.status_code} - {resp.text}")
except Exception as e:
    print(f"Brevo Verified Send: FAILED - {e}")
