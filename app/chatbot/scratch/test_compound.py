import os
from dotenv import load_dotenv
load_dotenv()

from groq import Groq

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

compound_models = [
    "groq/compound-mini",
    "groq/compound",
    "meta-llama/llama-4-scout-17b-16e-instruct"
]

for m in compound_models:
    try:
        res = client.chat.completions.create(
            messages=[{"role": "user", "content": "Hello! Reply with 'Compound OK' and your model name."}],
            model=m,
            max_tokens=20
        )
        print(f"SUCCESS {m}: {res.choices[0].message.content.strip()}")
    except Exception as e:
        print(f"FAILED {m}: {e}")
