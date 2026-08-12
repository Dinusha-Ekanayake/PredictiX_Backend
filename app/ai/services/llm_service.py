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
MODEL_CASCADE = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
]

# The model every caller starts from unless it asks for a specific one. Callers
# used to hardcode "llama-3.1-8b-instant" individually, which meant each one
# spent a 403 before the cascade rescued it — and each was a separate place to
# edit when Groq retired a model. Pointing them at the head of the cascade keeps
# that decision in exactly one place.
DEFAULT_MODEL = MODEL_CASCADE[0]


def _client() -> Groq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not configured")
    return Groq(api_key=api_key)


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
    """Call Groq with automatic retry and model cascade on block/rate-limit.

    Returns:
        (result, fallback_msg): 
          - result: str if no tools, dict if tools used.
          - fallback_msg: empty string if successful on first try, or a friendly message if fallback occurred.
    """
    client = _client()
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
    # Models already attempted, so the cascade never retries a known-bad one.
    # This used to be positional — it took the caller's model's index in
    # MODEL_CASCADE and only considered entries after it — which silently
    # disabled fallback whenever a caller started from a model near the end of
    # the list (or one not in it at all, where index() raised and the -1 meant
    # "start from the top" and could re-try the failing model forever).
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

            if is_rate_limit or is_model_blocked:
                next_model = next((m for m in MODEL_CASCADE if m not in tried), None)
                if next_model:
                    log.warning(
                        "Model %s blocked/rate-limited. Falling back to %s.",
                        current_model, next_model,
                    )
                    current_model = next_model
                    tried.add(next_model)
                    kwargs["model"] = current_model
                    fallback_message = "💡 Switching to backup model for best results."
                    # Switching models is not a retry of the same failing call,
                    # so it must not consume the retry budget — otherwise a
                    # cascade longer than `retries` would never be walked.
                    continue

            attempt += 1
            if attempt <= retries:
                backoff = 1.5 ** (attempt - 1)
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
