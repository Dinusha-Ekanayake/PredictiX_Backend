"""Ticket priority classification service — raw HF Inference API (online).

Calls the HuggingFace Inference API URL directly instead of going through
``huggingface_hub.InferenceClient``, which refuses to call models whose
model card doesn't declare a ``pipeline_tag``. The server itself happily
serves the model when we POST to its URL directly.
"""

import os
from functools import lru_cache

from dotenv import load_dotenv

from app.ai.services._hf_inference import call_hf_inference

load_dotenv()

MODEL_REPO = os.getenv("HF_TICKET_PRIORITIZATION_REPO")


def _assert_configured():
    if not os.getenv("HF_TOKEN"):
        raise RuntimeError("HF_TOKEN is not set in .env")
    if not MODEL_REPO:
        raise RuntimeError("HF_TICKET_PRIORITIZATION_REPO is not set in .env")


@lru_cache(maxsize=1)
def get_ticket_priority_repo() -> str:
    _assert_configured()
    return MODEL_REPO  # type: ignore[return-value]


def predict_ticket_priority(title: str, description: str) -> dict:
    """Predict a priority label via the HF Inference API.

    Returns ``{"predicted_label", "confidence", "scores"}`` where ``scores``
    is the full label list sorted by confidence descending.
    """
    title = (title or "").strip()
    description = (description or "").strip()
    if not title and not description:
        raise ValueError("Both title and description cannot be empty.")

    repo = get_ticket_priority_repo()
    text = f"Title: {title}\nDescription: {description}"
    raw = call_hf_inference(repo, text)

    # HF text-classification returns one of:
    #   * [{"label": ..., "score": ...}, ...]
    #   * [[{"label": ..., "score": ...}, ...]]  (nested when return_all_scores=True)
    if isinstance(raw, list) and raw and isinstance(raw[0], list):
        raw = raw[0]
    if not isinstance(raw, list) or not raw:
        raise RuntimeError(f"Unexpected priority response shape: {raw!r}")

    scores = [
        {"label": item["label"], "score": round(float(item["score"]), 4)}
        for item in raw
        if isinstance(item, dict) and "label" in item and "score" in item
    ]
    if not scores:
        raise RuntimeError("HF returned no priority predictions.")
    scores.sort(key=lambda x: x["score"], reverse=True)
    top = scores[0]

    return {
        "predicted_label": top["label"],
        "confidence": top["score"],
        "scores": scores,
    }


def warmup_ticket_priority() -> None:
    """No-op — the raw HTTP client is stateless. Kept for symmetry with the
    other services so ``app/main.py`` can still import it."""
    get_ticket_priority_repo()
