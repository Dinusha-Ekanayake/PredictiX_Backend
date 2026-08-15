"""Who can call what.

Each case here corresponds to a route whose gate was wrong at some point:
unauthenticated model inference, unscoped preference reads, and endpoints that
must stay public because they run before login.
"""
import pytest

pytestmark = pytest.mark.integration


# ── endpoints that must stay reachable without a token ────────────────────

def test_warmup_is_public(client):
    """The login page calls this before the user has a token."""
    resp = client.post("/warmup/inference-space")
    assert resp.status_code == 200
    assert "warmed" in resp.json()


def test_ticket_summary_health_is_public(client):
    assert client.get("/ticket-summaries/health").status_code == 200


# ── endpoints that must reject anonymous callers ──────────────────────────

@pytest.mark.parametrize("path", ["/chatbot/ask", "/ticket-summaries/generate"])
def test_rejects_anonymous(client, path):
    assert client.post(path, json={}).status_code in (401, 403)


def test_removed_debug_route_is_gone(client):
    assert client.get("/auth/test").status_code == 404


# ── model inference is admin-only ─────────────────────────────────────────

INFERENCE_ROUTES = [
    "/predictions/classification",
    "/predictions/regression",
    "/predictions/health-score",
    "/predictions/full",
    "/tickets/categorize",
    "/tickets/prioritize",
]


@pytest.mark.parametrize("path", INFERENCE_ROUTES)
def test_regular_user_cannot_run_inference(client, auth, path):
    """These burn external quota, so they are not open to every account."""
    assert client.post(path, headers=auth("user"), json={}).status_code == 403


@pytest.mark.parametrize("path", INFERENCE_ROUTES)
def test_admin_can_reach_inference(client, auth, path):
    """403 would mean the gate is wrong; 4xx-for-bad-body is fine."""
    assert client.post(path, headers=auth("admin"), json={}).status_code != 403


# ── notification preferences are scoped to the caller ─────────────────────

OTHER_USER = "00000000-0000-0000-0000-000000000000"


def test_user_cannot_create_preferences_for_someone_else(client, auth):
    resp = client.post(
        "/notification-preferences/",
        headers=auth("user"),
        json={"user_id": OTHER_USER, "channel": "email",
              "notification_type": "ticket_created", "enabled": True},
    )
    assert resp.status_code == 403


def test_user_cannot_read_another_users_preferences(client, auth):
    """The query string must not widen what a non-admin can see."""
    resp = client.get(f"/notification-preferences/?user_id={OTHER_USER}", headers=auth("user"))
    assert resp.status_code == 200
    assert resp.json() == []


def test_user_cannot_delete_a_preference_they_do_not_own(client, auth):
    resp = client.delete(f"/notification-preferences/{OTHER_USER}", headers=auth("user"))
    assert resp.status_code == 404


def test_invalid_notification_type_is_a_client_error(client, auth):
    """A value outside the enum must not reach the INSERT and 500 there."""
    me = client.get("/profiles/me", headers=auth("user")).json()
    resp = client.post(
        "/notification-preferences/",
        headers=auth("user"),
        json={"user_id": me["id"], "channel": "email",
              "notification_type": "not_a_real_type", "enabled": True},
    )
    assert resp.status_code == 422
