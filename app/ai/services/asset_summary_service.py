"""Asset summary generation service — local Seq2Seq inference (offline).

Loads the fine-tuned Seq2Seq model from HuggingFace **once** and runs
``model.generate`` locally on CPU. This is the original approach (it ran fine
before the merge that briefly switched to the online HF Inference API, which
HF has since retired/paywalled).

Public functions (``generate_asset_summary``, ``warmup_asset_summary_model``,
``get_asset_summary_model``, ``get_asset_summary_repo``, ``get_hf_credentials``)
keep their names so the ``/asset-summaries`` router and shared callers don't
need to change.
"""

import os
import re
import logging
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

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


def get_hf_credentials() -> tuple[str, str]:
    """Read HF credentials from the environment.

    The token is only used to *download* the (private/public) model weights
    from the Hub the first time; inference itself runs locally and offline.
    """
    hf_token = os.getenv("HF_TOKEN")
    model_repo = os.getenv("HF_ASSET_SUMMARIZATION_REPO")
    if not hf_token:
        raise RuntimeError("HF_TOKEN is not set in .env")
    if not model_repo:
        raise RuntimeError("HF_ASSET_SUMMARIZATION_REPO is not set in .env")
    return hf_token, model_repo


@lru_cache(maxsize=1)
def get_asset_summary_repo() -> str:
    """Back-compat shim — the router imports this. Returns the repo id."""
    _, repo = get_hf_credentials()
    return repo


@lru_cache(maxsize=1)
def get_asset_summary_model() -> dict:
    """Download (first call) and cache the local model + tokenizer."""
    if os.getenv("DISABLE_HF_MODELS", "false").lower() == "true":
        raise RuntimeError("Asset summary model is disabled (DISABLE_HF_MODELS=true).")

    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer  # noqa: PLC0415
    hf_token, model_repo = get_hf_credentials()
    tokenizer = AutoTokenizer.from_pretrained(model_repo, token=hf_token)
    model = AutoModelForSeq2SeqLM.from_pretrained(model_repo, token=hf_token)
    print(f"Asset summary model loaded locally from: {model_repo}")
    return {"model": model, "tokenizer": tokenizer}


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

    # Try the fine-tuned model, but only publish its output if it passes the
    # quality guard. Any failure or malformed result falls back to a clean,
    # deterministic summary so a client PDF never shows garbled text.
    try:
        model_data = get_asset_summary_model()
        model = model_data["model"]
        tokenizer = model_data["tokenizer"]

        inputs = tokenizer(
            input_text, return_tensors="pt", max_length=512, truncation=True
        )
        summary_ids = model.generate(
            inputs["input_ids"],
            max_length=512,
            min_length=80,
            num_beams=4,
            no_repeat_ngram_size=3,   # stop the model repeating phrases when pushed longer
            length_penalty=1.3,       # gently favour fuller, complete summaries
            early_stopping=True,
        )
        raw = tokenizer.decode(summary_ids[0], skip_special_tokens=True).strip()
        if _is_clean_summary(raw):
            return raw
        logger.warning("[AssetSummary] model output rejected as malformed; using deterministic fallback")
    except Exception as e:
        logger.warning(f"[AssetSummary] model unavailable ({e}); using deterministic fallback")

    return _fallback_summary(fields)


def warmup_asset_summary_model() -> None:
    """Pre-load the model on application startup."""
    try:
        get_asset_summary_model()
        print("Asset summary model warmed up successfully")
    except Exception as e:
        print(f"Asset summary model warmup failed: {e}")
        raise
