"""Groq LLM access with multi-key failover and a model cascade.

Which models a key can use changes over time (models are added and retired),
so the cascade is configurable with GROQ_MODELS (comma-separated, in order of
preference) and models a key does not have are remembered and skipped.

Reasoning models (openai/gpt-oss-*) spend output tokens on hidden reasoning
before the answer. A small max_tokens can be used up entirely by reasoning,
leaving an empty reply, so they get low reasoning effort and extra headroom.
An empty reply is treated as a failure and the next model is tried; it is
never returned as an answer.
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

# Groq "compound" systems run tools (web search) and are not available on every
# key; they are kept as names only for callers that request them explicitly.
MODEL_COMPOUND = "groq/compound"
MODEL_COMPOUND_MINI = "groq/compound-mini"

_DEFAULT_CASCADE = ["qwen/qwen3.8-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b"]


def _configured_cascade() -> list[str]:
    raw = os.getenv("GROQ_MODELS", "")
    models = [m.strip() for m in raw.split(",") if m.strip()]
    return models or list(_DEFAULT_CASCADE)


MODEL_CASCADE = _configured_cascade()
FAST_MODELS = MODEL_CASCADE
HEAVY_MODELS = MODEL_CASCADE
DEFAULT_MODEL = MODEL_CASCADE[0]

#: Models that returned "not found" for every configured key in this process.
_UNAVAILABLE_MODELS: set[str] = set()

#: Output tokens added for reasoning models so reasoning cannot crowd out the answer.
REASONING_HEADROOM = 1024

_NOT_FOUND = ("404", "model_not_found", "does not exist", "decommissioned")
_KEY_PROBLEM = ("401", "403", "429", "rate_limit", "permissions_error", "blocked", "unauthorized")


class EmptyCompletion(RuntimeError):
    """The model returned no usable text (for example its budget ran out while reasoning)."""


def _is_reasoning_model(model: str) -> bool:
    return model.startswith("openai/gpt-oss")


def _request_kwargs(model: str, messages: list[dict], max_tokens: int, temperature: float,
                    tools: Optional[list], tool_choice: Optional[str]) -> dict:
    kwargs: dict = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    if _is_reasoning_model(model):
        kwargs["reasoning_effort"] = "low"
        kwargs["max_tokens"] = max_tokens + REASONING_HEADROOM
    if tools:
        kwargs["tools"] = tools
    if tool_choice:
        kwargs["tool_choice"] = tool_choice
    return kwargs


def _get_api_keys() -> list[str]:
    """Retrieve all configured Groq API keys in priority order:
    1. WH_GROQ_API_KEY (Primary - always tried first)
    2. CHATBOT_GROQ_API_KEY (Secondary fallback)
    3. GROQ_API_KEY (Tertiary fallback)
    """
    keys: list[str] = []
    for var in ["WH_GROQ_API_KEY", "CHATBOT_GROQ_API_KEY", "GROQ_API_KEY"]:
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


def _complete_once(client: Groq, kwargs: dict, tools: Optional[list]):
    """One request. Returns the reply, or raises (EmptyCompletion for an empty reply)."""
    resp = client.chat.completions.create(**kwargs)
    choice = resp.choices[0]
    if tools:
        return choice.message
    content = (choice.message.content or "").strip()
    if not content:
        raise EmptyCompletion(f"empty reply from {kwargs['model']} (finish_reason={choice.finish_reason})")
    return content


def call_groq(
    *,
    messages: list[dict],
    model: str = "",
    max_tokens: int = 512,
    temperature: float = 0.3,
    retries: int = 1,
    tools: Optional[list] = None,
    tool_choice: Optional[str] = None,
) -> tuple[str | dict, str]:
    """Call Groq with multi-key failover, a model cascade and retry.

    Tries the requested model first, then the configured cascade. A model no
    key has is skipped (and remembered), a key is rotated on auth or rate-limit
    errors, transient errors are retried, and an empty reply moves on to the
    next model. Returns (content or tool message, fallback note).
    """
    global _ACTIVE_KEY_INDEX
    keys = _get_api_keys()
    if not keys:
        raise RuntimeError("No Groq API keys configured in environment")

    candidates: list[str] = []
    for m in [model or DEFAULT_MODEL, *MODEL_CASCADE]:
        if m and m not in candidates and m not in _UNAVAILABLE_MODELS:
            candidates.append(m)

    last_err: Optional[Exception] = None
    for model_idx, current_model in enumerate(candidates):
        kwargs = _request_kwargs(current_model, messages, max_tokens, temperature, tools, tool_choice)
        not_found_on_every_key = True

        for key_offset in range(len(keys)):
            key_idx = (_ACTIVE_KEY_INDEX + key_offset) % len(keys)
            client, _ = _get_client(key_idx)
            outcome = "next_model"
            for attempt in range(retries + 1):
                try:
                    reply = _complete_once(client, kwargs, tools)
                    _ACTIVE_KEY_INDEX = key_idx
                    if model_idx > 0:
                        log.info("Groq answered with fallback model %s (key #%d)", current_model, key_idx + 1)
                    return (reply, "")
                except EmptyCompletion as e:
                    last_err, not_found_on_every_key = e, False
                    log.warning("%s; trying the next model", e)
                    outcome = "next_model"
                    break
                except Exception as e:
                    last_err = e
                    err = str(e).lower()
                    if any(t in err for t in _NOT_FOUND):
                        outcome = "next_key"
                        break
                    not_found_on_every_key = False
                    if any(t in err for t in _KEY_PROBLEM):
                        log.warning("Groq key #%d failed (%s); rotating", key_idx + 1, str(e)[:100])
                        outcome = "next_key"
                        break
                    if attempt < retries:
                        time.sleep(1.0 * (attempt + 1))
                    outcome = "next_model"
            if outcome == "next_model":
                break

        if not_found_on_every_key:
            _UNAVAILABLE_MODELS.add(current_model)
            log.warning("Model %s is not available on any configured key; skipping it from now on", current_model)

    raise RuntimeError(f"All Groq keys ({len(keys)}) and models ({len(candidates)}) failed. Last error: {last_err}")


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
            max_tokens=500,
            temperature=0.5,
        )
        return msg + str(res)
    except Exception as e:
        log.error("Legacy answer failed: %s", e)
        return "I'm having trouble connecting to the AI service right now. Please try again shortly."
