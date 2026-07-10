"""PredictiX Chatbot – V3 Token-Optimized Router Agent.

Pipeline:
  1. ROUTER (8b-instant, ~80 tokens)  → classify intent into one of 7 categories
  2. Dispatch to the matching Zero-Token handler OR heavy pipeline
  3. Return a structured response with answer + action_buttons

Token budget per request type:
  - Greeting / WhoAmI / Navigation / FAQ  →  0 tokens (no LLM call)
  - Knowledge search                       →  ~300 tokens (8b)
  - Prediction info / navigation           →  0 tokens (keyword match)
  - Database query                         →  ~80 (8b router) + ~80 (8b table select) + ~350 (70b SQL) + ~300 (8b summary) ≈ 810 tokens max
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from .tools import (
    ToolContext,
    handle_greeting,
    handle_whoami,
    handle_navigation,
    handle_faq,
    handle_knowledge,
    handle_database,
    handle_prediction_info,
)
from app.ai.services.llm_service import call_groq

log = logging.getLogger("predictix.agent")

# ─── Intent categories ────────────────────────────────────────────────────────
INTENT_GREETING    = "GREETING"
INTENT_WHOAMI      = "WHOAMI"
INTENT_NAVIGATION  = "NAVIGATION"
INTENT_FAQ         = "FAQ"
INTENT_KNOWLEDGE   = "KNOWLEDGE"
INTENT_DATABASE    = "DATABASE"
INTENT_PREDICTION  = "PREDICTION"

ALL_INTENTS = [INTENT_GREETING, INTENT_WHOAMI, INTENT_NAVIGATION, INTENT_FAQ, INTENT_KNOWLEDGE, INTENT_DATABASE, INTENT_PREDICTION]

# ─── Router prompt ─────────────────────────────────────────────────────────────
ROUTER_SYSTEM = (
    "You are PredictiX Router, an intent classifier for a Smart Asset Management System.\n"
    "Analyze the user's input and classify it exactly into ONE of these intents:\n"
    "1. GREETING: 'hello', 'hi', 'how are you', 'what can you do'\n"
    "2. WHOAMI: 'who am i', 'what is my role', 'my account'\n"
    "3. NAVIGATION: 'take me to settings', 'go to dashboard', 'open tickets'\n"
    "4. FAQ: 'how to reset password', 'how to add an asset', general help questions\n"
    "5. PREDICTION: 'how to use failure prediction', 'cost estimation', 'run prediction'\n"
    "6. KNOWLEDGE: 'how does the HVAC system work', 'what is predictive maintenance', definition questions\n"
    "7. DATABASE: ANY question about actual data, tickets, users, assets, or status counts (e.g. 'how many tickets', 'show my assets')\n\n"
    "Rules:\n"
    "- Respond with ONLY the exact intent name in all caps.\n"
    "- If unsure, default to DATABASE."
)


def _classify_intent(question: str) -> str:
    """Use the fast model to classify intent. Falls back to DATABASE on any error."""
    # Pre-checks to avoid LLM calls for obvious cases (saves even more tokens)
    q = question.strip().lower()

    # Instant keyword pre-filter (catches 80%+ of simple queries)
    if q in {"hi", "hello", "hey", "menu", "help", "start", "yo", "good morning", "good evening", "good afternoon"}:
        return INTENT_GREETING
    if any(q.startswith(k) for k in ("who am i", "what is my", "my role", "my profile", "my name", "my department")):
        return INTENT_WHOAMI
    if q.startswith("faq") or "frequently asked" in q:
        return INTENT_FAQ

<<<<<<< HEAD
Guidelines:
- Call tools whenever the user's question needs real data. Don't guess.
- If the user asks about system navigation (e.g., "how to go to helpdesk", "how to change password", "where are reports"), ALWAYS call the `mr_guideline_helper` tool to get the proper instructions.

═══════════════════════════════════════════════════════════════════
RESPONSE FORMAT & CONVERSATIONAL RULES:
═══════════════════════════════════════════════════════════════════
- After tool results, summarise in plain English (2-5 sentences).
- If you used `mr_guideline_helper`, pass the guideline exactly as provided and ALWAYS end with: "Please visit the Helpdesk section for more details. If you need further support, contact the admin at neuromindspredictix@gmail.com."
- Quote exact numbers from the tool output. Do not round unless asked.
- Non-admin users only see their own tickets. If scope="own", say so.
- Never dump raw JSON. Never expose UUIDs unless the user asked for them.
- If a tool returned an "error" field, briefly explain and stop.
- If you cannot comprehend the user's intent or receive an unrecognized command, respond with: "I'm still learning and didn't quite catch that! Could you rephrase your question, or try typing 'menu' to see all the ways I can help?"
- If you have too much text or too many options to present, do not dump it all at once. Instead, break it down and ask: "That was a lot of info at once! Let's break this down. Do you want to try [Option A] or [Option B] first?"

═══════════════════════════════════════════════════════════════════
EMOJI FORMATTING (use sparingly and professionally):
═══════════════════════════════════════════════════════════════════
- 📊 for statistics/summary headings
- ✅ for positive status (resolved, active, healthy, completed)
- ❌ for negative status (failed, critical, cancelled)
- 🎫 for ticket references
- ⚙️ for asset/equipment references
- 👥 for user/team references
- 🏭 for warehouse references
- 🔴 for high priority or critical alerts
- 🟡 for medium priority or warnings
- 🟢 for low priority or healthy status
- 🔧 for maintenance references
- ⚠️ for important warnings
- ℹ️ for informational notes
Use 1-2 emojis per line max. Keep it clean and professional.
"""


import re

def _parse_failed_tool_call(error_body: str) -> tuple[str | None, dict | None]:
    match = re.search(r'<function=(\w+)>(.*?)</function>', error_body, re.DOTALL)
    if not match:
        return None, None
    name = match.group(1)
    try:
        args = json.loads(match.group(2))
    except json.JSONDecodeError:
        args = {}
    return name, args

def _get_groq_client() -> Groq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not configured")
    return Groq(api_key=api_key)
=======
    # Fast-path: "how to X" / "guide me" / "help me" / "how do i" → always FAQ
    FAQ_TRIGGERS = (
        "how to ", "how do i ", "guide me", "guide me to", "help me ",
        "what is the", "how can i ", "how should i ", "steps to ",
        "where is ", "where can i find", "how does ", "what are the steps",
        "is it possible to", "can i ", "how to navigate", "i want to know how",
    )
    if any(q.startswith(t) for t in FAQ_TRIGGERS):
        return INTENT_FAQ


    # LLM router call
    try:
        result = call_groq(
            messages=[
                {"role": "system", "content": ROUTER_SYSTEM},
                {"role": "user", "content": question},
            ],
            model="llama-3.1-8b-instant",
            max_tokens=20,
            temperature=0.0,
        )
        intent = str(result).strip().upper().split()[0] if result else INTENT_DATABASE
        if intent not in ALL_INTENTS:
            log.warning("Router returned unknown intent '%s', defaulting to DATABASE", intent)
            return INTENT_DATABASE
        return intent
    except Exception as e:
        log.error("Router failed: %s", e)
        return INTENT_DATABASE
>>>>>>> 35e3ac103591052fc88dd59200e314bb3792f95b

def get_sql_from_subagent(instruction: str, schema_str: str, model: str = DEFAULT_MODEL) -> str:
    """Uses Groq to generate a raw PostgreSQL query based on the instruction and provided schema."""
    client = _get_groq_client()
    system_prompt = f"""You are an expert PostgreSQL developer. 
Your ONLY job is to write a raw, valid PostgreSQL SELECT query to satisfy the user's instruction.
You MUST output ONLY the raw SQL query, with NO markdown formatting, NO backticks, and NO explanations.
If you cannot write the query, output ERROR: <reason>

Here is the exact schema for the ONLY tables you can query:
{schema_str}
"""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": instruction}
            ],
            max_tokens=300,
            temperature=0.1,
        )
        # Strip backticks if the LLM hallucinated them despite instructions
        sql = response.choices[0].message.content.strip()
        if sql.startswith("```sql"):
            sql = sql[6:]
        if sql.startswith("```"):
            sql = sql[3:]
        if sql.endswith("```"):
            sql = sql[:-3]
        return sql.strip()
    except Exception as e:
        log.exception("Subagent SQL generation failed")
        return f"ERROR: Subagent failed - {e}"



def run_agent(
    question: str,
    history: Optional[list[dict]],
    ctx: ToolContext,
) -> dict:
    """Main entry point. Route the question and return a structured response.

    Returns:
        {
            "answer": str,
            "action_buttons": [{"label": str, "path": str}],
            "tool_trace": [{"name": str, "args": dict, "result_preview": str}],
            "iterations": int,
        }
    """
    if not question.strip():
        return {
            "answer": "👋 Please type a question or say **menu** to see what I can help with!",
            "action_buttons": [],
            "tool_trace": [],
            "iterations": 0,
        }

    tool_trace: list[dict] = []
    intent = _classify_intent(question)
    log.info("Intent classified as: %s for question: %s", intent, question[:80])

<<<<<<< HEAD
    for iteration in range(MAX_TOOL_ITERATIONS):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                max_tokens=800,
                temperature=0.4,
            )
        except Exception as e:
            log.exception("Groq call failed (iteration %d)", iteration)
            err_str = str(e).lower()
            
            # Default Technical Error Message
            friendly = "Oops! My apologies, but it looks like I’m having a little trouble connecting to our systems right now. Please try again in a few minutes, or contact our support team at support@company.com."
            
            if "rate limit reached" in err_str or "rate_limit_exceeded" in err_str or "429" in err_str:
                friendly = "I've reached my daily token limit! 🛑 Please try again in a little while when the tokens reset."
            elif "timeout" in err_str or "timed out" in err_str:
                friendly = "Oops! My apologies, but the request timed out. Please try again in a few minutes."

            return {
                "answer": friendly,
                "tool_trace": tool_trace,
                "iterations": iteration,
            }
=======
    try:
        if intent == INTENT_GREETING:
            result = handle_greeting(ctx)
            tool_trace.append({"name": "handle_greeting", "args": {}, "result_preview": "Instant greeting returned."})

        elif intent == INTENT_WHOAMI:
            result = handle_whoami(ctx)
            tool_trace.append({"name": "handle_whoami", "args": {}, "result_preview": "Profile data returned."})
>>>>>>> 35e3ac103591052fc88dd59200e314bb3792f95b

        elif intent == INTENT_NAVIGATION:
            result = handle_navigation(question, ctx)
            tool_trace.append({"name": "handle_navigation", "args": {"question": question}, "result_preview": "Navigation guidance returned."})

        elif intent == INTENT_FAQ:
            result = handle_faq(question, ctx)
            tool_trace.append({"name": "handle_faq", "args": {"question": question}, "result_preview": f"Fetched FAQs from Supabase."})

        elif intent == INTENT_KNOWLEDGE:
            result = handle_knowledge(question, ctx)
            tool_trace.append({"name": "handle_knowledge", "args": {"question": question}, "result_preview": "Knowledge base searched."})

        elif intent == INTENT_PREDICTION:
            result = handle_prediction_info(question, ctx)
            tool_trace.append({"name": "handle_prediction_info", "args": {"question": question}, "result_preview": "Prediction info returned."})

        else:  # INTENT_DATABASE (default)
            result = handle_database(question, ctx)
            tool_trace.append({"name": "handle_database", "args": {"question": question}, "result_preview": "DB query executed."})

    except Exception as e:
        log.exception("Handler crashed for intent %s", intent)
        result = {
            "answer": "⚠️ Oops! I ran into an unexpected issue while processing your request. Please try again in a moment.",
            "action_buttons": [],
        }

    return {
        "answer": result.get("answer", "I'm sorry, I couldn't generate a response."),
        "action_buttons": result.get("action_buttons", []),
        "tool_trace": tool_trace,
        "iterations": 1,
    }
