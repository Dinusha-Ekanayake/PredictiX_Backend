import os
import requests
from dotenv import load_dotenv
load_dotenv()

api_key = os.getenv("BREVO_API_KEY")
print("Querying Brevo Transactional Logs via API...")

# Check Brevo account / sender info
resp = requests.get(
    "https://api.brevo.com/v3/senders",
    headers={"api-key": api_key, "accept": "application/json"}
)
print("Brevo Verified Senders:", resp.status_code, resp.json() if resp.status_code == 200 else resp.text)

# Check recent transactional logs
logs_resp = requests.get(
    "https://api.brevo.com/v3/smtp/emails?limit=10&sort=desc",
    headers={"api-key": api_key, "accept": "application/json"}
)
print("\nRecent Brevo Transactional Emails:", logs_resp.status_code)
if logs_resp.status_code == 200:
    for item in logs_resp.json().get("transactionalEmails", []):
        print(f"- Date: {item.get('date')} | To: {item.get('email')} | Subject: {item.get('subject')} | Status: {item.get('status') or item.get('uuid')}")
else:
    print("Logs response:", logs_resp.text)
