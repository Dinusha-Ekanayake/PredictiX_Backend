"""The shared Supabase client works with either server key."""
from __future__ import annotations

import pytest

from app.db.supabase_client import supabase_key


@pytest.mark.parametrize("key,service,expected", [
    ("anon-or-server", "service", "anon-or-server"),
    (None, "service", "service"),
    (None, None, None),
])
def test_supabase_key_falls_back_to_the_service_role_key(monkeypatch, key, service, expected):
    for name, value in (("SUPABASE_KEY", key), ("SUPABASE_SERVICE_ROLE_KEY", service)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    assert supabase_key() == expected


def test_report_service_uses_the_shared_client():
    from app.db.supabase_client import supabase
    from app.services import report_service

    assert report_service._get_supabase() is supabase
