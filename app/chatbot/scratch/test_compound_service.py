import os
from dotenv import load_dotenv
load_dotenv()

from app.ai.services.llm_service import call_groq, MODEL_COMPOUND, MODEL_COMPOUND_MINI

print("=== TESTING MODEL_COMPOUND_MINI ===")
try:
    res, fb = call_groq(
        messages=[{"role": "user", "content": "Respond with 'Compound Mini is active!'"}],
        model=MODEL_COMPOUND_MINI,
        max_tokens=20
    )
    print("RESULT:", res)
except Exception as e:
    print("FAILED:", e)

print("\n=== TESTING MODEL_COMPOUND ===")
try:
    res, fb = call_groq(
        messages=[{"role": "user", "content": "Respond with 'Compound Heavy is active!'"}],
        model=MODEL_COMPOUND,
        max_tokens=20
    )
    print("RESULT:", res)
except Exception as e:
    print("FAILED:", e)
