import os
import requests
from dotenv import load_dotenv
load_dotenv()

api_key = os.getenv("BREVO_API_KEY")
to_email = "aroshnimantha386@gmail.com"
sender_email = "neuromindspredictix@gmail.com"

print(f"Sending test email from {sender_email} to {to_email} via Brevo API...")

resp = requests.post(
    "https://api.brevo.com/v3/smtp/email",
    headers={
        "api-key": api_key,
        "Content-Type": "application/json",
        "accept": "application/json",
    },
    json={
        "sender": {"email": sender_email, "name": "PredictiX System"},
        "to": [{"email": to_email}],
        "subject": "PredictiX Official Alert: Verified neuromindspredictix@gmail.com Delivery",
        "htmlContent": """
        <html>
        <body style="font-family: Arial, sans-serif; color: #1e293b; padding: 20px;">
            <div style="max-width: 580px; margin: 0 auto; background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden;">
                <div style="background: linear-gradient(135deg, #7c3aed 0%, #4f46e5 100%); color: white; padding: 20px; text-align: center;">
                    <h2 style="margin: 0;">PredictiX Official Notification</h2>
                </div>
                <div style="padding: 20px;">
                    <p>Hello Aroshan,</p>
                    <p>This email is successfully sent directly from your official verified email: <strong>neuromindspredictix@gmail.com</strong>!</p>
                    <div style="background: #f1f5f9; border-left: 4px solid #10b981; padding: 12px; margin: 15px 0;">
                        <strong>Sender:</strong> neuromindspredictix@gmail.com<br>
                        <strong>Status:</strong> Verified &amp; Active on Brevo<br>
                        <strong>Recipient:</strong> aroshnimantha386@gmail.com
                    </div>
                    <p>All future ticket alerts, updates, and FAQs will now arrive with <strong>neuromindspredictix@gmail.com</strong> as the sender.</p>
                </div>
            </div>
        </body>
        </html>
        """
    },
    timeout=15,
)

print("Brevo API Response:", resp.status_code, resp.json())
