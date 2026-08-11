"""Public, unauthenticated warmup endpoint for the PredictiX Gradio Space.

The Space (ticket categorization + priority) sleeps after inactivity and
pays a 20-60s cold-start on the next real inference call. To avoid that
penalty hitting a user mid-workflow, the frontend fires this endpoint as
soon as the login page mounts (before the user has a token) — no auth
dependency on purpose, since there is no session yet at that point.

Fire-and-forget by design: the frontend does not wait on this call, and this
endpoint itself doesn't block the request past the ping duration; a failed
or slow ping is logged but never surfaced as an error, since login must
never depend on the Space being reachable.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/warmup", tags=["Warmup"])


@router.post("/inference-space")
def warmup_inference_space() -> dict:
    """Ping the Gradio Space to wake it. Always returns 200 — the `warmed`
    field tells the caller whether the ping actually succeeded, but a
    failure here must never block or fail the login flow."""
    from app.ai.services._gradio_space import ping_gradio_space

    warmed = ping_gradio_space(timeout=60)
    return {"warmed": warmed}
