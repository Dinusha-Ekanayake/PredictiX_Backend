"""Asset summary generation service — raw HF Inference API (online).

Uses the online HF Inference API to generate asset summaries, bypassing
huggingface_hub's client-side checks and avoiding slow local weight downloads.
"""

import os
import re
import logging
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from app.ai.services._hf_inference import call_hf_inference

env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

logger = logging.getLogger(__name__)


# ── Output quality guard ────────────────────────────────────────────────
# The fine-tuned Seq2Seq model occasionally emits malformed text (leaked
# feature tokens like "FPS:"/"CPS:", broken percentages like "99%.8", or
# circular phrasing such as "requires 99.8% failure probability"). Such output
# must never reach a client PDF, so we validate it and fall back to a clean,
# deterministic summary built from the same input fields when it fails.

_GARBLE_PATTERNS = [
    re.compile(r"\bFPS\b", re.I),
    re.compile(r"\bCPS\b", re.I),
    re.compile(r"\bCargo\s*:", re.I),
    re.compile(r"\d\s*%\s*\.\s*\d"),                       # "99%.8"
    re.compile(r"requires\s+[\d.]+\s*%?\s*failure", re.I), # "requires 99.8% failure probability"
    re.compile(r"health score of critical", re.I),
]


def _parse_input_fields(input_text: str) -> dict[str, str]:
    """Parse the pipe-separated 'Key: Value | Key: Value' input into a dict."""
    fields: dict[str, str] = {}
    for part in input_text.split("|"):
        if ":" in part:
            key, _, val = part.partition(":")
            key, val = key.strip().lower(), val.strip()
            if key and val:
                fields[key] = val
    return fields


def _is_clean_summary(text: str) -> bool:
    """True only if the generated summary is coherent enough to publish."""
    if not text or len(text.strip()) < 25:
        return False
    return not any(p.search(text) for p in _GARBLE_PATTERNS)


def _fallback_summary(fields: dict[str, str]) -> str:
    """Build a clean, professional summary deterministically from the fields."""
    subject = fields.get("vehicle") or fields.get("asset") or "This asset"
    vtype = fields.get("type")
    if vtype:
        subject = f"{subject} ({vtype})"

    risk = fields.get("risk")
    health = fields.get("health score") or fields.get("health")
    fprob = fields.get("failure probability")

    descriptors = []
    if health:
        descriptors.append(f"a health score of {health}")
    if fprob:
        descriptors.append(f"a {fprob} failure probability")

    sentence = subject
    sentence += f" is assessed as {risk.lower()} risk" if risk else " requires review"
    if descriptors:
        sentence += ", with " + " and ".join(descriptors)
    sentence += "."

    if risk and risk.lower() in ("critical", "high"):
        sentence += " Immediate inspection and prioritised servicing are recommended."
    else:
        sentence += " Continued monitoring is recommended."
    return sentence


def get_asset_summary_repo() -> str:
    """Returns the HF repo ID for the summarization model."""
    hf_token = os.getenv("HF_TOKEN")
    model_repo = os.getenv("HF_ASSET_SUMMARIZATION_REPO")
    if not hf_token:
        raise RuntimeError("HF_TOKEN is not set in .env")
    if not model_repo:
        raise RuntimeError("HF_ASSET_SUMMARIZATION_REPO is not set in .env")
    return model_repo


def generate_asset_summary(input_text: str) -> str:
    """Summarise the formatted asset text using the local Seq2Seq model.

    Args:
        input_text: Formatted input text (pipe-separated vehicle/asset attributes).
            Example: ``"Vehicle: SLW0225 | Type: Light Truck 3.5T | ..."``

    Returns:
        Generated summary string.
    """
    if not input_text or not input_text.strip():
        raise ValueError("input_text cannot be empty")

    fields = _parse_input_fields(input_text)

    # Try the fine-tuned model via HF Inference API
    try:
        repo = get_asset_summary_repo()
        raw = call_hf_inference(
            repo,
            input_text,
            parameters={
                "min_length": 50,
                "max_length": 256,
                "num_beams": 4,
                "early_stopping": True
            }
        )
        
        # HF summarization returns ``[{"summary_text": "..."}]``.
        generated_text = ""
        if isinstance(raw, list) and raw and isinstance(raw[0], dict) and "summary_text" in raw[0]:
            generated_text = raw[0]["summary_text"]
        elif isinstance(raw, dict) and "summary_text" in raw:
            generated_text = raw["summary_text"]
        else:
            generated_text = str(raw)

        if _is_clean_summary(generated_text):
            return generated_text
        logger.warning("[AssetSummary] model output rejected as malformed; using deterministic fallback")
    except Exception as e:
        logger.warning(f"[AssetSummary] model unavailable ({e}); using deterministic fallback")

    return _fallback_summary(fields)


def warmup_asset_summary_model() -> None:
    """No-op for raw HTTP. Kept for symmetry with lifespan."""
    get_asset_summary_repo()
