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
import time
from typing import Any

import requests

# Legacy host ``api-inference.huggingface.co`` was retired by HF and no longer
# resolves (DNS ``getaddrinfo`` failure). Serverless inference now lives behind
# the Inference Providers router; the ``hf-inference`` provider keeps the same
# ``{"inputs", "parameters"}`` request / pipeline-style response shape.
HF_API_URL = "https://router.huggingface.co/hf-inference/models/{repo}"


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
    """POST to HF Inference API and return the parsed JSON body.

    Args:
        repo: HuggingFace model repo id (e.g. ``"Owner/model-name"``).
        inputs: The text to feed to the model.
        parameters: Optional generation/decoding params (HF passes these
            through to the underlying pipeline).
        timeout: Per-request HTTP timeout (seconds).
        max_cold_start_wait: Max seconds we'll wait for a 503 cold-start
            retry. If HF asks for longer, we give up and raise.
    """
    url = HF_API_URL.format(repo=repo)
    headers = {
        "Authorization": f"Bearer {_token()}",
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {"inputs": inputs}
    if parameters:
        body["parameters"] = parameters

    for attempt in (1, 2):
        resp = requests.post(url, headers=headers, json=body, timeout=timeout)

        if resp.status_code == 503 and attempt == 1:
            # Cold start — wait the suggested time then retry once.
            try:
                wait = float(resp.json().get("estimated_time", 5))
            except Exception:
                wait = 5.0
            if wait > max_cold_start_wait:
                raise RuntimeError(
                    f"Model '{repo}' is loading; estimated wait {wait:.0f}s "
                    f"exceeds {max_cold_start_wait}s cap."
                )
            time.sleep(min(wait, max_cold_start_wait))
            continue

        if resp.status_code >= 400:
            # Try to surface the HF error body verbatim — usually JSON
            # ``{"error": "..."}`` but sometimes plain text.
            try:
                err = resp.json().get("error", resp.text)
            except Exception:
                err = resp.text
            raise RuntimeError(f"HF API {resp.status_code}: {err}")

        data = resp.json()
        # HF sometimes returns 200 with an ``{"error": ...}`` body.
        if isinstance(data, dict) and "error" in data and len(data) <= 2:
            raise RuntimeError(f"HF API error: {data['error']}")
        return data

    raise RuntimeError(f"Model '{repo}' did not respond after retry.")
