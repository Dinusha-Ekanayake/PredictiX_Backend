"""Shared Supabase client, created on first use.

Creating the client at import time made every module that imports this one
(routers, the chatbot) fail to load when SUPABASE_URL is unset, which broke
the unit tests and CI. The proxy below keeps the same name and API
(`from app.db.supabase_client import supabase`; `supabase.table(...)`) and
creates the real client the first time it is used.
"""
import os
import threading

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()


def supabase_key() -> str | None:
    """The server's Supabase key: SUPABASE_KEY, else SUPABASE_SERVICE_ROLE_KEY.

    Deployments set one or the other, and the shared client must work with
    either. (Storage uploads prefer the service-role key; see app/core/storage.py.)
    """
    return os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")


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
                            "SUPABASE_URL and SUPABASE_KEY (or SUPABASE_SERVICE_ROLE_KEY) must be set to use Supabase."
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
