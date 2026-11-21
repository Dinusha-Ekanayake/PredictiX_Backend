"""Shared fixtures for tests that talk to the real app and database.

These are integration tests: they need DATABASE_URL to point at a reachable
database with the demo accounts seeded. They are read-only unless a test says
otherwise, and any test that writes must clean up after itself.

Skip them with:  pytest -m "not integration"
"""
import os

import pytest
from dotenv import load_dotenv

# The application reads its configuration from .env, so load it here too.
# Without this, running an integration file on its own skips every test, while
# running the whole suite happens to work because an earlier import already
# loaded it. Same result either way is what makes the suite trustworthy.
load_dotenv()

# Test accounts. The passwords come from the environment (GitHub Actions
# secrets in CI, .env locally) because this repository is public.
DEMO = {
    "super": (os.getenv("TEST_SUPER_EMAIL", "demosuperadmin@lankalogix.com"), os.getenv("TEST_SUPER_PASSWORD", "")),
    "admin": (os.getenv("TEST_ADMIN_EMAIL", "demoadmincolombo.adm@lankalogix.com"), os.getenv("TEST_ADMIN_PASSWORD", "")),
    "user": (os.getenv("TEST_USER_EMAIL", "demousercolombo.adm@lankalogix.com"), os.getenv("TEST_USER_PASSWORD", "")),
}
MISSING_TEST_PASSWORDS = [role for role, (_, pw) in DEMO.items() if not pw]


@pytest.fixture(scope="session")
def client():
    """One TestClient for the session. Starting the app runs its lifespan,
    which loads the ML models, so this is deliberately not per-test."""
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL is not set; skipping integration tests")
    if MISSING_TEST_PASSWORDS:
        pytest.skip("TEST_SUPER_PASSWORD / TEST_ADMIN_PASSWORD / TEST_USER_PASSWORD not set")
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c


def _login(client, email: str, password: str) -> str | None:
    """Return an access token, completing warehouse selection when the account
    requires it (super admins pick a warehouse before they get a usable token)."""
    resp = client.post("/auth/login", json={"email": email, "password": password})
    if resp.status_code != 200:
        return None
    body = resp.json()
    token = body.get("access_token")
    if not token and body.get("requires_warehouse_selection"):
        chosen = body["warehouses"][0]
        resp2 = client.post(
            "/auth/login/select-warehouse",
            json={"selection_token": body["selection_token"], "warehouse_id": chosen["id"]},
        )
        token = resp2.json().get("access_token") if resp2.status_code == 200 else None
    return token


@pytest.fixture(scope="session")
def tokens(client):
    out = {}
    for role, (email, pw) in DEMO.items():
        token = _login(client, email, pw)
        if not token:
            pytest.skip(f"demo {role} account unavailable; skipping integration tests")
        out[role] = token
    return out


@pytest.fixture
def auth(tokens):
    """auth("admin") -> Authorization header for that role."""
    def _headers(role: str = "admin") -> dict:
        return {"Authorization": f"Bearer {tokens[role]}"}
    return _headers


@pytest.fixture(scope="session")
def db():
    from app.db import SessionLocal
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
