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
from .actions.insert_actions import handle_action
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
INTENT_ACTION      = "ACTION"

ALL_INTENTS = [INTENT_GREETING, INTENT_WHOAMI, INTENT_NAVIGATION, INTENT_FAQ, INTENT_KNOWLEDGE, INTENT_DATABASE, INTENT_PREDICTION, INTENT_ACTION]

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
    "7. DATABASE: ANY question about actual data, tickets, users, assets, or status counts (e.g. 'how many tickets', 'show my assets')\n"
    "8. ACTION: ANY command to create, insert, or add data (e.g. 'create a ticket', 'add a new user', 'insert an asset'). Do NOT include updates or deletes.\n\n"
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

    # Fast-path: navigation phrases — "open X", "go to X", "take me to X", "navigate to X"
    NAV_TRIGGERS = (
        "open ", "go to ", "take me to ", "navigate to ", "show me the ",
        "bring me to ", "launch ", "redirect to ", "i want to go to ",
        "switch to ", "jump to ",
    )
    NAV_SUBJECTS = (
        "asset", "ticket", "dashboard", "report", "warehouse", "user",
        "profile", "setting", "helpdesk", "help desk", "notification",
        "prediction", "cost", "fleet", "home", "overview",
    )
    if any(q.startswith(t) for t in NAV_TRIGGERS) and any(s in q for s in NAV_SUBJECTS):
        return INTENT_NAVIGATION

    # Fast-path: Actions (create, add, insert, update, delete, edit)
    ACTION_TRIGGERS = ("create ", "add ", "insert ", "make a new ", "generate a ticket", "update ", "delete ", "edit ", "remove ", "change ")
    if any(q.startswith(t) for t in ACTION_TRIGGERS):
        return INTENT_ACTION

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
        raw_result, _ = call_groq(
            messages=[
                {"role": "system", "content": ROUTER_SYSTEM},
                {"role": "user", "content": question},
            ],
            max_tokens=20,
            temperature=0.0,
        )
        intent = str(raw_result).strip().upper().split()[0] if raw_result else INTENT_DATABASE
        if intent not in ALL_INTENTS:
            log.warning("Router returned unknown intent '%s', defaulting to DATABASE", intent)
            return INTENT_DATABASE
        return intent
    except Exception as e:
        log.error("Router failed: %s", e)
        return INTENT_DATABASE

def _rewrite_query_with_history(question: str, history: list[dict]) -> str:
    """Uses LLM to rewrite ambiguous follow-up questions into standalone contextual queries."""
    if not history:
        return question

    q_lower = question.strip().lower()
    # If the question is obviously a standalone request (e.g. asking for counts, general queries, overview), do NOT rewrite
    standalone_triggers = [
        "how many", "how much", "which is", "what is the most", "show all", "list all",
        "who is", "who are", "total", "count of", "number of", "give number"
    ]
    if any(q_lower.startswith(t) for t in standalone_triggers):
        return question

    # Take the last 3 turns to provide context without overloading tokens
    recent_history = history[-3:]
    history_text = ""
    for turn in recent_history:
        role = turn.get("role", "unknown")
        content = turn.get("content", "")
        if len(content) > 300:
            content = content[:300] + "...[truncated]"
        history_text += f"{role}: {content}\n"

    prompt = (
        "You are a query rewriting assistant for the PredictiX Smart Asset Management System.\n"
        "Given the conversation history, rewrite the user's latest query into a standalone, fully-contextualized query ONLY if the user uses an explicit reference/pronoun (e.g. 'it', 'this one', 'the first ticket', 'its status', 'show details of that asset').\n\n"
        "STRICT RULES:\n"
        "1. If the user query is asking about a general system entity (e.g. 'how many tickets here', 'which is the most critical asset', 'show users', 'how many assets'), DO NOT mix or blend it with previous topics (like profile pictures, avatars, or passwords). Return the query EXACTLY as is.\n"
        "2. 'here' or 'in the system' refers to the user's current warehouse/system, NOT the previous conversational topic.\n"
        "3. If in doubt, return the original query unchanged.\n"
        "4. Return ONLY the rewritten query with no explanations.\n\n"
        f"History:\n{history_text}\n"
        f"User Latest Query: {question}"
    )

    try:
        rewritten, _ = call_groq(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=50,
            temperature=0.0
        )
        return str(rewritten).strip() if rewritten else question
    except Exception as e:
        log.error("Query rewriting failed: %s", e)
        return question


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

    # Conversational Memory (Query Rewriting)
    if history and len(history) > 0:
        original_q = question
        question = _rewrite_query_with_history(question, history)
        if question != original_q:
            log.info("Rewrote query: '%s' -> '%s'", original_q, question)

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

        elif intent == INTENT_ACTION:
            result = handle_action(question, ctx)
            tool_trace.append({"name": "handle_action", "args": {"question": question}, "result_preview": "Action processed."})

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
