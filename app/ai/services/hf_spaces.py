"""Wake the Hugging Face Spaces PredictiX depends on, and keep them awake.

The ticket categorisation/priority model and the ticket and asset summary
models run on free Hugging Face Spaces, which sleep after 48 hours without
traffic. A sleeping Space makes the next request fall back (summaries) or
fail (categorisation) while it boots for a minute or more.

    python -m app.ai.services.hf_spaces            # wake all, wait until ready
    python -m app.ai.services.hf_spaces --no-wait  # just send the wake requests

The same code runs as the API's keep-alive job (every HF_SPACE_KEEPALIVE_HOURS,
default 6) and as the scheduled GitHub workflow hf-keepalive.yml, so the Spaces stay awake even
when the API itself is not running.

A Space is woken by any request to its *.hf.space host, and is ready when
Gradio's /config route answers 200 with JSON, which only happens once the
app inside it has started.
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Optional

import requests

log = logging.getLogger("predictix.hf_spaces")

#: Environment variables naming the Spaces: a *.hf.space URL or an owner/name id.
SPACE_SETTINGS = ("HF_AI_SPACE_URL", "TICKET_SUMMARY_SPACE", "ASSET_SUMMARY_SPACE")
REQUEST_TIMEOUT_S = 20
POLL_INTERVAL_S = 15
DEFAULT_WAIT_S = 600


@dataclass(frozen=True)
class Space:
    setting: str
    host: str          # https://<subdomain>.hf.space


@dataclass(frozen=True)
class WakeResult:
    space: Space
    ready: bool
    seconds: float
    detail: str


def space_host(value: str) -> str:
    """The https://<subdomain>.hf.space base for a Space URL or an owner/name id.

    Hugging Face builds the subdomain from "owner-name", lower-cased, with
    every character other than a letter or digit replaced by "-".
    """
    value = value.strip().rstrip("/")
    if value.startswith(("http://", "https://")):
        return value
    owner, _, name = value.partition("/")
    if not owner or not name:
        raise ValueError(f"not a Space URL or owner/name id: {value!r}")
    subdomain = re.sub(r"[^a-z0-9]+", "-", f"{owner}-{name}".lower()).strip("-")
    return f"https://{subdomain}.hf.space"


def configured_spaces() -> list[Space]:
    """Every Space configured for this deployment; unset settings are skipped."""
    spaces = []
    for setting in SPACE_SETTINGS:
        value = (os.getenv(setting) or "").strip()
        if value:
            spaces.append(Space(setting=setting, host=space_host(value)))
    return spaces


def _headers() -> dict:
    # The Spaces are private; the token used for inference also reaches them.
    token = os.getenv("HF_TOKEN_space") or os.getenv("SPACE_HF_TOKEN") or os.getenv("HF_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def is_ready(space: Space, session: Optional[requests.Session] = None) -> tuple[bool, str]:
    """True when the Space's Gradio app answers /config with JSON."""
    http = session or requests
    try:
        resp = http.get(f"{space.host}/config", headers=_headers(), timeout=REQUEST_TIMEOUT_S)
    except requests.RequestException as exc:
        return False, type(exc).__name__
    if resp.status_code != 200:
        return False, f"HTTP {resp.status_code}"
    try:
        resp.json()
    except ValueError:
        return False, "starting (not the app yet)"
    return True, "ready"


def wake(space: Space, *, wait_s: float = DEFAULT_WAIT_S, session: Optional[requests.Session] = None,
         sleep=time.sleep, clock=time.monotonic) -> WakeResult:
    """Send the wake request, then poll until the Space is ready or wait_s passes."""
    start = clock()
    ready, detail = is_ready(space, session)       # this request is also the wake-up
    while not ready and clock() - start < wait_s:
        sleep(POLL_INTERVAL_S)
        ready, detail = is_ready(space, session)
    return WakeResult(space, ready, round(clock() - start, 1), detail)


def wake_all(*, wait_s: float = DEFAULT_WAIT_S) -> list[WakeResult]:
    """Wake every configured Space. Spaces boot in parallel on Hugging Face,
    so all wake requests go out first and readiness is polled afterwards."""
    spaces = configured_spaces()
    with requests.Session() as session:
        for space in spaces:
            is_ready(space, session)
        return [wake(space, wait_s=wait_s, session=session) for space in spaces]


def keep_warm_job() -> None:
    """Scheduled job in the API: one quick request per Space, never raises."""
    try:
        for result in wake_all(wait_s=0):
            if not result.ready:
                log.info("HF Space %s not ready yet (%s); woken.", result.space.setting, result.detail)
    except Exception as exc:  # a keep-warm ping must never disturb the API
        log.warning("HF Space keep-warm failed (non-fatal): %s", exc)


def main(argv: Optional[list[str]] = None) -> int:
    from dotenv import load_dotenv

    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-wait", action="store_true", help="send the wake requests and exit")
    parser.add_argument("--wait", type=float, default=DEFAULT_WAIT_S, help="seconds to wait per Space")
    args = parser.parse_args(argv)

    if not configured_spaces():
        print(f"No Spaces configured (set {', '.join(SPACE_SETTINGS)}).")
        return 2
    results = wake_all(wait_s=0 if args.no_wait else args.wait)
    for r in results:
        print(f"{'READY  ' if r.ready else 'WAKING ' if args.no_wait else 'FAILED '} "
              f"{r.space.setting:22} {r.space.host}  ({r.detail}, {r.seconds}s)")
    if args.no_wait:
        return 0
    return 0 if all(r.ready for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
