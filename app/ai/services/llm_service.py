"""Groq LLM service with two-model support and automatic fallback.

Models used:
  PRIMARY   = llama-3.3-70b-versatile   (used only for SQL generation)
  FAST      = llama-3.1-8b-instant       (router, table selector, summarizer)
  FALLBACK  = llama-3.3-70b-versatile   (if 8b-instant is unavailable)
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

from groq import Groq

log = logging.getLogger("predictix.llm")

# Groq models in the order they are attempted. The first entry must be one the
# deployed GROQ_API_KEY can actually call: a dead or forbidden model at the head
# of this list costs a failed HTTP round-trip on *every* LLM request before the
# cascade recovers, which is why the previous order was worth fixing.
#
# Probed against the live API 2026-08-12 with the deployed key:
#   llama-3.3-70b-versatile   OK
#   llama-3.1-8b-instant      403 — listed in models.list() but not permitted
#                                   for this key's tier
#   llama3-8b-8192            400 — decommissioned
#   llama-3.1-70b-versatile   400 — decommissioned
#
# The 403 is a key/tier property, not a property of the model, so 8b-instant is
# kept as a fallback: a key with broader access would use it, and on this key it
# is simply never reached. Re-probe before trusting these notes — the point of
# the cascade is that Groq retires models faster than this file gets edited.
MODEL_COMPOUND = "groq/compound"
MODEL_COMPOUND_MINI = "groq/compound-mini"

FAST_MODELS = [
    "groq/compound-mini",
    "groq/compound",
    "llama-3.3-70b-versatile",
    "qwen/qwen3.6-27b",
]

HEAVY_MODELS = [
    "groq/compound",
    "groq/compound-mini",
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-120b",
]

MODEL_CASCADE = [
    "groq/compound-mini",
    "groq/compound",
    "llama-3.3-70b-versatile",
    "qwen/qwen3.6-27b",
    "openai/gpt-oss-120b",
]

DEFAULT_MODEL = MODEL_COMPOUND_MINI


def _get_api_keys() -> list[str]:
    """Retrieve all configured Groq API keys in priority order."""
    keys: list[str] = []
    for var in ["CHATBOT_GROQ_API_KEY", "WH_GROQ_API_KEY", "GROQ_API_KEY"]:
        val = os.getenv(var)
        if val and val.strip() and val.strip() not in keys:
            keys.append(val.strip())
    return keys


_ACTIVE_KEY_INDEX = 0


def _get_client(key_index: Optional[int] = None) -> tuple[Groq, int]:
    """Returns a Groq client for the given or currently active API key index."""
    global _ACTIVE_KEY_INDEX
    keys = _get_api_keys()
    if not keys:
        raise RuntimeError("No Groq API keys configured in environment")
    idx = (key_index if key_index is not None else _ACTIVE_KEY_INDEX) % len(keys)
    return Groq(api_key=keys[idx]), idx


def call_groq(
    *,
    messages: list[dict],
    model: str = DEFAULT_MODEL,
    max_tokens: int = 512,
    temperature: float = 0.3,
    retries: int = 2,
    tools: Optional[list] = None,
    tool_choice: Optional[str] = None,
) -> tuple[str | dict, str]:
    """Call Groq with automatic multi-key failover, model cascade, and retry.

    Returns:
        (result, fallback_msg): 
          - result: str if no tools, dict if tools used.
          - fallback_msg: empty string if successful on first try, or a friendly message if fallback occurred.
    """
    global _ACTIVE_KEY_INDEX
    keys = _get_api_keys()
    current_key_idx = _ACTIVE_KEY_INDEX
    client, current_key_idx = _get_client(current_key_idx)

    kwargs: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if tools:
        kwargs["tools"] = tools
    if tool_choice:
        kwargs["tool_choice"] = tool_choice

    last_err: Exception | None = None
    fallback_message = ""
    current_model = model
    tried: set[str] = {model}
    attempt = 0

    while attempt <= retries:
        try:
            resp = client.chat.completions.create(**kwargs)
            msg = resp.choices[0].message
            if tools:
                return (msg, fallback_message)  # type: ignore[return-value]
            return (msg.content or "", fallback_message)
        except Exception as e:
            last_err = e
            err_str = str(e).lower()
            is_rate_limit = "429" in err_str or "rate_limit" in err_str
            is_model_blocked = (
                "403" in err_str
                or "blocked" in err_str
                or "not allowed" in err_str
                or "permission" in err_str
                or "decommissioned" in err_str
                or "no longer supported" in err_str
                or "model_decommissioned" in err_str
                or ("model" in err_str and "not found" in err_str)
            )

            # 1. Multi-key failover: switch to backup Groq key on rate limit (429)
            if is_rate_limit and len(keys) > 1:
                current_key_idx = (current_key_idx + 1) % len(keys)
                _ACTIVE_KEY_INDEX = current_key_idx
                log.warning(
                    "Groq API key rate-limited (429). Seamlessly switching to backup Groq key (%d/%d)...",
                    current_key_idx + 1,
                    len(keys),
                )
                client, _ = _get_client(current_key_idx)
                continue

            # 2. Model cascade on block/decommission
            if is_model_blocked:
                pool = HEAVY_MODELS if current_model in HEAVY_MODELS else FAST_MODELS
                next_model = next((m for m in pool if m not in tried), None)
                if not next_model:
                    next_model = next((m for m in MODEL_CASCADE if m not in tried), None)
                if next_model:
                    log.warning(
                        "Model %s blocked. Falling back to %s.",
                        current_model, next_model,
                    )
                    current_model = next_model
                    tried.add(next_model)
                    kwargs["model"] = current_model
                    fallback_message = ""
                    continue

            attempt += 1
            if attempt <= retries:
                backoff = 2.0 * attempt
                log.warning(
                    "Groq call failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt, retries, backoff, str(e)[:120],
                )
                time.sleep(backoff)

    raise RuntimeError(f"Groq call failed after {retries + 1} attempts: {last_err}")


def ask_llm(context: str, question: str) -> str:
    """Legacy RAG LLM call – kept for backwards compatibility with /chatbot/ask."""
    try:
        res, msg = call_groq(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an intelligent assistant for PredictiX, a Smart Asset Management System. "
                        "Use the provided context to answer clearly and helpfully. "
                        "Do NOT include general fleet statistics, counts of critical assets, or predicted failures (e.g. '205 assets at critical risk', '125 predicted to fail') unless the user's question explicitly asks for numbers, counts, or statistics. "
                        "Use professional emojis strategically to format your response (e.g., 📊 for stats, 🎫 for tickets, ⚙️ for assets, 👥 for users, 💡 for suggestions, ⚠️ for alerts). "
                        "If the context is not enough, say so honestly. "
                        "Keep answers concise and professional."
                    ),
                },
                {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
            ],
            model=DEFAULT_MODEL,
            max_tokens=500,
            temperature=0.5,
        )
        return msg + str(res)
    except Exception as e:
        return f"I'm having trouble connecting to the AI service right now. Please try again shortly. ({e})"
