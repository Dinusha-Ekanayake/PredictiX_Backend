"""Asset summary generation service — HF Space (online) inference only.

Inference runs entirely on the private Hugging Face Space (ASSET_SUMMARY_SPACE)
via its Gradio API — no local model and no model download. If the Space is
unreachable, a clean, fully data-grounded deterministic summary built from the
asset fields is returned instead, so a client PDF never shows an error or
garbled text.

Public functions (``generate_asset_summary``, ``get_asset_summary_repo``) keep
their names so the ``/asset-summaries`` router and shared callers don't change.
"""

import os
import re
import logging
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
    # Artifacts observed from the fine-tuned model on asset inputs (hallucinated
    # labels/phrases that are not part of the retrieved data).
    re.compile(r"\bgame plan\b", re.I),
    re.compile(r"\bdietary\b", re.I),
    re.compile(r"\bnumber of engines\b", re.I),
    re.compile(r"\b(driver|target|current state)\s*:", re.I),
    re.compile(r"\bclassified as\b", re.I),
    re.compile(r"requires\s+\w+\s+fuel", re.I),          # "requires diesel fuel"
    re.compile(r"priority of \w+\s+[\d.]+", re.I),       # "priority of critical 1.1"
    re.compile(r"requires a \w+ priority", re.I),        # "requires a maintenance priority of..."
    re.compile(r"\b[A-Za-z][A-Za-z ]{1,25}:\s"),         # leaked "Label: value" fragments (model artifact)
]


def _numbers_in(text: str) -> set[str]:
    """All numeric tokens in text, comma-stripped, for grounding checks."""
    return {n.replace(",", "") for n in re.findall(r"\d[\d,]*\.?\d*", text or "")}


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


def _is_clean_summary(text: str, input_text: str = "") -> bool:
    """True only if the generated summary is coherent AND grounded in the data.

    Rejects model output that (a) is too short, (b) matches a known garble/
    hallucination pattern, or (c) contains a number absent from the source
    fields — which guarantees any published model summary sticks to the
    retrieved Supabase data. Anything rejected falls back to the deterministic
    field-based summary.
    """
    if not text or len(text.strip()) < 25:
        return False
    if any(p.search(text) for p in _GARBLE_PATTERNS):
        return False
    if input_text:
        source_numbers = _numbers_in(input_text)
        for n in _numbers_in(text):
            if n not in source_numbers:
                return False  # invented/hallucinated number → not grounded
    return True


def _join(items: list[str]) -> str:
    """Join clauses naturally: 'a', 'a and b', or 'a, b and c'."""
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _fallback_summary(fields: dict[str, str]) -> str:
    """Compose a clean, professional, fully data-grounded summary.

    Every clause is built straight from the retrieved asset fields (static
    attributes + latest AI prediction signals), so the output is guaranteed
    meaningful and to use exactly the Supabase data — no model, no invented
    facts. Used both as the standalone summary and as the safety net when the
    model output fails the quality/grounding guard.
    """
    name = fields.get("asset") or fields.get("vehicle") or "This asset"
    year = fields.get("year")
    model = fields.get("model") or fields.get("make")
    vtype = fields.get("vehicle type") or fields.get("type")
    fuel = fields.get("fuel")
    status = fields.get("status")
    health = fields.get("health")                    # health band (e.g. "moderate")
    health_score = fields.get("health score")        # numeric % (e.g. "8%")
    fprob = fields.get("failure probability")         # e.g. "99.8%"
    risk = fields.get("risk")                         # e.g. "critical"
    crit = fields.get("criticality score")
    mileage = fields.get("mileage")
    svc_due = fields.get("service due in")            # e.g. "1 day"
    priority = fields.get("maintenance priority")
    driver = fields.get("primary driver")             # per-asset failure driver (SHAP)

    sentences = []

    # 1) Identity
    desc = " ".join(x for x in (year, model) if x)
    if desc and vtype:
        ident = f"{name} is a {desc} {vtype}"
    elif desc:
        ident = f"{name} is a {desc}"
    elif vtype:
        ident = f"{name} is a {vtype}"
    else:
        ident = name
    if fuel:
        ident += f" running on {fuel}"
    sentences.append(ident + ".")

    # 2) Condition — lead with the AI prediction signals when present
    metrics = []
    if health_score:
        metrics.append(f"a component health score of {health_score}")
    elif health:
        metrics.append(f"{health} component health")
    if fprob:
        metrics.append(f"a {fprob} failure probability")
    if risk:
        metrics.append(f"a {risk.lower()} risk level")
    if crit:
        metrics.append(f"a criticality score of {crit}")

    if status and metrics:
        sentences.append(f"It is currently {status}, with {_join(metrics)}.")
    elif status:
        sentences.append(f"It is currently {status}.")
    elif metrics:
        sentences.append(f"It has {_join(metrics)}.")

    # Primary failure driver — the per-asset differentiator (why it is failing)
    if driver:
        sentences.append(f"The main factor driving this is {driver}.")

    # 3) Usage / service timing
    if mileage:
        sentences.append(f"The asset has {mileage} recorded on the odometer.")
    if svc_due:
        sentences.append(f"Its next service is due in {svc_due}.")

    # 4) Recommendation — grounded in priority / risk / health / status / criticality
    high_flags = {"high", "critical", "poor", "at risk", "at_risk"}

    def _is_severe(v: str) -> bool:
        return bool(v) and v.strip().lower() in high_flags

    is_high = any(_is_severe(v) for v in (priority, health, status, risk))
    if not is_high and crit:
        try:
            is_high = float(str(crit).split()[0]) >= 7.0
        except ValueError:
            pass
    if not is_high and fprob:
        try:
            is_high = float(fprob.replace("%", "").strip()) >= 70.0
        except ValueError:
            pass

    if priority:
        rec = f"Given its {priority} maintenance priority, "
    elif is_high:
        rec = "Given its elevated risk, "
    else:
        rec = ""
    if is_high:
        rec += "the asset should be prioritised for inspection and preventive servicing to avoid unplanned downtime."
    else:
        rec += "routine monitoring and scheduled servicing are sufficient."
    sentences.append(rec[:1].upper() + rec[1:])

    return " ".join(sentences)
    return sentence


def get_asset_summary_repo() -> str:
    """Return the HF Space id that serves asset summaries (for /health)."""
    return os.getenv("ASSET_SUMMARY_SPACE") or ""


def _summarize_via_space(space_id, input_text: str):
    """Run inference on a HuggingFace Space (online) via its Gradio API.

    Returns the summary string, or None if no Space is configured or it's
    unreachable/asleep (the caller then falls back). Spaces are private, so the
    HF_TOKEN is passed for auth.
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
        logger.warning("[AssetSummary] Space %s unavailable (%s)", space_id, e)
        return None


def generate_asset_summary(input_text: str) -> str:
    """Summarise the formatted asset text.

    Order: HF Space (online, ASSET_SUMMARY_SPACE) → deterministic fallback.
    Only output that passes the grounding/quality guard is published.
    """
    if not input_text or not input_text.strip():
        raise ValueError("input_text cannot be empty")

    fields = _parse_input_fields(input_text)

    space_out = _summarize_via_space(os.getenv("ASSET_SUMMARY_SPACE"), input_text)
    if space_out and _is_clean_summary(space_out, input_text):
        return space_out

    return _fallback_summary(fields)
