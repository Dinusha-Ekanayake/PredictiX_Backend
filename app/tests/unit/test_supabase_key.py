"""The server uses the service-role key and never the browsers' public key."""
from __future__ import annotations

import base64
import json

import pytest

from app.db.supabase_client import is_public_key, supabase_key


def _jwt(role: str) -> str:
    def part(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    return f"{part({'alg': 'HS256'})}.{part({'role': role, 'iss': 'supabase'})}.signature"


ANON, SERVICE = _jwt("anon"), _jwt("service_role")


@pytest.mark.parametrize("key,expected", [
    (ANON, True), ("sb_publishable_abc123", True),
    (SERVICE, False), ("sb_secret_abc123", False), ("not-a-jwt", False), ("a.!!!.c", False),
], ids=["anon-jwt", "publishable", "service-jwt", "secret", "opaque", "malformed"])
def test_is_public_key(key, expected):
    assert is_public_key(key) is expected


@pytest.mark.parametrize("key,service,expected", [
    (ANON, SERVICE, SERVICE),        # service role wins
    (SERVICE, None, SERVICE),        # SUPABASE_KEY accepted only when it is a server key
    (ANON, None, None),              # a public key alone is refused
    ("sb_publishable_x", None, None),
    (None, None, None),
], ids=["prefers-service-role", "server-key-in-supabase-key", "anon-only", "publishable-only", "none"])
def test_supabase_key_never_returns_a_public_key(monkeypatch, key, service, expected):
    for name, value in (("SUPABASE_KEY", key), ("SUPABASE_SERVICE_ROLE_KEY", service)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    assert supabase_key() == expected


def test_production_refuses_to_start_with_only_the_public_key(monkeypatch):
    import app.core.config as config

    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("SUPABASE_KEY", ANON)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SUPABASE_SERVICE_ROLE_KEY"):
        config.require_runtime_settings()

    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", SERVICE)
    config.require_runtime_settings()


def test_development_starts_without_a_supabase_key(monkeypatch):
    import app.core.config as config

    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    config.require_runtime_settings()
