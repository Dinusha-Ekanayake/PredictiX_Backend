"""Fixtures and reporting for the module-by-module functional suite.

Each test carries the case id, title and expected result from the test plan
via the ``case`` marker. A reporting plugin collects those into
``functional_results.json`` so scripts/run_functional_tests.py can print the
same table that appears in the report.

Three outcomes are possible and they mean different things:

  PASS      the expectation held against the live system
  FAIL      the expectation did not hold, a real defect, not a broken test
  FRONTEND  the behaviour has no server-side surface to assert, so the backend
            suite cannot judge it and does not claim to

A case is never marked PASS because it was hard to test.
"""
import json
import os
import uuid
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv()

DEMO = {
    "super": ("demosuperadmin@lankalogix.com", "superadmin@123"),
    "admin": ("demoadmincolombo.adm@lankalogix.com", "demoadmin@123"),
    "user": ("demousercolombo.adm@lankalogix.com", "demouser@123"),
}

# Anything this suite creates carries the marker so a failed cleanup is
# identifiable and never mistaken for real fleet data.
FIXTURE_TAG = "ZZFUNCTEST"


def case(cid: str, title: str, expected: str):
    """Attach test-plan metadata to a functional test."""
    return pytest.mark.case(cid=cid, title=title, expected=expected)


def frontend_only(reason: str):
    """Mark a case whose behaviour lives entirely in the browser.

    Skipping is honest here: the backend has nothing to assert. The runner
    renders these as FRONTEND, and the frontend suite covers them separately.
    """
    return pytest.mark.skip(reason=f"FRONTEND: {reason}")


# ── fixtures ────────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def client():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL is not set")
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c


def _login(client, email: str, password: str) -> str | None:
    resp = client.post("/auth/login", json={"email": email, "password": password})
    if resp.status_code != 200:
        return None
    body = resp.json()
    token = body.get("access_token")
    if not token and body.get("requires_warehouse_selection"):
        chosen = body["warehouses"][0]
        r2 = client.post(
            "/auth/login/select-warehouse",
            json={"selection_token": body["selection_token"],
                  "warehouse_id": chosen["id"]},
        )
        token = r2.json().get("access_token") if r2.status_code == 200 else None
    return token


@pytest.fixture(scope="session")
def tokens(client):
    out = {}
    for role, (email, pw) in DEMO.items():
        t = _login(client, email, pw)
        if not t:
            pytest.skip(f"demo {role} account unavailable")
        out[role] = t
    return out


@pytest.fixture
def auth(tokens):
    def _h(role: str = "admin") -> dict:
        return {"Authorization": f"Bearer {tokens[role]}"}
    return _h


@pytest.fixture(scope="session")
def db():
    from app.db import SessionLocal
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture(scope="session")
def ctx(client, tokens, db):
    """Ids the tests need repeatedly: the admin's own warehouse, an asset in
    it, and an asset outside it. Resolved once from live data so the suite
    does not depend on hardcoded uuids."""
    from sqlalchemy import text

    h = {"Authorization": f"Bearer {tokens['admin']}"}
    me = client.get("/profiles/me", headers=h)
    if me.status_code != 200:
        pytest.skip("cannot resolve the demo admin profile")
    wh = me.json().get("warehouse_id")

    inside = db.execute(text(
        "SELECT id FROM assets WHERE warehouse_id = :w ORDER BY asset_code LIMIT 1"
    ), {"w": wh}).scalar()
    outside = db.execute(text(
        "SELECT id FROM assets WHERE warehouse_id <> :w ORDER BY asset_code LIMIT 1"
    ), {"w": wh}).scalar()
    other_wh = db.execute(text(
        "SELECT id FROM warehouses WHERE id <> :w LIMIT 1"
    ), {"w": wh}).scalar()

    if not (wh and inside and outside):
        pytest.skip("fleet data does not span two warehouses")

    return {
        "warehouse_id": str(wh),
        "other_warehouse_id": str(other_wh),
        "asset_in": str(inside),
        "asset_out": str(outside),
        "admin_profile_id": me.json().get("id"),
    }


@pytest.fixture
def unique():
    """Short unique suffix for rows a test creates."""
    return lambda: f"{FIXTURE_TAG}{uuid.uuid4().hex[:8]}"


@pytest.fixture
def requires_hf():
    """Skip a case that cannot be judged with Hugging Face inference disabled.

    app/main.py defaults HF_HUB_OFFLINE to 1, and .env additionally sets
    DISABLE_HF_MODELS and TRANSFORMERS_OFFLINE, so the summary services fall
    straight through to their deterministic template. Asserting "a summary came
    back" would then pass on template text and report a working model that was
    never called.
    """
    disabled = (
        os.getenv("DISABLE_HF_MODELS", "").lower() in ("1", "true", "yes")
        or os.getenv("HF_HUB_OFFLINE", "1") not in ("0", "false", "")
        or os.getenv("TRANSFORMERS_OFFLINE", "").lower() in ("1", "true", "yes")
    )
    if disabled:
        pytest.skip("Hugging Face inference is disabled in this environment "
                    "(HF_HUB_OFFLINE / DISABLE_HF_MODELS), so only the template "
                    "fallback would be exercised")


@pytest.fixture
def requires_llm():
    """Skip a case that cannot be judged without a working Groq key.

    Without GROQ_API_KEY the agent still answers, but from its non-LLM
    fallback path. A test that only checks "an answer came back" then passes
    on that fallback and reports a working chatbot when none was exercised,
    which is worse than reporting nothing. Skipping says so plainly.
    """
    if not os.getenv("GROQ_API_KEY"):
        pytest.skip("GROQ_API_KEY is not configured; only the fallback path "
                    "would be exercised, so this case cannot be judged")


# ── reporting plugin ────────────────────────────────────────────────────
_COLLECTED: dict[str, dict] = {}


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "case(cid, title, expected): functional test-plan metadata")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()

    marker = item.get_closest_marker("case")
    if marker is None:
        return

    cid = marker.kwargs.get("cid", item.name)
    entry = _COLLECTED.setdefault(cid, {
        "cid": cid,
        "title": marker.kwargs.get("title", ""),
        "expected": marker.kwargs.get("expected", ""),
        "status": "PASS",
        "detail": "",
        "nodeid": item.nodeid,
    })

    if rep.when == "call" or (rep.when == "setup" and rep.outcome != "passed"):
        if rep.outcome == "failed":
            entry["status"] = "FAIL"
            entry["detail"] = _short_reason(rep)
        elif rep.outcome == "skipped":
            reason = _skip_reason(rep)
            if reason.startswith("FRONTEND:"):
                entry["status"] = "FRONTEND"
                entry["detail"] = reason[len("FRONTEND:"):].strip()
            else:
                entry["status"] = "SKIP"
                entry["detail"] = reason


def _short_reason(rep) -> str:
    text = str(getattr(rep, "longrepr", "") or "")
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("E "):
            return s[2:].strip()[:200]
    return text.strip().splitlines()[-1][:200] if text.strip() else "failed"


def _skip_reason(rep) -> str:
    lr = getattr(rep, "longrepr", None)
    if isinstance(lr, tuple) and len(lr) == 3:
        return str(lr[2]).replace("Skipped: ", "")
    return str(lr or "skipped")


def pytest_sessionfinish(session, exitstatus):
    if not _COLLECTED:
        return
    dest = Path(session.config.rootpath) / "functional_results.json"
    rows = sorted(_COLLECTED.values(), key=lambda r: r["cid"])
    dest.write_text(json.dumps(rows, indent=1), encoding="utf-8")
