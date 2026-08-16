from groq import Groq

key1 = "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"
key2 = "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"

for name, k in [("CHATBOT_GROQ_API_KEY", key1), ("WH_GROQ_API_KEY", key2)]:
    try:
        client = Groq(api_key=k)
        res = client.chat.completions.create(
            messages=[{"role": "user", "content": "hello"}],
            model="llama-3.3-70b-versatile",
            max_tokens=10
        )
        print(f"SUCCESS {name}: {res.choices[0].message.content.strip()}")
    except Exception as e:
        print(f"FAILED {name}: {e}")
