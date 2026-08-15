"""Assigning an asset to a user.

The rules under test: only admins may assign, the assignee must belong to the
asset's warehouse and be active, and every change must leave an audit trail.

The happy-path test mutates real data, so it captures the asset's original
assignee first and restores it in a finally block.
"""
import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


@pytest.fixture
def colombo_asset(db):
    """An unassigned Colombo asset, so the test starts from a known state."""
    row = db.execute(text("""
        SELECT a.id, a.asset_code, a.assigned_to
        FROM assets a JOIN warehouses w ON w.id = a.warehouse_id
        WHERE a.assigned_to IS NULL AND w.name LIKE '%Colombo%'
        LIMIT 1
    """)).fetchone()
    if not row:
        pytest.skip("no unassigned Colombo asset available")
    return row


@pytest.fixture
def colombo_user(db):
    row = db.execute(text("""
        SELECT p.id, p.full_name
        FROM profiles p JOIN warehouses w ON w.id = p.warehouse_id
        WHERE w.name LIKE '%Colombo%' AND p.status = 'active' AND p.role = 'user'
        LIMIT 1
    """)).fetchone()
    if not row:
        pytest.skip("no active Colombo user available")
    return row


@pytest.fixture
def other_warehouse_user(db):
    row = db.execute(text("""
        SELECT p.id FROM profiles p JOIN warehouses w ON w.id = p.warehouse_id
        WHERE w.name NOT LIKE '%Colombo%' AND p.status = 'active'
        LIMIT 1
    """)).fetchone()
    if not row:
        pytest.skip("no user outside Colombo available")
    return row


# ── authorisation ─────────────────────────────────────────────────────────

def test_regular_user_cannot_assign_an_asset(client, auth, colombo_asset, colombo_user):
    resp = client.patch(
        f"/assets/{colombo_asset.id}/assign?assigned_to={colombo_user.id}",
        headers=auth("user"),
    )
    assert resp.status_code == 403


def test_regular_user_cannot_unassign_an_asset(client, auth, colombo_asset):
    resp = client.patch(f"/assets/{colombo_asset.id}/assign", headers=auth("user"))
    assert resp.status_code == 403


def test_anonymous_caller_is_rejected(client, colombo_asset, colombo_user):
    resp = client.patch(
        f"/assets/{colombo_asset.id}/assign?assigned_to={colombo_user.id}"
    )
    assert resp.status_code in (401, 403)


# ── validation ────────────────────────────────────────────────────────────

def test_cannot_assign_to_a_user_in_another_warehouse(
    client, auth, colombo_asset, other_warehouse_user
):
    """An asset can only be worked on by someone at its own site."""
    resp = client.patch(
        f"/assets/{colombo_asset.id}/assign?assigned_to={other_warehouse_user.id}",
        headers=auth("admin"),
    )
    assert resp.status_code == 422
    assert "warehouse" in resp.json()["detail"].lower()


def test_cannot_assign_to_a_user_that_does_not_exist(client, auth, colombo_asset):
    resp = client.patch(
        f"/assets/{colombo_asset.id}/assign"
        f"?assigned_to=00000000-0000-0000-0000-000000000000",
        headers=auth("admin"),
    )
    assert resp.status_code == 404


def test_cannot_assign_an_asset_that_does_not_exist(client, auth, colombo_user):
    resp = client.patch(
        f"/assets/00000000-0000-0000-0000-000000000000/assign"
        f"?assigned_to={colombo_user.id}",
        headers=auth("admin"),
    )
    assert resp.status_code == 404


# ── happy path, with restoration ──────────────────────────────────────────

def test_admin_can_assign_and_unassign_leaving_an_audit_trail(
    client, auth, db, colombo_asset, colombo_user
):
    asset_id, user_id = str(colombo_asset.id), str(colombo_user.id)
    try:
        resp = client.patch(
            f"/assets/{asset_id}/assign?assigned_to={user_id}&notes=pytest",
            headers=auth("admin"),
        )
        assert resp.status_code == 200
        assert str(resp.json()["assigned_to"]) == user_id

        db.expire_all()
        row = db.execute(text("""
            SELECT user_id, is_active, assigned_by, notes
            FROM asset_assignments WHERE asset_id = :a
            ORDER BY assigned_at DESC LIMIT 1
        """), {"a": asset_id}).fetchone()
        assert row is not None, "assignment history was not written"
        assert str(row.user_id) == user_id
        assert row.is_active is True
        assert row.assigned_by is not None, "assigned_by must come from the session"
        assert row.notes == "pytest"

        # Unassigning closes the open history row rather than deleting it.
        resp = client.patch(f"/assets/{asset_id}/assign", headers=auth("admin"))
        assert resp.status_code == 200
        assert resp.json()["assigned_to"] is None

        db.expire_all()
        row = db.execute(text("""
            SELECT is_active, unassigned_at FROM asset_assignments
            WHERE asset_id = :a ORDER BY assigned_at DESC LIMIT 1
        """), {"a": asset_id}).fetchone()
        assert row.is_active is False
        assert row.unassigned_at is not None
    finally:
        # Restore the asset to the unassigned state the fixture found it in.
        client.patch(f"/assets/{asset_id}/assign", headers=auth("admin"))
