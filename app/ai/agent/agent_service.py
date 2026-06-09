"""Agent loop: feeds tools to Groq, executes the tool calls it picks,
streams the results back, and returns the final assistant reply."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections import OrderedDict
from typing import Any, Optional

from groq import Groq

from .tools import TOOL_HANDLERS, TOOL_SCHEMAS, ToolContext, execute_tool
from app.core.toon import to_toon

log = logging.getLogger("predictix.agent")

DEFAULT_MODEL = "llama-3.3-70b-versatile"
MAX_TOOL_ITERATIONS = 6  # cap the loop so a confused model can't spin forever

# ── Response cache ────────────────────────────────────────────────────────────
# Small in-memory LRU. Keyed on (user_id, question, history). Lets repeat
# questions (very common during a session) return instantly instead of
# burning another 3-6 LLM round-trips.
_CACHE_MAX = 128
_CACHE_TTL_SECONDS = 5 * 60  # responses go stale after 5 min — DB state changes
_response_cache: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()


def _cache_key(user_id: str, question: str, history: Optional[list[dict]]) -> str:
    hist_str = json.dumps(history or [], sort_keys=True, default=str)
    raw = f"{user_id}|{question.strip().lower()}|{hist_str}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> Optional[dict]:
    entry = _response_cache.get(key)
    if not entry:
        return None
    ts, payload = entry
    if time.time() - ts > _CACHE_TTL_SECONDS:
        _response_cache.pop(key, None)
        return None
    _response_cache.move_to_end(key)
    return payload


def _cache_put(key: str, payload: dict) -> None:
    _response_cache[key] = (time.time(), payload)
    _response_cache.move_to_end(key)
    while len(_response_cache) > _CACHE_MAX:
        _response_cache.popitem(last=False)


SYSTEM_PROMPT = """You are PredictiX Assistant, an AI helper for a Smart Asset Management System.

Your data comes ONLY from the tools below. The tools query the same database
that powers the website's pages — so calling the right tool guarantees your
answer matches what the user sees on screen.

═══════════════════════════════════════════════════════════════════
ABSOLUTE RULES (violating these is a critical failure):
═══════════════════════════════════════════════════════════════════
1. NEVER state a number, count, name, ID, status, or date that did not come
   from a tool call in THIS conversation turn. No guessing. No estimating.
   No "based on typical systems...". No recalling FAQ/knowledge snippets.
2. For ANY question containing "how many", "count", "total", "all",
   "list", "show me", "who", "which", "what is the status of",
   "details about" — you MUST call a tool first. Always.
3. If the relevant tool returns zero results or an error, SAY SO plainly
   ("I couldn't find any matching records" / "I don't have access to that").
   Do not fill the gap with invented data.
4. Never mention specific ticket titles, asset codes, or person names
   unless they appeared verbatim in a tool result this turn.
5. If you are uncertain which tool to use, call dashboard_stats or
   count_tickets with no filters — it's better to make an extra tool call
   than to guess.

═══════════════════════════════════════════════════════════════════
TOOL SELECTION (pick the FIRST match):
═══════════════════════════════════════════════════════════════════
- "how many tickets" / "total tickets" / "all tickets" / "ticket count"
  → count_tickets  (add group_by="status"/"priority"/"category" if asked)
- "tickets per/by category" / "tickets per status"
  → count_tickets with group_by
- "how many assets" / "total assets"          → count_assets
- "how many users" / "total users" / "user count" → count_users
- "dashboard" / "overview" / "system stats" / "summary"
  → dashboard_stats  (returns the EXACT numbers shown on the Admin Dashboard
                      page — KPIs, open tickets, fleet health, etc.)
- "who is <name>" / "details about <name>" / "find user <X>"
  → find_user → then get_user_details for the matching id
- "warehouse <name> stats" / "warehouse details"
  → warehouse_summary
- "who created ticket X" / "history of ticket X" / "ticket X status changes"
  → get_ticket_history
- "list tickets" / "show me tickets" / "my tickets" / specific ticket
  → list_tickets or get_ticket
- "list assets" / "show me assets" / specific asset
  → list_assets or get_asset
- "how do I..." / "what is..." (general how-to)
  → list_faqs, then search_knowledge if nothing matches

═══════════════════════════════════════════════════════════════════
RESPONSE FORMAT:
═══════════════════════════════════════════════════════════════════
- After tool results, summarise in plain English (2-5 sentences).
- Quote exact numbers from the tool output. Do not round unless asked.
- Non-admin users only see their own tickets. If scope="own", say so.
- Never dump raw JSON. Never expose UUIDs unless the user asked for them.
- If a tool returned an "error" field, briefly explain and stop — don't
  retry the same tool with different made-up arguments.

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

═══════════════════════════════════════════════════════════════════
TOOL RESULT FORMAT:
═══════════════════════════════════════════════════════════════════
Tool results are provided in TOON (Token-Oriented Object Notation) format,
a compact key-value notation. Read the values directly — they are the same
numbers shown on the website. Example:
  ticket_total: 222
  by_status:
    open: 83
    in_progress: 51
Always quote the exact numbers from tool results. Never guess.
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
    cache_key = _cache_key(ctx.user_id, question, history)
    cached = _cache_get(cache_key)
    if cached:
        return cached

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
                temperature=0.1,
            )
        except Exception as e:
            log.exception("Groq call failed (iteration %d)", iteration)
            err_str = str(e).lower()
            if "rate" in err_str or "429" in err_str or "quota" in err_str or "limit" in err_str:
                friendly = (
                    "I'm a bit busy right now. Please try again in a moment."
                )
            elif "timeout" in err_str or "timed out" in err_str:
                friendly = (
                    "That took longer than expected. Please try again with a more specific question."
                )
            else:
                friendly = (
                    "I couldn't process that just now. Please try again shortly."
                )
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
            payload = {
                "answer": final_answer,
                "tool_trace": tool_trace,
                "iterations": iteration + 1,
            }
            _cache_put(cache_key, payload)
            return payload

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
                log.info("Executing tool '%s' with args: %s", name, args)
                result = execute_tool(name, args, ctx)
                log.info("Tool '%s' returned type=%s", name, type(result).__name__)

            result_toon = to_toon(result)
            preview = result_toon if len(result_toon) <= 240 else result_toon[:240] + "…"

            tool_trace.append({
                "name": name,
                "args": args,
                "result_preview": preview,
            })

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": name,
                "content": result_toon[:8000],  # cap to keep tokens reasonable
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
