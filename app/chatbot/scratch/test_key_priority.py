import os
from dotenv import load_dotenv
load_dotenv()

from app.ai.services.llm_service import _get_api_keys, call_groq

keys = _get_api_keys()
wh_key = os.getenv("WH_GROQ_API_KEY")
chatbot_key = os.getenv("CHATBOT_GROQ_API_KEY")

print("Keys retrieved count:", len(keys))
if keys:
    print("Key #1 matches WH_GROQ_API_KEY:", keys[0] == wh_key)
if len(keys) > 1:
    print("Key #2 matches CHATBOT_GROQ_API_KEY:", keys[1] == chatbot_key)

print("\nTesting call_groq...")
res, _ = call_groq(
    messages=[{"role": "user", "content": "Respond with 'Key test OK'."}],
    max_tokens=20
)
print("call_groq Response:", res)
