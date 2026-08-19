import os
import json
import re
from dotenv import load_dotenv
load_dotenv()

from app.ai.services.llm_service import call_groq
from app.ai.agent.actions.insert_actions import ACTION_PROMPT

query = "Create a high priority ticket for Forklift FL-04 titled 'Brake pressure loss' with description 'Operator reported low hydraulic pressure during transit."

print("Testing LLM call on query...")
raw_json, _ = call_groq(
    messages=[
        {"role": "system", "content": ACTION_PROMPT},
        {"role": "user", "content": query}
    ],
    max_tokens=200,
    temperature=0.1
)

print(f"RAW OUTPUT:\n{raw_json!r}\n")

raw_json_clean = str(raw_json).strip()
if raw_json_clean.startswith("```json"):
    raw_json_clean = raw_json_clean[7:-3].strip()

print(f"CLEANED:\n{raw_json_clean!r}\n")

try:
    data = json.loads(raw_json_clean)
    print("Parsed data:", data)
except Exception as e:
    print("Failed to parse JSON:", e)
    # Test regex extraction
    match = re.search(r'\{.*\}', str(raw_json), re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            print("Regex extracted JSON successfully:", data)
        except Exception as e2:
            print("Regex parse failed:", e2)
