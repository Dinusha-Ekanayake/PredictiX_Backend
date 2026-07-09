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

    try:
        if intent == INTENT_GREETING:
            result = handle_greeting(ctx)
            tool_trace.append({"name": "handle_greeting", "args": {}, "result_preview": "Instant greeting returned."})

        elif intent == INTENT_WHOAMI:
            result = handle_whoami(ctx)
            tool_trace.append({"name": "handle_whoami", "args": {}, "result_preview": "Profile data returned."})

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
