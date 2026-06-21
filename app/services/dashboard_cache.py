"""Full-response dashboard cache with background refresh.

Root cause of dashboard latency: Supabase is hosted in ap-southeast-2. Each
DB round-trip costs ~170-250ms in network time regardless of query complexity.
With 9 sequential queries that's ~1.5-2.5s of pure wire overhead per request.

Solution: cache the entire response payload in memory. Serve from cache
instantly (sub-millisecond). Rebuild in a background thread every TTL seconds
so the data stays fresh without blocking any request.

Usage:
    from app.services.dashboard_cache import DashboardCache

    cache = DashboardCache("admin", ttl=60)

    @router.get("/summary")
    def summary(db=Depends(get_db)):
        return cache.get_or_refresh(db, _build_fn)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional

log = logging.getLogger("predictix")


class DashboardCache:
    """Thread-safe, TTL-based full-response cache for one dashboard endpoint.

    - First request: no cache → build synchronously, store, return.
    - Subsequent requests within TTL: return cached payload instantly.
    - On TTL expiry: serve stale payload immediately AND kick off a background
      rebuild so the next request after the rebuild gets fresh data.
    - If background rebuild fails: keep the previous payload (never 500 on cache
      miss) and retry on the next request.
    """

    def __init__(self, name: str, ttl: int = 60) -> None:
        self.name = name
        self.ttl = ttl
        self._lock = threading.Lock()
        self._payload: Optional[Any] = None
        self._built_at: float = 0.0
        self._refreshing: bool = False

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_or_refresh(self, db, build_fn: Callable) -> Any:
        """Return the cached payload or build it now (first call only).

        On subsequent calls: always returns cached payload instantly and
        triggers a background rebuild if TTL has expired.
        """
        with self._lock:
            payload = self._payload
            stale = self._is_stale()
            refreshing = self._refreshing

        if payload is None:
            # First ever call — must build synchronously so we have something to return.
            return self._build_sync(db, build_fn)

        if stale and not refreshing:
            # Serve stale instantly, refresh in background.
            self._start_background_refresh(build_fn)

        return payload

    # ── Internals ──────────────────────────────────────────────────────────────

    def _is_stale(self) -> bool:
        return (time.monotonic() - self._built_at) >= self.ttl

    def _build_sync(self, db, build_fn: Callable) -> Any:
        """Build synchronously (first-call path). Stores result and returns it."""
        try:
            payload = build_fn(db)
        except Exception:
            log.exception("[DashboardCache:%s] sync build failed", self.name)
            raise
        with self._lock:
            self._payload = payload
            self._built_at = time.monotonic()
        return payload

    def _start_background_refresh(self, build_fn: Callable) -> None:
        with self._lock:
            if self._refreshing:
                return
            self._refreshing = True

        t = threading.Thread(
            target=self._bg_worker,
            args=(build_fn,),
            daemon=True,
            name=f"dash_cache_{self.name}",
        )
        t.start()

    def _bg_worker(self, build_fn: Callable) -> None:
        from app.db.session import SessionLocal

        new_payload = None
        try:
            db = SessionLocal()
            try:
                new_payload = build_fn(db)
            finally:
                db.close()
        except Exception:
            log.warning("[DashboardCache:%s] background refresh failed (stale data kept)", self.name, exc_info=True)

        with self._lock:
            if new_payload is not None:
                self._payload = new_payload
                self._built_at = time.monotonic()
            else:
                # Back off: don't retry for half a TTL to avoid hammering a down DB.
                self._built_at = time.monotonic() - self.ttl + max(self.ttl // 2, 30)
            self._refreshing = False
