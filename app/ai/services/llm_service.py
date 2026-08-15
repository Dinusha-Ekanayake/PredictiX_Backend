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

# Working Groq models ordered by speed. Remove any that get decommissioned.
# Verified working as of 2026-07: llama-3.1-8b-instant may be 403'd on free tier,
# so we fall through to llama3-8b-8192 → mixtral → llama-3.3-70b-versatile.
MODEL_CASCADE = [
    "llama-3.1-8b-instant",
    "llama3-8b-8192",
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile",
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
                # Find next working model in cascade (skip any that already failed)
                try:
                    current_idx = MODEL_CASCADE.index(current_model)
                except ValueError:
                    current_idx = -1
                
                next_model = None
                for candidate in MODEL_CASCADE[current_idx + 1:]:
                    next_model = candidate
                    break

                if next_model:
                    log.warning("Model %s blocked/decommissioned. Falling back to %s.", current_model, next_model)
                    current_model = next_model
                    kwargs["model"] = current_model
                    fallback_message = ""
                    continue

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
                        "Do NOT include general fleet statistics, counts of critical assets, or predicted failures (e.g. '205 assets at critical risk', '125 predicted to fail') unless the user's question explicitly asks for numbers, counts, or statistics. "
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
