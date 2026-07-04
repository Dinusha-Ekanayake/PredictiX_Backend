"""Ticket summary generation service — local ONNX (ONNX Runtime) inference.

Loads the quantized ONNX ticket-summary model once and runs generation on CPU
via ONNX Runtime (Optimum). This replaces the retired/paywalled HF Inference
API path. The model is a fine-tuned BART summariser exported to ONNX + INT8.

Model location resolution (first match wins):
  1. env HF_TICKET_SUMMARIZATION_ONNX_REPO  (a HF repo id or a path)
  2. local  <backend-root>/onnx_ticket_summary_final/

Public functions keep their names so the /tickets + user-ticket callers and
app/ai/services/__init__.py don't need to change.
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

# ── Model location ──────────────────────────────────────────────────────────
# Load the ONNX model from HuggingFace (no local folder). Prefers an explicit
# ONNX repo var, else the main ticket-summarization repo.
_MODEL_LOCATION = (
    os.getenv("HF_TICKET_SUMMARIZATION_ONNX_REPO")
    or os.getenv("HF_TICKET_SUMMARIZATION_REPO")
    or ""
)


# ── Output quality guard ────────────────────────────────────────────────────
_GARBLE_PATTERNS = [
    re.compile(r"\bFPS\b", re.I),
    re.compile(r"\bCPS\b", re.I),
    re.compile(r"(.)\1{7,}"),                       # 8+ identical chars in a row
    re.compile(r"(?:\b\d[\d.]*\b[\s:,()]+){6,}"),   # 6+ bare numbers (quantization garble)
]


def _postprocess(text: str) -> str:
    """Clean raw model output: unglue sentences and trim trailing rambling.

    This BART model reliably produces a coherent summary then degrades into
    hallucinated fragments (e.g. "Site: Colombo DC.day Shift: Day shift..."),
    which always begin lowercase or with a mid-word "word:word" glue. We keep
    the leading well-formed sentences and drop the rest.
    """
    text = re.sub(r"(\.)([A-Za-z])", r"\1 \2", text.strip())   # unglue "DC.day"
    text = re.sub(r"\s{2,}", " ", text).strip()

    kept: list[str] = []
    for s in re.split(r"(?<=[.!?])\s+", text):
        s = s.strip()
        if not s:
            continue
        if kept and (s[0].islower() or re.search(r"[a-z]:[A-Za-z0-9]", s)):
            break  # first rambling/garbled fragment — stop here
        kept.append(s)
    return " ".join(kept).strip() or text


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
    if not text or len(text.strip()) < 15:
        return False
    return not any(p.search(text) for p in _GARBLE_PATTERNS)


def _fallback_summary(fields: dict[str, str]) -> str:
    """Deterministic summary from the parsed input fields (never garbled)."""
    title = fields.get("title")
    desc = fields.get("description")
    asset = fields.get("asset")
    category = fields.get("category")
    priority = fields.get("priority")

    base = title or (desc[:120] if desc else "Support ticket logged")
    sentence = base.rstrip(".")
    if asset:
        sentence += f" on asset {asset}"
    if category:
        sentence += f" ({category})"
    sentence += "."
    if priority:
        sentence += f" Priority: {priority}."
    return sentence


# ── Input formatting (unchanged public API) ─────────────────────────────────
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


# ── Model loading (cached) ──────────────────────────────────────────────────
@lru_cache(maxsize=1)
def get_ticket_summary_repo() -> str:
    """Back-compat shim — returns the resolved model location."""
    return _MODEL_LOCATION


@lru_cache(maxsize=1)
def get_ticket_summary_model() -> dict:
    """Load (first call) and cache the ONNX model + tokenizer."""
    if os.getenv("DISABLE_HF_MODELS", "false").lower() == "true":
        raise RuntimeError("Ticket summary model is disabled (DISABLE_HF_MODELS=true).")

    from optimum.onnxruntime import ORTModelForSeq2SeqLM  # noqa: PLC0415
    from transformers import AutoTokenizer  # noqa: PLC0415

    # If the model isn't a local dir, loading it means downloading from HF. Gate
    # that so teammates cloning the repo (no local model) don't fetch it just to
    # run the backend — the caller falls back to a deterministic summary. Set
    # ALLOW_MODEL_DOWNLOAD=true to enable the download.
    if not Path(_MODEL_LOCATION).is_dir() and os.getenv("ALLOW_MODEL_DOWNLOAD", "false").lower() != "true":
        raise RuntimeError(
            "Ticket summary model not present locally and downloads are disabled "
            "(set ALLOW_MODEL_DOWNLOAD=true) — using deterministic fallback."
        )

    token = os.getenv("HF_TOKEN")
    tokenizer = AutoTokenizer.from_pretrained(_MODEL_LOCATION, token=token)
    model = ORTModelForSeq2SeqLM.from_pretrained(_MODEL_LOCATION, token=token)
    logger.info("Ticket summary ONNX model loaded from: %s", _MODEL_LOCATION)
    return {"model": model, "tokenizer": tokenizer}


# ── Public prediction API (unchanged name/signature) ────────────────────────
def generate_ticket_summary(input_text: str) -> str:
    """Summarise the formatted ticket text using the local ONNX model.

    Falls back to a clean deterministic summary if the model is unavailable or
    produces malformed output, so a client never sees garbled text.
    """
    if not input_text or not input_text.strip():
        raise ValueError("input_text cannot be empty")

    fields = _parse_input_fields(input_text)

    try:
        data = get_ticket_summary_model()
        model, tokenizer = data["model"], data["tokenizer"]

        inputs = tokenizer(input_text, return_tensors="pt", max_length=512, truncation=True)
        summary_ids = model.generate(
            inputs["input_ids"],
            max_length=160,
            min_length=20,
            num_beams=4,
            early_stopping=True,
        )
        raw = _postprocess(tokenizer.decode(summary_ids[0], skip_special_tokens=True))
        if _is_clean_summary(raw):
            return raw
        logger.warning("[TicketSummary] model output rejected as malformed; using fallback")
    except Exception as e:  # noqa: BLE001
        logger.warning("[TicketSummary] model unavailable (%s); using fallback", e)

    return _fallback_summary(fields)


def warmup_ticket_summary_model() -> None:
    """Pre-load the ONNX model on application startup."""
    try:
        get_ticket_summary_model()
        print("Ticket summary ONNX model warmed up successfully")
    except Exception as e:  # noqa: BLE001
        print(f"Ticket summary model warmup failed (non-fatal): {e}")
