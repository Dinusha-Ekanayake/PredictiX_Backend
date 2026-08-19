"""7.3.9 Notifications, Profile and Settings (NS-01 .. NS-08)."""
import pytest

from .conftest import case, frontend_only

pytestmark = pytest.mark.functional


def _rows(payload):
    if isinstance(payload, dict):
        for k in ("items", "notifications", "data", "results"):
            if k in payload:
                return payload[k]
    return payload


@case("NS-01", "Trigger high risk asset notification",
      "Notification is created for relevant user")
def test_ns_01_high_risk_notification(client, auth, ctx, db):
    from sqlalchemy import text

    before = db.execute(text("""
        SELECT count(*) FROM notifications
        WHERE user_id = CAST(:u AS uuid) AND type = 'high_risk_asset'
    """), {"u": ctx["admin_profile_id"]}).scalar()

    r = client.post("/notifications", json={
        "user_id": ctx["admin_profile_id"],
        "type": "high_risk_asset",
        "title": "Functional test high risk asset",
        "message": "Raised by the functional suite.",
        "related_asset_id": ctx["asset_in"],
    }, headers=auth("admin"))
    assert r.status_code in (200, 201), f"could not raise a notification ({r.status_code})"
    nid = r.json().get("id")

    try:
        db.rollback()
        after = db.execute(text("""
            SELECT count(*) FROM notifications
            WHERE user_id = CAST(:u AS uuid) AND type = 'high_risk_asset'
        """), {"u": ctx["admin_profile_id"]}).scalar()
        assert after == before + 1, "the notification was not stored for the user"
    finally:
        if nid:
            client.delete(f"/notifications/{nid}", headers=auth("admin"))


@case("NS-02", "Update maintenance ticket", "Appropriate notification is generated")
def test_ns_02_ticket_notification(client, auth, ctx, unique, monkeypatch):
    """New-ticket notification is delivered by email and is not written to the
    notifications table, so this asserts the dispatch fires rather than
    counting rows that were never meant to appear."""
    from app.services.notification_service import NotificationService

    sent: list[tuple] = []
    original = NotificationService.send_email

    def spy(recipients, subject, html_body, *a, **kw):
        sent.append((recipients, subject))
        return True

    monkeypatch.setattr(NotificationService, "send_email", staticmethod(spy))

    tid = None
    try:
        created = client.post("/tickets/", json={
            "title": f"{unique()} notification probe",
            "description": "Raised by the functional suite to check notification fan-out.",
            "created_by": ctx["admin_profile_id"],
            "asset_id": ctx["asset_in"],
            "warehouse_id": ctx["warehouse_id"],
        }, headers=auth("admin"))
        assert created.status_code in (200, 201), (
            f"setup: ticket creation failed ({created.status_code}): {created.text[:160]}")
        tid = created.json()["id"]

        assert sent, "creating a ticket dispatched no notification"
        recipients = [r for group, _ in sent for r in (group or [])]
        assert recipients, "the notification was dispatched with no recipients"
    finally:
        monkeypatch.setattr(NotificationService, "send_email", original)
        if tid:
            client.delete(f"/tickets/{tid}", headers=auth("admin"))


@case("NS-03", "Mark notification as read", "Notification status is updated")
def test_ns_03_mark_read(client, auth, ctx, db):
    from sqlalchemy import text

    r = client.post("/notifications", json={
        "user_id": ctx["admin_profile_id"],
        "type": "system",
        "title": "Functional test read-state",
        "message": "Raised by the functional suite.",
    }, headers=auth("admin"))
    assert r.status_code in (200, 201), f"setup: could not raise a notification ({r.status_code})"
    nid = r.json()["id"]

    try:
        upd = client.put(f"/notifications/{nid}/mark-read", headers=auth("admin"))
        assert upd.status_code == 200, f"mark-read failed ({upd.status_code})"

        db.rollback()
        row = db.execute(text(
            "SELECT status::text, read_at FROM notifications WHERE id = CAST(:i AS uuid)"
        ), {"i": nid}).first()
        assert row and row[0] == "read", f"status is {row[0] if row else None!r}, expected 'read'"
        assert row[1] is not None, "read_at was not stamped"
    finally:
        client.delete(f"/notifications/{nid}", headers=auth("admin"))


@case("NS-04", "User views notifications", "Only permitted notifications are returned")
def test_ns_04_notifications_are_own_only(client, auth, db):
    from sqlalchemy import text

    me = client.get("/profiles/me", headers=auth("user"))
    assert me.status_code == 200
    uid = me.json()["id"]

    # Seed one so the scoping check always has something to verify against
    # rather than passing vacuously on an empty inbox.
    seeded = client.post("/notifications", json={
        "user_id": uid,
        "type": "system",
        "title": "Functional test scoping probe",
        "message": "Raised by the functional suite.",
    }, headers=auth("admin"))
    assert seeded.status_code in (200, 201), (
        f"setup: could not seed a notification ({seeded.status_code}): "
        f"{seeded.text[:160]}")
    seeded_id = seeded.json().get("id")
    assert str(seeded.json().get("user_id")) == str(uid), (
        "setup: the notification was created for the caller rather than the "
        "requested user_id")

    try:
        r = client.get("/notifications", headers=auth("user"))
        assert r.status_code == 200, f"notification listing failed ({r.status_code})"
        rows = _rows(r.json())

        ids = [str(n["id"]) for n in rows if n.get("id")]
        assert seeded_id in ids, (
            "the notification raised for this user is missing from their listing")
        leaked = db.execute(text("""
            SELECT count(*) FROM notifications
            WHERE id = ANY(CAST(:ids AS uuid[])) AND user_id <> CAST(:u AS uuid)
        """), {"ids": ids, "u": uid}).scalar()
        assert leaked == 0, (
            f"{leaked} notifications belonging to other users were returned")
    finally:
        if seeded_id:
            client.delete(f"/notifications/{seeded_id}", headers=auth("admin"))


@case("NS-05", "Open profile page", "Current profile information is displayed")
def test_ns_05_profile(client, auth):
    r = client.get("/profiles/me", headers=auth("admin"))
    assert r.status_code == 200, f"profile failed ({r.status_code})"
    body = r.json()
    for field in ("id", "email", "role"):
        assert body.get(field), f"profile is missing {field}"


@case("NS-06", "Update permitted profile details", "Changes are saved")
def test_ns_06_update_profile(client, auth):
    # The payload key is contactNumber; the profile reads back as phone.
    original = client.get("/profiles/me", headers=auth("admin")).json()
    old_phone = original.get("phone") or original.get("contactNumber")
    try:
        upd = client.put("/profiles/me", json={"contactNumber": "0771234567"},
                         headers=auth("admin"))
        assert upd.status_code == 200, f"profile update failed ({upd.status_code}): {upd.text[:160]}"
        again = client.get("/profiles/me", headers=auth("admin")).json()
        stored = again.get("phone") or again.get("contactNumber")
        assert stored == "0771234567", f"the change was not persisted (stored {stored!r})"
    finally:
        client.put("/profiles/me", json={"contactNumber": old_phone}, headers=auth("admin"))


@case("NS-07", "Switch light/dark theme", "Selected appearance is applied")
@frontend_only("theme is a client-side preference; no server state is involved")
def test_ns_07_theme():
    raise AssertionError("unreachable")


@case("NS-08", "Navigate between main application areas", "Selected module loads correctly")
@frontend_only("routing is handled by the Next.js app router; no API surface to assert")
def test_ns_08_navigation():
    raise AssertionError("unreachable")
