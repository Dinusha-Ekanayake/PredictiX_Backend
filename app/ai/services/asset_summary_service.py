"""Asset summary generation service — raw HF Inference API (online).

Raw HTTP to the Inference API URL — bypasses ``huggingface_hub``'s
client-side ``pipeline_tag`` validation, which rejects models whose model
card doesn't declare the field.

Public functions (``generate_asset_summary``, ``warmup_asset_summary_model``,
``get_asset_summary_model``) keep their existing names so the
``/asset-summaries`` router and shared callers don't need to change.
"""

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from app.ai.services._hf_inference import call_hf_inference

env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


def get_hf_credentials() -> tuple[str, str]:
    """Read HF credentials from the environment."""
    hf_token = os.getenv("HF_TOKEN")
    model_repo = os.getenv("HF_ASSET_SUMMARIZATION_REPO")
    if not hf_token:
        raise RuntimeError("HF_TOKEN is not set in .env")
    if not model_repo:
        raise RuntimeError("HF_ASSET_SUMMARIZATION_REPO is not set in .env")
    return hf_token, model_repo


@lru_cache(maxsize=1)
def get_asset_summary_repo() -> str:
    _, repo = get_hf_credentials()
    return repo


def get_asset_summary_model() -> dict:
    """Back-compat shim — older callers expected a ``{"model","tokenizer"}``
    dict. We return a truthy stand-in so their ``is not None`` checks pass."""
    return {"model": get_asset_summary_repo(), "tokenizer": None}


def generate_asset_summary(input_text: str) -> str:
    """Call the HF Inference API to summarise the formatted asset text.

    Args:
        input_text: Formatted input text (pipe-separated vehicle/asset attributes).
            Example: ``"Vehicle: SLW0225 | Type: Light Truck 3.5T | ..."``

    Returns:
        Generated summary string.
    """
    if not input_text or not input_text.strip():
        raise ValueError("input_text cannot be empty")

    try:
        repo = get_asset_summary_repo()
        raw = call_hf_inference(
            repo,
            input_text,
            parameters={"min_length": 50, "max_length": 256},
        )
    except Exception as e:
        raise RuntimeError(f"Summary generation failed: {e}")

    if isinstance(raw, list) and raw:
        item = raw[0]
        if isinstance(item, dict) and "summary_text" in item:
            return item["summary_text"]
    if isinstance(raw, dict) and "summary_text" in raw:
        return raw["summary_text"]
    return str(raw)


def warmup_asset_summary_model() -> None:
    """No-op for raw HTTP. Kept for symmetry with the old API."""
    get_asset_summary_repo()
