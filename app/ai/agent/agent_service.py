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

You have access to tools that read live data (tickets, assets, FAQs, knowledge base) and run ML models (failure prediction, ticket categorization, priority classification).

Guidelines:
- Call tools whenever the user's question needs real data. Don't guess.
- Prefer specific tools (list_tickets, get_asset) over generic ones (search_knowledge) when the question is concrete.
- For "how do I..." questions, try list_faqs or search_knowledge first.
- Non-admin users only see their own tickets — don't promise data you can't return.
- When you receive tool results, summarise them in plain language. Don't dump raw JSON at the user.
- If a tool returns an error, explain it briefly and suggest a next step.
- Keep replies concise (2-5 sentences) unless the user asks for detail.
- Never invent ticket IDs, asset codes, or numeric values. If you don't have data, say so.
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
            return {
                "answer": f"Sorry — the AI service returned an error: {e}",
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
        "answer": (
            "I gathered some information but couldn't finalise a response within the allowed steps. "
            "Try asking a more specific question."
        ),
        "tool_trace": tool_trace,
        "iterations": MAX_TOOL_ITERATIONS,
    }
