"""Ticket categorization service — calls the PredictiX Gradio Space API."""

import json
import os
from functools import lru_cache

import requests
from dotenv import load_dotenv

load_dotenv()


def _get_space_url() -> str:
    url = os.getenv("HF_AI_SPACE_URL")
    if not url:
        raise RuntimeError("HF_AI_SPACE_URL is not set in .env")
    return url.rstrip("/")


@lru_cache(maxsize=1)
def get_ticket_categorizer_repo() -> str:
    return os.getenv("HF_TICKET_CATEGORIZATION_REPO", "")


# Keyword fallback used when the remote Space isn't configured/reachable, so
# category still works offline. Labels must match ALLOWED_CATEGORIES.
_CATEGORY_KEYWORDS = {
    "electrical": {
        "battery", "wiring", "wire", "electrical", "electric", "headlight",
        "light", "fuse", "alternator", "starter", "short circuit", "spark",
        "horn", "indicator", "dashboard", "charging", "voltage",
    },
    "software": {
        "software", "app", "application", "system", "screen", "display", "gps",
        "navigation", "update", "firmware", "bug", "crash", "login", "interface",
        "telematics", "glitch", "reboot", "freeze", "connectivity", "sync",
    },
    "mechanical": {
        "brake", "engine", "tire", "tyre", "transmission", "gear", "gearbox",
        "clutch", "suspension", "oil", "coolant", "hydraulic", "exhaust",
        "wheel", "axle", "bearing", "belt", "mechanical", "leak", "overheat",
        "seized", "breakdown", "steering", "vibration",
    },
}


def _rule_based_category(text: str) -> str | None:
    """Best-guess category from keyword hits; None if nothing matches."""
    lower = text.lower()
    scores = {cat: sum(kw in lower for kw in kws) for cat, kws in _CATEGORY_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else None


def categorize_ticket_text(title: str, description: str) -> dict:
    """Classify ticket text.

    Prefers the remote Gradio Space (HF_AI_SPACE_URL) when configured; otherwise
    falls back to a keyword classifier so category works without any Space.
    Returns ``{"predicted_label", "confidence", "scores"}``.
    """
    title = (title or "").strip()
    description = (description or "").strip()
    if not title and not description:
        raise ValueError("Both title and description cannot be empty.")

    text = f"Title: {title}\nDescription: {description}"

    try:
        space_url = _get_space_url()
        r1 = requests.post(
            f"{space_url}/gradio_api/call/categorize",
            json={"data": [text]},
            timeout=30,
        )
        if r1.status_code >= 400:
            raise RuntimeError(f"Categorization Space error {r1.status_code}: {r1.text[:200]}")
        event_id = r1.json().get("event_id")

        r2 = requests.get(
            f"{space_url}/gradio_api/call/categorize/{event_id}",
            stream=True,
            timeout=120,
        )
        raw = None
        for line in r2.iter_lines():
            if line:
                decoded = line.decode()
                if decoded.startswith("data:"):
                    raw = json.loads(decoded[5:])
                    break

        if not raw:
            raise RuntimeError("Categorization Space returned no data")
        result = raw[0] if isinstance(raw, list) else raw
        if isinstance(result, dict) and "error" in result:
            raise RuntimeError(f"Categorization model error: {result['error']}")
        if not isinstance(result, list) or not result:
            raise RuntimeError(f"Unexpected response shape: {result!r}")

        scores_sorted = sorted(result, key=lambda x: x.get("score", 0), reverse=True)
        top = scores_sorted[0]
        return {
            "predicted_label": top["label"],
            "confidence": round(float(top["score"]), 4),
            "scores": scores_sorted,
        }
    except Exception:
        # Space unavailable/unconfigured — keyword fallback (default: mechanical).
        label = _rule_based_category(text) or "mechanical"
        return {"predicted_label": label, "confidence": 0.5, "scores": []}


def warmup_ticket_categorizer() -> None:
    """Wake the shared Gradio Space (categorization + priority live on the
    same Space, so one ping warms both)."""
    from app.ai.services._gradio_space import ping_gradio_space
    ping_gradio_space()
