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


def _resolve_onnx_dir() -> Path:
    """Locate the local ONNX asset-summary model directory.

    Overridable via ASSET_SUMMARY_ONNX_DIR; otherwise defaults to
    ``onnx_asset_summary_final`` at the project root (or CWD).
    """
    env = os.getenv("ASSET_SUMMARY_ONNX_DIR")
    if env:
        return Path(env)
    candidates = [
        Path(__file__).resolve().parents[3] / "onnx_asset_summary_final",
        Path.cwd() / "onnx_asset_summary_final",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[0]


@lru_cache(maxsize=1)
def get_asset_summary_model() -> dict:
    """Load and cache the asset-summary model + tokenizer.

    Prefers the local ONNX (BART) model in ``onnx_asset_summary_final/`` via ONNX
    Runtime — far lighter on memory than the PyTorch weights and fully offline.
    Falls back to the HuggingFace PyTorch model only if the ONNX dir is missing.
    """
    if os.getenv("DISABLE_HF_MODELS", "false").lower() == "true":
        raise RuntimeError("Asset summary model is disabled (DISABLE_HF_MODELS=true).")

    from transformers import AutoTokenizer  # noqa: PLC0415

    onnx_dir = _resolve_onnx_dir()
    if onnx_dir.is_dir():
        from optimum.onnxruntime import ORTModelForSeq2SeqLM  # noqa: PLC0415
        tokenizer = AutoTokenizer.from_pretrained(str(onnx_dir))
        model = ORTModelForSeq2SeqLM.from_pretrained(str(onnx_dir))
        print(f"Asset summary ONNX model loaded from: {onnx_dir}")
        return {"model": model, "tokenizer": tokenizer}

    # Fallback: original PyTorch model from the Hub.
    from transformers import AutoModelForSeq2SeqLM  # noqa: PLC0415
    hf_token, model_repo = get_hf_credentials()
    tokenizer = AutoTokenizer.from_pretrained(model_repo, token=hf_token)
    model = AutoModelForSeq2SeqLM.from_pretrained(model_repo, token=hf_token)
    print(f"Asset summary model loaded from Hub fallback: {model_repo}")
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
            max_new_tokens=200,       # override the model's baked-in 96-token cap for a longer summary
            min_new_tokens=40,
            num_beams=4,
            no_repeat_ngram_size=3,   # stop the model repeating phrases when pushed longer
            length_penalty=1.3,       # gently favour fuller, complete summaries
            early_stopping=True,
        )
        raw = tokenizer.decode(summary_ids[0], skip_special_tokens=True).strip()
        if _is_clean_summary(raw, input_text):
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
