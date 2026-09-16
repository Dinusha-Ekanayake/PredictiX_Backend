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
        # Per-key entries: key -> {"payload", "built_at", "refreshing"}.
        # The key is the active warehouse id (or "__all__" for the unscoped,
        # backwards-compatible global payload). This keeps each warehouse's
        # dashboard cached separately so a super_admin switching warehouses,
        # or two admins in different warehouses, never see each other's data.
        self._entries: dict[str, dict] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_or_refresh(self, db, build_fn: Callable, key: Optional[str] = None) -> Any:
        """Return the cached payload for `key` or build it now (first call only).

        `key` scopes the cache (e.g. the active warehouse id). Omitting it keeps
        the original single-payload behaviour. `build_fn` receives the db session
        (the caller closes over any key-specific filter it needs).

        On subsequent calls: always returns the cached payload instantly and
        triggers a background rebuild if TTL has expired.
        """
        k = key or "__all__"
        with self._lock:
            entry = self._entries.get(k)
            payload = entry["payload"] if entry else None
            stale = self._is_stale(entry)
            refreshing = entry["refreshing"] if entry else False

        if payload is None:
            # First ever call for this key, build synchronously.
            return self._build_sync(db, build_fn, k)

        if stale and not refreshing:
            self._start_background_refresh(build_fn, k)

        return payload

    # ── Internals ──────────────────────────────────────────────────────────────

    def _is_stale(self, entry: Optional[dict]) -> bool:
        if not entry:
            return True
        return (time.monotonic() - entry["built_at"]) >= self.ttl

    def _build_sync(self, db, build_fn: Callable, key: str) -> Any:
        """Build synchronously (first-call path). Stores result and returns it."""
        try:
            payload = build_fn(db)
        except Exception:
            log.exception("[DashboardCache:%s] sync build failed (key=%s)", self.name, key)
            raise
        with self._lock:
            self._entries[key] = {
                "payload": payload,
                "built_at": time.monotonic(),
                "refreshing": False,
            }
        return payload

    def _start_background_refresh(self, build_fn: Callable, key: str) -> None:
        with self._lock:
            entry = self._entries.get(key)
            if entry and entry["refreshing"]:
                return
            if entry:
                entry["refreshing"] = True

        t = threading.Thread(
            target=self._bg_worker,
            args=(build_fn, key),
            daemon=True,
            name=f"dash_cache_{self.name}_{key}",
        )
        t.start()

    def _bg_worker(self, build_fn: Callable, key: str) -> None:
        from app.db.session import SessionLocal

        new_payload = None
        try:
            db = SessionLocal()
            try:
                new_payload = build_fn(db)
            finally:
                db.close()
        except Exception:
            log.warning("[DashboardCache:%s] background refresh failed (stale data kept, key=%s)", self.name, key, exc_info=True)

        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                entry = {"payload": None, "built_at": 0.0, "refreshing": False}
                self._entries[key] = entry
            if new_payload is not None:
                entry["payload"] = new_payload
                entry["built_at"] = time.monotonic()
            else:
                # Back off: don't retry for half a TTL to avoid hammering a down DB.
                entry["built_at"] = time.monotonic() - self.ttl + max(self.ttl // 2, 30)
            entry["refreshing"] = False
