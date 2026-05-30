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
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


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

    try:
        model_data = get_asset_summary_model()
        model = model_data["model"]
        tokenizer = model_data["tokenizer"]

        inputs = tokenizer(
            input_text, return_tensors="pt", max_length=512, truncation=True
        )
        summary_ids = model.generate(
            inputs["input_ids"],
            max_length=256,
            min_length=50,
            num_beams=4,
            early_stopping=True,
        )
        return tokenizer.decode(summary_ids[0], skip_special_tokens=True)
    except Exception as e:
        raise RuntimeError(f"Summary generation failed: {e}")


def warmup_asset_summary_model() -> None:
    """Pre-load the model on application startup."""
    try:
        get_asset_summary_model()
        print("Asset summary model warmed up successfully")
    except Exception as e:
        print(f"Asset summary model warmup failed: {e}")
        raise
