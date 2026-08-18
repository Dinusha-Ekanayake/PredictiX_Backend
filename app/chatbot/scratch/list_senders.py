import os
import requests
from dotenv import load_dotenv
load_dotenv()

api_key = os.getenv("BREVO_API_KEY")
resp = requests.get(
    "https://api.brevo.com/v3/senders",
    headers={"api-key": api_key, "accept": "application/json"}
)
print("Brevo Senders:", resp.status_code, resp.json())
