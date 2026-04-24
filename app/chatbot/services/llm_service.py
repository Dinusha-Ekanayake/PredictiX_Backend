import requests
import os
from dotenv import load_dotenv

load_dotenv()

HF_TOKEN = os.getenv("HF_TOKEN")

# Best free model for your project
MODEL_URL = "https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.1"

headers = {
    "Authorization": f"Bearer {HF_TOKEN}"
}

def ask_llm(context: str, question: str) -> str:
    prompt = f"""You are an intelligent assistant for a Smart Asset Management System.
Use the context below to answer the question clearly and helpfully.

Context:
{context}

Question: {question}

Answer:"""

    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": 300,
            "temperature": 0.7,
            "return_full_text": False
        }
    }

    try:
        response = requests.post(MODEL_URL, headers=headers, json=payload, timeout=30)
        result = response.json()

        # Handle response
        if isinstance(result, list):
            return result[0].get("generated_text", "No answer generated.")
        elif "error" in result:
            return f"Model error: {result['error']}"
        else:
            return "Could not generate answer."

    except Exception as e:
        return f"Error: {str(e)}"