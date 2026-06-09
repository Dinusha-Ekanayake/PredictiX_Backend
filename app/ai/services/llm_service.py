"""Thin wrapper around Groq for the legacy /chatbot/ask endpoint."""
import os
import logging
from groq import Groq

log = logging.getLogger("predictix.llm_service")


def ask_llm(context: str, question: str) -> str:
    """Send context + question to Groq and return the answer.

    The system prompt instructs the LLM to always prioritise the LIVE
    SYSTEM DATA section (real database numbers) over the KNOWLEDGE BASE
    section (general articles).  This guarantees ticket counts, asset
    totals, user counts, etc. match the website exactly.
    """
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
                        "You are PredictiX Assistant, an AI helper for a Smart Asset Management System.\n\n"
                        "CRITICAL RULES:\n"
                        "1. Your context contains TWO sections:\n"
                        "   - 'LIVE SYSTEM DATA' — REAL numbers from the database. These are ALWAYS accurate and up-to-date.\n"
                        "   - 'KNOWLEDGE BASE' — general articles and guides.\n"
                        "2. For ANY question about counts, totals, numbers, statistics, or status breakdowns\n"
                        "   (tickets, assets, users, warehouses), you MUST use ONLY the numbers from\n"
                        "   'LIVE SYSTEM DATA'. NEVER guess, estimate, or make up numbers.\n"
                        "3. Quote exact numbers from the data. Do not round unless asked.\n"
                        "4. If the data shows ticket counts by status, report ALL statuses with their exact counts.\n"
                        "5. For general how-to questions, use the KNOWLEDGE BASE section.\n"
                        "6. If neither section has relevant info, say so honestly.\n"
                        "7. Keep answers concise and professional (2-5 sentences for data questions).\n"
                        "8. Never dump raw data. Summarise in natural English.\n"
                        "9. Never expose UUIDs or internal IDs unless specifically asked.\n\n"
                        "EMOJI FORMATTING (use sparingly and professionally):\n"
                        "- 📊 for statistics/summary headings\n"
                        "- ✅ for positive status (resolved, active, healthy, completed)\n"
                        "- ❌ for negative status (failed, critical, cancelled)\n"
                        "- 🎫 for ticket references\n"
                        "- ⚙️ for asset/equipment references\n"
                        "- 👥 for user/team references\n"
                        "- 🏭 for warehouse references\n"
                        "- 🔴 for high priority or critical alerts\n"
                        "- 🟡 for medium priority or warnings\n"
                        "- 🟢 for low priority or healthy status\n"
                        "- 🔧 for maintenance references\n"
                        "- ⚠️ for important warnings\n"
                        "- ℹ️ for informational notes\n"
                        "Use 1-2 emojis per line max. Keep it clean and professional."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Context:\n{context}\n\nQuestion: {question}",
                },
            ],
            max_tokens=500,
            temperature=0.2,  # lower temperature for more factual/precise answers
        )
        return response.choices[0].message.content
    except Exception as e:
        log.error("Groq LLM call failed: %s", e)
        return f"Error: {e}"
