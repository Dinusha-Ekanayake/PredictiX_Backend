"""Non-blocking, short-TTL cache for the Admin Dashboard AI summary.

The admin dashboard must never block on the Groq LLM (a 3–10s round-trip).
This module keeps the most recent LLM-written ``insight_summary`` in memory and
refreshes it in a background thread:

  * ``get_cached_summary()`` returns the cached text instantly (or None) and
    never performs network/DB work.
  * ``maybe_refresh(...)`` triggers a background refresh only when the cache is
    stale and no refresh is already running — so request handlers stay fast.

A fresh DB session is opened inside the worker thread (the request-scoped
session is closed once the response is sent, so it cannot be reused here).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

log = logging.getLogger("predictix")

# Cache lifetime: serve the same LLM summary for this long before refreshing.
TTL_SECONDS = int(__import__("os").getenv("ADMIN_AI_SUMMARY_TTL", "600"))  # 10 min

_lock = threading.Lock()
_summary: Optional[str] = None
_fetched_at: float = 0.0
_refreshing: bool = False


def get_cached_summary() -> Optional[str]:
    """Return the cached AI summary instantly (no network/DB). None if empty."""
    with _lock:
        return _summary


def _is_stale() -> bool:
    return (time.monotonic() - _fetched_at) >= TTL_SECONDS


def maybe_refresh() -> None:
    """Start a background refresh if the cache is stale and none is in flight.

    Returns immediately; the refresh runs in a daemon thread with its own DB
    session. Safe to call on every request.
    """
    global _refreshing
    with _lock:
        if _refreshing or (_summary is not None and not _is_stale()):
            return
        _refreshing = True

    t = threading.Thread(target=_refresh_worker, daemon=True, name="admin_ai_summary")
    t.start()


def _refresh_worker() -> None:
    global _summary, _fetched_at, _refreshing
    new_summary: Optional[str] = None
    try:
        from app.db.session import SessionLocal
        from app.agents.report_agents import run_warehouse_agent

        db = SessionLocal()
        try:
            result = run_warehouse_agent(db)
            text = (result.get("ai_sections") or {}).get("insight_summary")
            new_summary = str(text).strip() if text else None
        finally:
            db.close()
    except Exception:
        # No API key / network / parse error — keep the previous value (if any).
        log.warning("Admin AI summary refresh failed (non-fatal).", exc_info=True)
    finally:
        with _lock:
            if new_summary:
                _summary = new_summary
                _fetched_at = time.monotonic()
            else:
                # Don't pin _fetched_at on failure so we retry on the next call,
                # but back off a little to avoid hammering a down LLM.
                _fetched_at = time.monotonic() - TTL_SECONDS + 60
            _refreshing = False
