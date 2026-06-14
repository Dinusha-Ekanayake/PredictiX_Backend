"""Agent loop: feeds tools to Groq, executes the tool calls it picks,
streams the results back, and returns the final assistant reply."""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from groq import Groq

from .tools import TOOL_HANDLERS, TOOL_SCHEMAS, ToolContext, execute_tool

log = logging.getLogger("predictix.agent")

DEFAULT_MODEL = "llama-3.3-70b-versatile"
MAX_TOOL_ITERATIONS = 6  # cap the loop so a confused model can't spin forever


SYSTEM_PROMPT = """You are PredictiX Assistant, an AI helper for a Smart Asset Management System.

You have access to tools that read live data (tickets, assets, FAQs, users, notifications, maintenance events, etc) and run ML models (failure prediction, ticket categorization, priority classification).

Guidelines:
- Call tools whenever the user's question needs real data. Don't guess.
- To count things accurately, look at the `total_count` field returned by the list tools, rather than just counting the items in the paginated list.
- If asked about notifications, use the `list_notifications` tool.
- If asked about users or admins, use the `list_users` tool.
- If asked about maintenance, use the `list_maintenance_events` tool.
- If asked about comments on a ticket, use `list_ticket_comments`.
═══════════════════════════════════════════════════════════════════
RESPONSE FORMAT & CONVERSATIONAL RULES:
═══════════════════════════════════════════════════════════════════
- After tool results, summarise in plain English (2-5 sentences).
- Quote exact numbers from the tool output. Do not round unless asked.
- Non-admin users only see their own tickets (scope="own"). Admins see tickets in their warehouse (scope="warehouse"). Superadmins see all tickets (scope="all"). If scope is restricted, say so.
- Never dump raw JSON. Never expose UUIDs unless the user asked for them.
- If a tool returned an "error" field, briefly explain and stop.
- If you cannot comprehend the user's intent or receive an unrecognized command, respond with: "I’m still learning and didn't quite catch that! Could you rephrase your question, or try typing 'menu' to see all the ways I can help?"
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


def _get_groq_client() -> Groq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not configured")
    return Groq(api_key=api_key)


def run_agent(
    question: str,
    history: Optional[list[dict]],
    ctx: ToolContext,
    model: str = DEFAULT_MODEL,
) -> dict:
    """Run the tool-calling loop and return the final assistant message + trace.

    Args:
        question: The user's latest message.
        history: Prior conversation turns ([{role, content}]). Excludes system+current question.
        ctx: Per-request tool context (db session, current user).
        model: Groq model id.

    Returns:
        {
            "answer": str,
            "tool_trace": [{"name": str, "args": dict, "result_preview": str}],
            "iterations": int,
        }
    """
    client = _get_groq_client()

    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        # Trim history to last 10 turns to keep context manageable
        for turn in history[-10:]:
            role = turn.get("role")
            content = turn.get("content")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question})

    tool_trace: list[dict] = []
    final_answer = ""

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

        msg = response.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None)

        if not tool_calls:
            # Model produced a final natural-language answer
            final_answer = msg.content or ""
            return {
                "answer": final_answer,
                "tool_trace": tool_trace,
                "iterations": iteration + 1,
            }

        # Append the assistant's tool-call message verbatim so the API
        # accepts the follow-up tool-result messages.
        messages.append(
            {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ],
            }
        )

        # Execute every tool the model requested in this turn
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            if name not in TOOL_HANDLERS:
                result: Any = {"error": f"Unknown tool '{name}'"}
            else:
                result = execute_tool(name, args, ctx)

            result_json = json.dumps(result, default=str)
            preview = result_json if len(result_json) <= 240 else result_json[:240] + "…"

            tool_trace.append({
                "name": name,
                "args": args,
                "result_preview": preview,
            })

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": name,
                "content": result_json[:8000],  # cap to keep tokens reasonable
            })

    # Hit the iteration cap without a final answer
    return {
        "answer": "It looks like I might not be the best bot for this specific request. Let me connect you with a live human support agent who can help you out.",
        "tool_trace": tool_trace,
        "iterations": MAX_TOOL_ITERATIONS,
    }
