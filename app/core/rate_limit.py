"""In-process request rate limiting.

The API runs as a single uvicorn worker, so one in-memory sliding window per
key is enough. Limits are generous: they stop scripted password guessing and
runaway LLM spend, not normal use.

Settings (all optional):
  RATE_LIMIT_ENABLED       true/false, default true
  LOGIN_RATE_LIMIT         login attempts per minute per client IP, default 20
  LOGIN_EMAIL_RATE_LIMIT   login attempts per minute per account email, default 10
  AI_RATE_LIMIT            chatbot / agent calls per minute per user, default 30
  REPORT_RATE_LIMIT        AI report generations per minute per user, default 6
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from typing import Callable

from fastapi import Depends, HTTPException, Request

from app.core.config import _env_flag

_WINDOW_SECONDS = 60.0


def _limit_from_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default
    return value if value > 0 else default


class SlidingWindowLimiter:
    """Counts hits per key over the last `window` seconds."""

    def __init__(self, window: float = _WINDOW_SECONDS) -> None:
        self.window = window
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._calls_since_sweep = 0

    def hit(self, key: str, limit: int, now: float | None = None) -> float | None:
        """Record a hit. Returns None when allowed, else seconds until a slot frees."""
        now = time.monotonic() if now is None else now
        cutoff = now - self.window
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= limit:
                return max(0.0, hits[0] + self.window - now)
            hits.append(now)
            self._calls_since_sweep += 1
            if self._calls_since_sweep >= 1000:
                self._sweep(cutoff)
            return None

    def _sweep(self, cutoff: float) -> None:
        self._calls_since_sweep = 0
        for key in [k for k, v in self._hits.items() if not v or v[-1] <= cutoff]:
            del self._hits[key]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _enforce(bucket: str, key: str, limit: int) -> None:
    if not _env_flag("RATE_LIMIT_ENABLED", True):
        return
    retry_after = limiter.hit(f"{bucket}:{key}", limit)
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please wait a moment and try again.",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )


def login_rate_limit(request: Request) -> None:
    _enforce("login", _client_ip(request), _limit_from_env("LOGIN_RATE_LIMIT", 20))


def login_email_rate_limit(email: str) -> None:
    """Per-account limit, so guesses spread across many IPs still hit a ceiling."""
    if email:
        _enforce("login-email", email.strip().lower(), _limit_from_env("LOGIN_EMAIL_RATE_LIMIT", 10))


def _user_limit(bucket: str, env_name: str, default: int) -> Callable:
    from app.deps import get_current_user

    def dependency(request: Request, current_user=Depends(get_current_user)) -> None:
        key = str(getattr(current_user, "id", "") or _client_ip(request))
        _enforce(bucket, key, _limit_from_env(env_name, default))

    return dependency


ai_rate_limit = _user_limit("ai", "AI_RATE_LIMIT", 30)
report_rate_limit = _user_limit("report", "REPORT_RATE_LIMIT", 6)
