"""Shared helper for the PredictiX Gradio Space (ticket categorization + priority).

The free-tier Space sleeps after a period of inactivity; the next real
request then pays a 20-60s cold-start penalty. A lightweight GET to the
Space's ``/config`` endpoint (Gradio's own app-config route) is enough to
wake it without invoking any real inference — this is what the warmers below
use, both at backend startup and on-demand from the login page.
"""

from __future__ import annotations

import logging
import os

import requests
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("predictix.ai")


def get_space_url() -> str:
    url = os.getenv("HF_AI_SPACE_URL")
    if not url:
        raise RuntimeError("HF_AI_SPACE_URL is not set in .env")
    return url.rstrip("/")


def ping_gradio_space(timeout: int = 60) -> bool:
    """Wake the Space with a lightweight GET. Returns True on a 2xx response.

    Never raises — callers (startup warmup, the public warmup endpoint) treat
    a failed/slow ping as non-fatal, since the Space will still cold-start on
    the next real inference call regardless.
    """
    try:
        space_url = get_space_url()
    except RuntimeError:
        log.debug("HF_AI_SPACE_URL not configured — skipping Space warmup.")
        return False

    try:
        resp = requests.get(f"{space_url}/config", timeout=timeout)
        ok = resp.status_code < 400
        if ok:
            log.info("Gradio Space warmed up (%s).", space_url)
        else:
            log.warning("Gradio Space ping returned HTTP %s (%s).", resp.status_code, space_url)
        return ok
    except requests.RequestException as exc:
        log.warning("Gradio Space ping failed (non-fatal): %s", exc)
        return False
