import os
from pathlib import Path
from dotenv import load_dotenv
from groq import Groq

# Load .env from project root
load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=True)


def ask_llm(context: str, question: str) -> str:
    groq_api_key = os.getenv("GROQ_API_KEY")
    if not groq_api_key:
        return "Error: GROQ_API_KEY is not configured"

    try:
        client = Groq(api_key=groq_api_key)

        system_prompt = """You are an intelligent assistant for PredictiX,
a Smart Asset Management System.
Use the provided context to answer clearly and helpfully.
If the context is not enough, say so honestly.
Keep answers concise and professional."""

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"}
            ],
            max_tokens=500,
            temperature=0.7
        )

        return response.choices[0].message.content

    except Exception as e:
        return f"Error: {str(e)}"
