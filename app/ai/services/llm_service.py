"""Groq LLM service with active model support and automatic fallback.

Models used:
  DEFAULT / FAST  = groq/compound-mini or groq/compound
  HEAVY / SQL     = groq/compound or openai/gpt-oss-120b
  FALLBACK        = qwen/qwen3.6-27b or openai/gpt-oss-20b
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional
from dotenv import load_dotenv

from groq import Groq

# Ensure .env is loaded
load_dotenv()

log = logging.getLogger("predictix.llm")

# Active Groq models available
MODEL_COMPOUND = "groq/compound"
MODEL_COMPOUND_MINI = "groq/compound-mini"

FAST_MODELS = [
    "groq/compound",
    "groq/compound-mini",
    "qwen/qwen3.6-27b",
    "openai/gpt-oss-120b",
]

HEAVY_MODELS = [
    "groq/compound",
    "groq/compound-mini",
    "openai/gpt-oss-120b",
    "qwen/qwen3.6-27b",
]

MODEL_CASCADE = [
    "groq/compound",
    "groq/compound-mini",
    "qwen/qwen3.6-27b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
]

DEFAULT_MODEL = MODEL_COMPOUND


def _get_api_keys() -> list[str]:
    """Retrieve all configured Groq API keys in priority order."""
    keys: list[str] = []
    for var in ["WH_GROQ_API_KEY", "GROQ_API_KEY", "CHATBOT_GROQ_API_KEY"]:
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
    retries: int = 1,
    tools: Optional[list] = None,
    tool_choice: Optional[str] = None,
) -> tuple[str | dict, str]:
    """Call Groq with automatic multi-key failover, multi-model cascade, and retry.

    Systematically rotates through all configured API keys and candidate models
    upon encountering ANY trouble (rate limits, 401/403 permission errors,
    404 model not found, timeouts, 500/503 server errors, etc.).
    """
    global _ACTIVE_KEY_INDEX
    keys = _get_api_keys()
    if not keys:
        raise RuntimeError("No Groq API keys configured in environment")

    # Build prioritized candidate model list starting with the requested model
    pool = HEAVY_MODELS if model in HEAVY_MODELS else FAST_MODELS
    candidate_models: list[str] = [model]
    for m in pool + MODEL_CASCADE:
        if m not in candidate_models:
            candidate_models.append(m)

    last_err: Exception | None = None
    fallback_message = ""

    # Try every candidate model in order
    for model_idx, current_model in enumerate(candidate_models):
        kwargs: dict = {
            "model": current_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice

        is_model_missing = False

        # For this model, try all configured API keys starting from _ACTIVE_KEY_INDEX
        for key_offset in range(len(keys)):
            current_key_idx = (_ACTIVE_KEY_INDEX + key_offset) % len(keys)
            client, _ = _get_client(current_key_idx)

            # Attempts per key/model for transient hiccups
            for attempt in range(retries + 1):
                try:
                    resp = client.chat.completions.create(**kwargs)
                    msg = resp.choices[0].message
                    # Save working key as the new active key
                    _ACTIVE_KEY_INDEX = current_key_idx
                    if model_idx > 0:
                        log.info(
                            "Groq succeeded using fallback model '%s' with key #%d/%d",
                            current_model,
                            current_key_idx + 1,
                            len(keys),
                        )
                    if tools:
                        return (msg, fallback_message)
                    return (msg.content or "", fallback_message)

                except Exception as e:
                    last_err = e
                    err_str = str(e).lower()

                    # Check if model is missing / decommissioned (no key will have it)
                    is_model_missing = (
                        "404" in err_str
                        or "model_not_found" in err_str
                        or "not found" in err_str
                        or "decommissioned" in err_str
                    )
                    if is_model_missing:
                        log.warning(
                            "Model '%s' is not found or decommissioned (%s). Cascading to next model...",
                            current_model,
                            str(e)[:100],
                        )
                        break

                    # Check if key issue (401, 403, 429 rate limit, quota, project blocked)
                    is_key_issue = (
                        "401" in err_str
                        or "403" in err_str
                        or "429" in err_str
                        or "rate_limit" in err_str
                        or "permissions_error" in err_str
                        or "blocked" in err_str
                        or "unauthorized" in err_str
                    )
                    if is_key_issue and len(keys) > 1 and key_offset < len(keys) - 1:
                        log.warning(
                            "Groq key #%d encountered error (%s). Seamlessly rotating to next key...",
                            current_key_idx + 1,
                            str(e)[:100],
                        )
                        break

                    # Transient connection/server error: brief retry with backoff
                    if attempt < retries:
                        time.sleep(1.0 * (attempt + 1))
                    else:
                        break

            if is_model_missing:
                break

    raise RuntimeError(
        f"All Groq API keys ({len(keys)}) and candidate models ({len(candidate_models)}) failed. Last error: {last_err}"
    )


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
