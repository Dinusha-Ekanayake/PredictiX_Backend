"""Ticket categorization service — raw HF Inference API (online).

Same approach as ``ticket_priority_service``: we POST to the HF Inference
API URL directly to bypass ``huggingface_hub``'s client-side check that
rejects models without a ``pipeline_tag`` in their model card.

Public functions (``categorize_ticket_text``, ``warmup_ticket_categorizer``)
keep the same signatures and return shapes so existing callers don't change.
"""

import os
from functools import lru_cache

from dotenv import load_dotenv

from app.ai.services._hf_inference import call_hf_inference

load_dotenv()

MODEL_REPO = os.getenv("HF_TICKET_CATEGORIZATION_REPO")


def _assert_configured():
    if not os.getenv("HF_TOKEN"):
        raise RuntimeError("HF_TOKEN is not set in .env")
    if not MODEL_REPO:
        raise RuntimeError("HF_TICKET_CATEGORIZATION_REPO is not set in .env")


@lru_cache(maxsize=1)
def get_ticket_categorizer_repo() -> str:
    _assert_configured()
    return MODEL_REPO  # type: ignore[return-value]


def categorize_ticket_text(title: str, description: str) -> dict:
    """Classify the ticket text into a category via the HF Inference API.

    Returns ``{"predicted_label", "confidence", "scores"}``.
    """
    title = (title or "").strip()
    description = (description or "").strip()
    if not title and not description:
        raise ValueError("Both title and description cannot be empty.")

    repo = get_ticket_categorizer_repo()
    text = f"Title: {title}\nDescription: {description}"
    raw = call_hf_inference(repo, text)

    if isinstance(raw, list) and raw and isinstance(raw[0], list):
        raw = raw[0]
    if not isinstance(raw, list) or not raw:
        raise RuntimeError(f"Unexpected category response shape: {raw!r}")

    scores = [
        {"label": item["label"], "score": round(float(item["score"]), 4)}
        for item in raw
        if isinstance(item, dict) and "label" in item and "score" in item
    ]
    if not scores:
        raise RuntimeError("HF returned no category predictions.")
    scores.sort(key=lambda x: x["score"], reverse=True)
    top = scores[0]

    return {
        "predicted_label": top["label"],
        "confidence": top["score"],
        "scores": scores,
    }


def warmup_ticket_categorizer() -> None:
    """No-op — the raw HTTP client is stateless."""
    get_ticket_categorizer_repo()
