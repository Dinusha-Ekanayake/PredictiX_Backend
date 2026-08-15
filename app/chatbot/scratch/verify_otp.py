import os
import requests
from dotenv import load_dotenv
load_dotenv()

api_key = os.getenv("BREVO_API_KEY")
otp = "396527"
sender_id = 2

# Try verifying via API endpoints
endpoints = [
    ("POST", f"https://api.brevo.com/v3/senders/{sender_id}/verify", {"otp": otp}),
    ("POST", f"https://api.brevo.com/v3/senders/{sender_id}/verify", {"code": otp}),
    ("POST", f"https://api.brevo.com/v3/senders/verify", {"senderId": sender_id, "code": otp}),
    ("PUT", f"https://api.brevo.com/v3/senders/{sender_id}", {"otp": otp}),
]

for method, url, payload in endpoints:
    try:
        r = requests.request(method, url, headers={"api-key": api_key, "Content-Type": "application/json"}, json=payload)
        print(f"{method} {url} -> {r.status_code}: {r.text[:150]}")
    except Exception as e:
        print(f"Error {url}: {e}")

# Check current status of senders
s = requests.get("https://api.brevo.com/v3/senders", headers={"api-key": api_key})
print("\nCurrent Senders:", s.json())
