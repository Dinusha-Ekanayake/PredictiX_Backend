import os
from dotenv import load_dotenv
load_dotenv()

from groq import Groq

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
models = client.models.list()
print("=== AVAILABLE GROQ MODELS ===")
for m in models.data:
    if m.active:
        print(f"ID: {m.id} | Owned By: {m.owned_by}")
