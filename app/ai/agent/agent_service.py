"""Agent loop: feeds tools to Groq, executes the tool calls it picks,
streams the results back, and returns the final assistant reply."""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

from groq import Groq

from .tools import TOOL_HANDLERS, TOOL_SCHEMAS, ToolContext, execute_tool

log = logging.getLogger("predictix.agent")

DEFAULT_MODEL = "llama-3.3-70b-versatile"
MAX_TOOL_ITERATIONS = 6  # cap the loop so a confused model can't spin forever


SYSTEM_PROMPT = """You are PredictiX Assistant, an AI helper for a Smart Asset Management System.

You have access to tools that read live data (tickets, assets, FAQs, users, notifications, maintenance events, etc).

Guidelines:
- Call tools whenever the user's question needs real data. Don't guess.
- To count things accurately, look at the `total_count` field returned by the list tools, rather than just counting the items in the paginated list.
- If asked about notifications, use the `list_notifications` tool.
- If asked about users or admins, use the `list_users` tool.
- If asked about maintenance, use the `list_maintenance_events` tool.
- If asked about comments on a ticket, use `list_ticket_comments`.
- For general questions (e.g. "describe the dashboard"), answer from your knowledge of the system without calling any tools.

RESPONSE FORMAT & CONVERSATIONAL RULES:
- After tool results, summarise in plain English (2-5 sentences).
- Quote exact numbers from the tool output. Do not round unless asked.
- Non-admin users only see their own tickets (scope="own"). Admins see tickets in their warehouse (scope="warehouse"). Superadmins see all tickets (scope="all"). If scope is restricted, say so.
- Never dump raw JSON. Never expose UUIDs unless the user asked for them.
- If a tool returned an "error" field, briefly explain and stop.
- If you cannot comprehend the user's intent or receive an unrecognized command, respond with: "I'm still learning and didn't quite catch that! Could you rephrase your question, or try typing 'menu' to see all the ways I can help?"

EMOJI FORMATTING (use sparingly and professionally):
- Use relevant emojis like ticket, gear, chart, checkmark etc.
- Use 1-2 emojis per line max. Keep it clean and professional.
"""


def _get_groq_client() -> Groq:
    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not configured")
    return Groq(api_key=api_key)


def _parse_failed_tool_call(error_body: str) -> tuple[str | None, dict | None]:
    """Try to extract tool name + args from Groq's failed_generation XML format.

    Groq returns something like:
        <function=list_faqs>{"limit": 1, "search": "dashboard"}</function>
    We parse the function name and JSON args out of it.
    """
    match = re.search(r'<function=(\w+)>(.*?)</function>', error_body, re.DOTALL)
    if not match:
        return None, None
    name = match.group(1)
    try:
        args = json.loads(match.group(2))
    except json.JSONDecodeError:
        args = {}
    return name, args


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
            err_str = str(e)
            err_lower = err_str.lower()

            # ── Handle Groq's "tool_use_failed" (XML <function> tag) ──
            # Llama 3.3 sometimes emits <function=name>{args}</function>
            # instead of proper JSON tool calls. Groq rejects this with 400.
            # We catch it, parse the tool call manually, execute the tool,
            # then ask the model again (without tools) to summarise.
            if "tool_use_failed" in err_lower or "failed_generation" in err_lower:
                log.warning("Groq tool_use_failed - attempting manual parse (iteration %d)", iteration)
                tool_name, tool_args = _parse_failed_tool_call(err_str)
                tool_args = tool_args or {}
                if tool_name and tool_name in TOOL_HANDLERS:
                    # Execute the tool ourselves
                    result = execute_tool(tool_name, tool_args, ctx)
                    result_json = json.dumps(result, default=str)
                    preview = result_json if len(result_json) <= 240 else result_json[:240] + "..."
                    tool_trace.append({
                        "name": tool_name,
                        "args": tool_args,
                        "result_preview": preview,
                    })

                    # Feed the tool result back to the model WITHOUT tools
                    # so it just summarises in plain English.
                    messages.append({
                        "role": "assistant",
                        "content": f"I looked up data using the {tool_name} tool.",
                    })
                    messages.append({
                        "role": "user",
                        "content": f"Here is the tool result for {tool_name}:\n{result_json[:8000]}\n\nPlease summarise this data in a helpful answer.",
                    })

                    try:
                        followup = client.chat.completions.create(
                            model=model,
                            messages=messages,
                            max_tokens=800,
                            temperature=0.4,
                        )
                        final_answer = followup.choices[0].message.content or ""
                    except Exception:
                        log.exception("Follow-up Groq call also failed")
                        final_answer = f"I found the data but had trouble formatting it. Raw result: {preview}"

                    return {
                        "answer": final_answer,
                        "tool_trace": tool_trace,
                        "iterations": iteration + 1,
                    }

            # ── Other errors ──
            log.exception("Groq call failed (iteration %d)", iteration)

            friendly = f"Oops! I encountered an error: {err_str}"

            if "rate limit reached" in err_lower or "rate_limit_exceeded" in err_lower or "429" in err_lower:
                friendly = "I've reached my daily token limit! Please try again in a little while when the tokens reset."
            elif "timeout" in err_lower or "timed out" in err_lower:
                friendly = "Oops! My apologies, but the request timed out. Please try again in a few minutes."
            else:
                friendly = "Oops! My apologies, but it looks like I'm having a little trouble connecting to our systems right now. Please try again in a few minutes, or contact our support team at neuromindspredictix@gmail.com."

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
            preview = result_json if len(result_json) <= 240 else result_json[:240] + "..."

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
