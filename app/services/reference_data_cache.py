"""Short-TTL in-memory cache for small, rarely-changing lookup tables.

Departments and warehouses barely ever change, but every request that needs
to resolve an id -> name (user lists, asset lists, etc.) was paying a full
DB round-trip (~150-800ms to the remote Supabase region) just to re-fetch a
handful of rows that were almost certainly unchanged since the last request.

This is a plain TTL cache (not a full-response cache like DashboardCache), it only holds the {id: name} maps, rebuilt on demand when stale. Safe to call
from any request path; on a cache miss it costs one query, same as before.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, TypeVar

T = TypeVar("T")

_DEFAULT_TTL_SECONDS = 120


class _TTLCache:
    def __init__(self, ttl: float = _DEFAULT_TTL_SECONDS) -> None:
        self.ttl = ttl
        self._lock = threading.Lock()
        self._value = None
        self._built_at = 0.0

    def get_or_build(self, build_fn: Callable[[], T]) -> T:
        with self._lock:
            if self._value is not None and (time.monotonic() - self._built_at) < self.ttl:
                return self._value

        # Build outside the lock so a slow query doesn't block other cache
        # readers that are still within TTL; a harmless duplicate build on a
        # cold/expired cache is fine (rare, and idempotent).
        value = build_fn()

        with self._lock:
            self._value = value
            self._built_at = time.monotonic()
        return value

    def invalidate(self) -> None:
        with self._lock:
            self._value = None
            self._built_at = 0.0


_department_names_cache = _TTLCache()
_warehouse_names_cache = _TTLCache()


def get_department_names() -> dict:
    """{department_id: name} for every department, cached for a short TTL."""
    from app.db.session import SessionLocal
    from app.models import Department

    def _build() -> dict:
        with SessionLocal() as db:
            return {d.id: d.name for d in db.query(Department.id, Department.name).all()}

    return _department_names_cache.get_or_build(_build)


def get_warehouse_names() -> dict:
    """{warehouse_id: name} for every warehouse, cached for a short TTL."""
    from app.db.session import SessionLocal
    from app.models import Warehouse

    def _build() -> dict:
        with SessionLocal() as db:
            return {w.id: w.name for w in db.query(Warehouse.id, Warehouse.name).all()}

    return _warehouse_names_cache.get_or_build(_build)


def invalidate_department_names() -> None:
    """Call after creating/renaming/deleting a department."""
    _department_names_cache.invalidate()


def invalidate_warehouse_names() -> None:
    """Call after creating/renaming/deleting a warehouse."""
    _warehouse_names_cache.invalidate()
