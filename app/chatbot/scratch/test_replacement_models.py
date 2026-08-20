import os
from dotenv import load_dotenv
load_dotenv()

from groq import Groq

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

test_models = [
    "openai/gpt-oss-120b",
    "qwen/qwen3.6-27b",
    "openai/gpt-oss-20b",
]

for m in test_models:
    try:
        res = client.chat.completions.create(
            messages=[{"role": "user", "content": "Respond with 'Model OK' and nothing else."}],
            model=m,
            max_tokens=10
        )
        print(f"SUCCESS: {m} -> {res.choices[0].message.content.strip()}")
    except Exception as e:
        print(f"FAILED {m}: {e}")
