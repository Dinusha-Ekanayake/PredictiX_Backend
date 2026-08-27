"""Public, unauthenticated warmup endpoint for the PredictiX Gradio Space.

The Space (ticket categorization + priority) sleeps after inactivity and
pays a 20-60s cold-start on the next real inference call. To avoid that
penalty hitting a user mid-workflow, the frontend fires this endpoint as
soon as the login page mounts (before the user has a token), no auth
dependency on purpose, since there is no session yet at that point.

Fire-and-forget by design: the frontend does not wait on this call, and this
endpoint itself doesn't block the request past the ping duration; a failed
or slow ping is logged but never surfaced as an error, since login must
never depend on the Space being reachable.
"""
from __future__ import annotations

import logging
import threading
import time

from fastapi import APIRouter

log = logging.getLogger("predictix.warmup")

router = APIRouter(prefix="/warmup", tags=["Warmup"])

#: A Space stays awake for far longer than this, so pinging more often than
#: once a minute cannot wake anything that is not already awake.
_COOLDOWN_SECONDS = 60.0

_lock = threading.Lock()
_last_ping_at: float = 0.0
_last_result: bool = False


@router.post("/inference-space")
def warmup_inference_space() -> dict:
    """Ping the Gradio Space to wake it. Always returns 200, the `warmed`
    field tells the caller whether the ping actually succeeded, but a
    failure here must never block or fail the login flow.

    Rate-limited by a process-wide cooldown. This endpoint is unauthenticated
    by necessity (it runs before login), runs synchronously, and waits up to
    60s on an external host, so without a cooldown, repeated calls could tie
    up a worker thread each and starve the very login requests it exists to
    speed up. The cooldown also removes redundant work in normal use: several
    tabs opening the login page produce one ping, not several.
    """
    global _last_ping_at, _last_result

    now = time.monotonic()
    with _lock:
        age = now - _last_ping_at
        if _last_ping_at and age < _COOLDOWN_SECONDS:
            # Report the real cached outcome rather than an optimistic True.
            return {"warmed": _last_result, "cached": True,
                    "age_seconds": round(age, 1)}

    from app.ai.services._gradio_space import ping_gradio_space

    warmed = ping_gradio_space(timeout=60)

    with _lock:
        _last_ping_at = time.monotonic()
        _last_result = warmed

    if not warmed:
        log.info("Gradio Space warmup ping did not succeed; login is unaffected.")
    return {"warmed": warmed, "cached": False}
