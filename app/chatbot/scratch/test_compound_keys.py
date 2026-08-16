from groq import Groq

key1 = "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"
key2 = "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"

for name, k in [("CHATBOT_GROQ_API_KEY", key1), ("WH_GROQ_API_KEY", key2)]:
    client = Groq(api_key=k)
    for model in ["groq/compound-mini", "groq/compound"]:
        try:
            res = client.chat.completions.create(
                messages=[{"role": "user", "content": "hi"}],
                model=model,
                max_tokens=10
            )
            print(f"SUCCESS {name} [{model}]: {res.choices[0].message.content.strip()}")
        except Exception as e:
            print(f"FAILED {name} [{model}]: {e}")
