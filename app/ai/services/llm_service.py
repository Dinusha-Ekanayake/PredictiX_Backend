import os
from groq import Groq

def ask_llm(context: str, question: str) -> str:
    groq_api_key = os.getenv("GROQ_API_KEY")
    if not groq_api_key:
        return "Error: GROQ_API_KEY is not configured"

    try:
        client = Groq(api_key=groq_api_key)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an intelligent assistant for PredictiX, "
                        "a Smart Asset Management System. "
                        "Use the provided context to answer clearly and helpfully. "
                        "If the context is not enough, say so honestly. "
                        "Keep answers concise and professional."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Context:\n{context}\n\nQuestion: {question}",
                },
            ],
            max_tokens=500,
            temperature=0.7,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error: {e}"
