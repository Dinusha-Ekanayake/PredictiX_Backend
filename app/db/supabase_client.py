"""Shared Supabase client, created on first use.

Creating the client at import time made every module that imports this one
(routers, the chatbot) fail to load when SUPABASE_URL is unset, which broke
the unit tests and CI. The proxy below keeps the same name and API
(`from app.db.supabase_client import supabase`; `supabase.table(...)`) and
creates the real client the first time it is used.
"""
import base64
import json
import os
import threading

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()


def is_public_key(key: str) -> bool:
    """True for a key meant for browsers: a legacy anon JWT or a publishable key.

    Such a key carries only the permissions granted to anonymous visitors, so
    a server using it silently depends on the database being open to
    everyone. The server never uses one.
    """
    if key.startswith("sb_publishable_"):
        return True
    parts = key.split(".")
    if len(parts) != 3:
        return False
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(padded)).get("role") == "anon"
    except (ValueError, json.JSONDecodeError):
        return False


def supabase_key() -> str | None:
    """The server's Supabase key: the service-role key, never a public one.

    SUPABASE_SERVICE_ROLE_KEY is preferred; SUPABASE_KEY is accepted only when
    it is itself a server key. Every server-side Supabase client uses this.
    """
    for name in ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_KEY"):
        key = (os.getenv(name) or "").strip()
        if key and not is_public_key(key):
            return key
    return None


class _LazySupabase:
    """Forwards attribute access to a Supabase client built on first use."""

    def __init__(self) -> None:
        self._client: Client | None = None
        self._lock = threading.Lock()

    def _get(self) -> Client:
        if self._client is None:
            with self._lock:
                if self._client is None:
                    url, key = os.getenv("SUPABASE_URL"), supabase_key()
                    if not url or not key:
                        raise RuntimeError(
                            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set to use Supabase."
                        )
                    self._client = create_client(url, key)
        return self._client

    def __getattr__(self, name: str):
        # Introspection (mock.patch, copy, inspect) probes private and dunder
        # names; answering those must not open a connection.
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._get(), name)


supabase: Client = _LazySupabase()  # type: ignore[assignment]
