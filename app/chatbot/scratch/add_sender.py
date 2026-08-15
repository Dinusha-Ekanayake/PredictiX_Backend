import os
import requests
from dotenv import load_dotenv
load_dotenv()

api_key = os.getenv("BREVO_API_KEY")
print("Adding neuromindspredictix@gmail.com to Brevo senders...")

resp = requests.post(
    "https://api.brevo.com/v3/senders",
    headers={
        "api-key": api_key,
        "Content-Type": "application/json",
        "accept": "application/json",
    },
    json={
        "name": "PredictiX System",
        "email": "neuromindspredictix@gmail.com"
    }
)
print("Create Sender Response:", resp.status_code, resp.text)
