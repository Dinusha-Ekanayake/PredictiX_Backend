"""Ticket priority classification — calls the PredictiX Gradio Space API."""

import json
import os

import requests
from dotenv import load_dotenv

load_dotenv(override=True)

_LOW_KEYWORDS = {
    "scratch", "dent", "cosmetic", "minor", "small crack", "paint", "sticker",
    "mirror", "wiper", "next service", "next scheduled", "no rush", "low urgency",
    "seat cover", "floor mat", "trim", "logo", "decal", "cleaning",
}
_HIGH_KEYWORDS = {
    "fire", "smoke", "explosion", "fuel leak", "brake failure", "no brakes",
    "engine seized", "total failure", "accident", "crash", "rollover",
    "unsafe to drive", "cannot drive", "vehicle stopped", "complete breakdown",
    "coolant leak", "overheating", "electrical fire", "cannot start",
}


def _rule_based_override(text: str) -> str | None:
    lower = text.lower()
    if any(kw in lower for kw in _HIGH_KEYWORDS):
        return "High"
    if any(kw in lower for kw in _LOW_KEYWORDS):
        return "Low"
    return None


def _get_space_url() -> str:
    url = os.getenv("HF_AI_SPACE_URL")
    if not url:
        raise RuntimeError("HF_AI_SPACE_URL is not set in .env")
    return url.rstrip("/")


def predict_ticket_priority(
    title: str = "",
    description: str = "",
    **_kwargs,
) -> str:
    """Predict ticket priority via the remote Gradio Space.

    Returns 'Low', 'Medium', or 'High'.
    """
    combined = f"{title} {description}".strip() or "No issue description"

    override = _rule_based_override(combined)
    if override:
        return override

    # Prefer the remote Space; if it isn't configured/reachable, default to
    # "Medium" so the priority field always populates (High/Low come from the
    # keyword rules above).
    try:
        space_url = _get_space_url()
        r1 = requests.post(
            f"{space_url}/gradio_api/call/prioritize",
            json={"data": [combined]},
            timeout=30,
        )
        if r1.status_code >= 400:
            raise RuntimeError(f"Priority Space error {r1.status_code}: {r1.text[:200]}")
        event_id = r1.json().get("event_id")

        r2 = requests.get(
            f"{space_url}/gradio_api/call/prioritize/{event_id}",
            stream=True,
            timeout=120,
        )
        result = None
        for line in r2.iter_lines():
            if line:
                decoded = line.decode()
                if decoded.startswith("data:"):
                    result = json.loads(decoded[5:])
                    break

        if not result:
            raise RuntimeError("Priority Space returned no data")
        data = result[0] if isinstance(result, list) else result
        if isinstance(data, dict) and "error" in data:
            raise RuntimeError(f"Priority model error: {data['error']}")
        if isinstance(data, dict) and "priority" in data:
            return data["priority"]
        raise RuntimeError(f"Unexpected priority response: {result!r}")
    except Exception:
        return "Medium"


def warmup_ticket_priority() -> None:
    """Wake the shared Gradio Space (categorization + priority live on the
    same Space, so one ping warms both — kept as a separate call so the
    startup log line for each stays accurate/independent)."""
    from app.ai.services._gradio_space import ping_gradio_space
    ping_gradio_space()
