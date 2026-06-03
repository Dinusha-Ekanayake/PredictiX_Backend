"""Ticket summary generation service — raw HF Inference API (online).

Same approach as the classification services: raw HTTP to the Inference API
URL to bypass ``huggingface_hub``'s client-side ``pipeline_tag`` check.
"""

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from app.ai.services._hf_inference import call_hf_inference

env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


def _get_credentials() -> str:
    if not os.getenv("HF_TOKEN"):
        raise RuntimeError("HF_TOKEN is not set in .env")
    repo = os.getenv("HF_TICKET_SUMMARIZATION_REPO")
    if not repo:
        raise RuntimeError("HF_TICKET_SUMMARIZATION_REPO is not set in .env")
    return repo


@lru_cache(maxsize=1)
def get_ticket_summary_repo() -> str:
    return _get_credentials()


def build_ticket_summary_input(
    title: str,
    description: str,
    *,
    asset_name: str | None = None,
    asset_code: str | None = None,
    category: str | None = None,
    priority: str | None = None,
) -> str:
    """Format ticket fields into the pipe-separated input the model expects."""
    parts: list[str] = []
    if title:
        parts.append(f"Title: {title.strip()}")
    if description:
        parts.append(f"Description: {description.strip()}")
    if asset_code or asset_name:
        asset_part = " ".join(p for p in [asset_code, asset_name] if p)
        parts.append(f"Asset: {asset_part}")
    if category:
        parts.append(f"Category: {category}")
    if priority:
        parts.append(f"Priority: {priority}")
    return " | ".join(parts)


def generate_ticket_summary(input_text: str) -> str:
    """Call the HF Inference API to summarise the formatted ticket text."""
    if not input_text or not input_text.strip():
        raise ValueError("input_text cannot be empty")

    repo = get_ticket_summary_repo()
    raw = call_hf_inference(
        repo,
        input_text,
        parameters={"min_length": 20, "max_length": 160},
    )

    # HF summarization returns ``[{"summary_text": "..."}]``.
    if isinstance(raw, list) and raw:
        item = raw[0]
        if isinstance(item, dict) and "summary_text" in item:
            return item["summary_text"]
    if isinstance(raw, dict) and "summary_text" in raw:
        return raw["summary_text"]
    return str(raw)


def warmup_ticket_summary_model() -> None:
    """No-op for raw HTTP. Kept for symmetry."""
    get_ticket_summary_repo()
