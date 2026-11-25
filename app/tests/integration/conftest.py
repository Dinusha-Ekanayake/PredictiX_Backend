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
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL is not set")
    from app.db import SessionLocal
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ── Read-only fixtures that need no passwords ───────────────────────────────
# Tokens are minted for real profiles with the API's own signing key, so the
# authorization, sandbox and chatbot suites run wherever DATABASE_URL and
# JWT_SECRET are set. Nothing here writes to the database.

@pytest.fixture(scope="session")
def api():
    """A TestClient that does not run the app's startup hook (which writes the
    model registry), for read-only and refused-before-write requests."""
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL is not set; skipping integration tests")
    os.environ.setdefault("SCHEDULER_ENABLED", "false")
    from fastapi.testclient import TestClient
    from app.main import app

    return TestClient(app)


@pytest.fixture(scope="session")
def world(api):
    """Real ids from the admin's own warehouse and from another one."""
    from sqlalchemy import text
    from app.db.session import engine

    with engine.connect() as c:
        c.execute(text("SET TRANSACTION READ ONLY"))
        admin = c.execute(text(
            "SELECT id::text, email, warehouse_id::text FROM profiles "
            "WHERE role='admin' AND status='active' AND warehouse_id IS NOT NULL LIMIT 1")).fetchone()
        if admin is None:
            pytest.skip("no active admin with a warehouse")
        wh = admin[2]
        one = lambda sql: c.execute(text(sql), {"w": wh}).scalar()  # noqa: E731
        data = {
            "admin": {"id": admin[0], "email": admin[1], "wh": wh},
            "user_same": one("SELECT id::text FROM profiles WHERE role='user' AND status='active' AND warehouse_id::text=:w LIMIT 1"),
            "user_other": one("SELECT id::text FROM profiles WHERE role='user' AND warehouse_id::text<>:w LIMIT 1"),
            "super": c.execute(text("SELECT id::text, email FROM profiles WHERE role='super_admin' AND status='active' LIMIT 1")).fetchone(),
            "ticket_same": one("SELECT id::text FROM tickets WHERE warehouse_id::text=:w LIMIT 1"),
            "ticket_other": one("SELECT id::text FROM tickets WHERE warehouse_id::text<>:w LIMIT 1"),
            "asset_same": one("SELECT id::text FROM assets WHERE warehouse_id::text=:w LIMIT 1"),
            "asset_other": one("SELECT id::text FROM assets WHERE warehouse_id::text<>:w LIMIT 1"),
            "event_other": one("SELECT m.id::text FROM maintenance_events m JOIN assets a ON a.id=m.asset_id WHERE a.warehouse_id::text<>:w LIMIT 1"),
        }
        user = c.execute(text("SELECT id::text, email, warehouse_id::text FROM profiles WHERE id::text=:u"), {"u": data["user_same"]}).fetchone()
        data["user"] = {"id": user[0], "email": user[1], "wh": user[2]}
        c.rollback()
    return data


@pytest.fixture(scope="session")
def bearer(world):
    """bearer(role) -> Authorization header for a real profile of that role."""
    from app.routers.auth import _create_selection_token, _create_token

    def _headers(role: str) -> dict:
        if role == "admin":
            a = world["admin"]
            token = _create_token(a["id"], a["email"], "admin", warehouse_id=a["wh"])
        elif role == "user":
            u = world["user"]
            token = _create_token(u["id"], u["email"], "user")
        elif role == "super":
            s = world["super"]
            token = _create_token(s[0], s[1], "super_admin", warehouse_id=world["admin"]["wh"])
        elif role == "selection":
            s = world["super"]
            token = _create_selection_token(s[0], s[1], "x")
        else:
            raise ValueError(role)
        return {"Authorization": f"Bearer {token}"}

    return _headers
