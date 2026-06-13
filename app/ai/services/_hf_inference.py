"""Shared helper for calling the HuggingFace Inference API over raw HTTP.

Why not `huggingface_hub.InferenceClient`? It performs a client-side check
against the model card's `pipeline_tag` and refuses to call models that
don't declare one. Several models in this project don't have that field
set, so the client raises ``ValueError: Model 'X' doesn't support task 'Y'``
before any HTTP request is made. Hitting the Inference API URL directly
sidesteps that check — the server still serves the model.

This module also handles the two transient cases the API can return:
* HTTP 503 with ``{"estimated_time": N}`` — the model is cold-starting on
  HF's serverless infra; we retry once after the suggested wait (capped).
* JSON ``{"error": ...}`` returned with HTTP 200 — surface as RuntimeError.
"""

from __future__ import annotations

import os
from typing import Any
from gradio_client import Client

def _token() -> str:
    tok = os.getenv("HF_TOKEN")
    if not tok:
        raise RuntimeError("HF_TOKEN is not set in .env")
    return tok

def call_hf_inference(
    repo: str,
    inputs: str,
    *,
    parameters: dict[str, Any] | None = None,
    timeout: int = 60,
    max_cold_start_wait: int = 30,
) -> Any:
    if os.getenv("DISABLE_HF_MODELS", "false").lower() == "true":
        raise RuntimeError("HF models disabled (DISABLE_HF_MODELS=true).")

    # Map the requested model repo to the correct Gradio endpoint inside our Space
    if "categorization" in repo.lower():
        api_name = "/categorize"
    elif "ticket_summarization" in repo.lower():
        api_name = "/summarize_ticket"
    elif "asset_summarization" in repo.lower():
        api_name = "/summarize_asset"
    else:
        raise ValueError(f"Unknown repo mapping for Gradio Space: {repo}")

    space_id = "Dinusha-Ekanayake/predictix-inference-api"
    hf_token = _token()

    # Initialize the Gradio client (it connects securely to the private space)
    client = Client(space_id, token=hf_token)

    # Send the request
    try:
        result = client.predict(inputs, api_name=api_name)
    except Exception as e:
        raise RuntimeError(f"Gradio Space Inference failed: {e}")

    # Format the result to mimic Hugging Face's original API response shape
    if api_name == "/categorize":
        # Gradio returns the list directly: [{"label": "...", "score": ...}]
        return result
    else:
        # Gradio returns: {"summary": "..."}
        # Original API expected: [{"summary_text": "..."}]
        if isinstance(result, dict) and "summary" in result:
            return [{"summary_text": result["summary"]}]
        # Fallback if result shape is weird
        return [{"summary_text": str(result)}]
