"""Ticket summary generation service — HF Space (online) inference only.

Inference runs entirely on the private Hugging Face Space (TICKET_SUMMARY_SPACE)
via its Gradio API — no local model and no model download. If the Space is
unreachable, a clean deterministic summary built from the ticket fields is
returned instead, so a client never sees an error or garbled text.

Public functions keep their names so the /tickets + user-ticket callers and
app/ai/services/__init__.py don't need to change.
"""

import os
import re
import logging

from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
load_dotenv(dotenv_path=env_path)

logger = logging.getLogger(__name__)


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
    """Deterministic ticket summary from the parsed fields (never garbled).

    Reads as a short paragraph and always weaves in the (possibly default)
    category and priority so the output is meaningful even without the model.
    """
    title = (fields.get("title") or "").strip()
    desc = (fields.get("description") or "").strip()
    asset = (fields.get("asset") or "").strip()
    category = (fields.get("category") or "").strip().lower()
    priority = (fields.get("priority") or "").strip().lower()

    subject = (title or (desc[:80] if desc else "A support issue")).rstrip(".")

    # 1) What it is — category + asset
    tail = []
    if category:
        article = "an" if category[:1] in "aeiou" else "a"
        tail.append(f"{article} {category} issue")
    if asset:
        tail.append(f"on asset {asset}")
    sentences = [f"{subject} is " + " ".join(tail) + "." if tail else subject + "."]

    # 2) Detail from the description (trimmed, grounded)
    if desc and desc.lower() not in subject.lower():
        d = desc if len(desc) <= 160 else desc[:157].rstrip() + "…"
        if not d.endswith((".", "…", "!", "?")):
            d += "."
        sentences.append(d[0].upper() + d[1:])

    # 3) Priority + recommendation
    if priority in ("high", "critical"):
        sentences.append(f"It is assessed as {priority} priority and needs prompt attention.")
    elif priority == "low":
        sentences.append(f"It is assessed as {priority} priority and can be scheduled routinely.")
    elif priority:
        sentences.append(f"It is assessed as {priority} priority.")

    return " ".join(sentences)


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


# ── Space location (reported by /ticket-summaries/health) ───────────────────
def get_ticket_summary_repo() -> str:
    """Return the HF Space id that serves ticket summaries (for /health)."""
    return os.getenv("TICKET_SUMMARY_SPACE") or ""


# ── Public prediction API (unchanged name/signature) ────────────────────────
def _summarize_via_space(space_id, input_text: str):
    """Run inference on a HuggingFace Space (online) via its Gradio API.

    Returns the summary, or None if no Space is configured or it's unreachable/
    asleep (the caller then falls back). Spaces are private, so HF_TOKEN is used.
    """
    if not space_id:
        return None
    try:
        from gradio_client import Client  # noqa: PLC0415
        space_token = (
            os.getenv("HF_TOKEN_space")
            or os.getenv("SPACE_HF_TOKEN")
            or os.getenv("HF_TOKEN")
            or None
        )
        client = Client(space_id, token=space_token, verbose=False)
        out = client.predict(input_text, api_name="/predict")
        return (out or "").strip() or None
    except Exception as e:  # noqa: BLE001
        logger.warning("[TicketSummary] Space %s unavailable (%s)", space_id, e)
        return None


def generate_ticket_summary(input_text: str) -> str:
    """Summarise the formatted ticket text.

    Order: HF Space (online, TICKET_SUMMARY_SPACE) → deterministic fallback,
    so a client never sees an error or garbled text.
    """
    if not input_text or not input_text.strip():
        raise ValueError("input_text cannot be empty")

    fields = _parse_input_fields(input_text)

    space_out = _summarize_via_space(os.getenv("TICKET_SUMMARY_SPACE"), input_text)
    if space_out:
        cleaned = _postprocess(space_out)
        if _is_clean_summary(cleaned):
            return cleaned

    return _fallback_summary(fields)
