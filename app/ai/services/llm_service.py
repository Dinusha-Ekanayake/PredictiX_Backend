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

# Fast models prioritized by speed/availability. The primary heavy model is always at the end.
MODEL_CASCADE = [
    "llama-3.1-8b-instant",
    "gemma2-9b-it",
    "mixtral-8x7b-32768",
    "llama-3.3-70b-versatile"
]


def _client() -> Groq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not configured")
    return Groq(api_key=api_key)


def call_groq(
    *,
    messages: list[dict],
    model: str = "llama-3.1-8b-instant",
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
    
    for attempt in range(retries + 1):
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
            is_model_blocked = "model" in err_str and ("not allowed" in err_str or "not found" in err_str or "blocked" in err_str or "permission" in err_str)

            if is_rate_limit or is_model_blocked:
                try:
                    next_idx = MODEL_CASCADE.index(current_model) + 1
                    if next_idx < len(MODEL_CASCADE):
                        next_model = MODEL_CASCADE[next_idx]
                        log.warning("Model %s blocked/rate-limited (%s). Falling back to %s.", current_model, str(e)[:80], next_model)
                        current_model = next_model
                        kwargs["model"] = current_model
                        fallback_message = f"💡 *The primary AI is temporarily blocked or rate-limited. I'm using the `{current_model}` backup model instead!*\n\n"
                        continue
                except ValueError:
                    pass # model not in cascade list, just let normal retry handle it

            if attempt < retries:
                backoff = 1.5 ** attempt
                log.warning("Groq call failed (attempt %d/%d), retrying in %.1fs: %s", attempt + 1, retries, backoff, str(e)[:120])
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
            model="llama-3.1-8b-instant",
            max_tokens=500,
            temperature=0.5,
        )
        return msg + str(res)
    except Exception as e:
        return f"I'm having trouble connecting to the AI service right now. Please try again shortly. ({e})"
