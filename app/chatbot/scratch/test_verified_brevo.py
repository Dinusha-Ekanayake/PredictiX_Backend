import os
import requests
from dotenv import load_dotenv
load_dotenv()

api_key = os.getenv("BREVO_API_KEY")
to_test = "aroshnimantha386@gmail.com"

print("Sending with verified sender: sharadaabeywickrama@gmail.com...")
resp = requests.post(
    "https://api.brevo.com/v3/smtp/email",
    headers={
        "api-key": api_key,
        "Content-Type": "application/json",
        "accept": "application/json",
    },
    json={
        "sender": {"email": "sharadaabeywickrama@gmail.com", "name": "PredictiX System"},
        "to": [{"email": to_test}],
        "subject": "PredictiX Alert: Verified Sender Test to Aroshan",
        "htmlContent": "<h3>PredictiX Verified Brevo Delivery</h3><p>This email is sent using the verified sender account registered on Brevo.</p>",
    },
    timeout=15,
)
print("Brevo Send Response:", resp.status_code, resp.json())

# Query logs for aroshnimantha386@gmail.com
logs_resp = requests.get(
    f"https://api.brevo.com/v3/smtp/emails?email={to_test}&limit=5&sort=desc",
    headers={"api-key": api_key, "accept": "application/json"}
)
print("\nBrevo Logs for", to_test, ":", logs_resp.status_code, logs_resp.json())
