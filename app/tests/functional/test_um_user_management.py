"""7.3.2 User Management (UM-01 .. UM-07).

Creating a user also creates a Supabase auth user, and deleting one removes
both. Every test that creates a user deletes it in a finally block, and the
email carries the fixture tag so a leaked row is identifiable.
"""
import pytest

from .conftest import case

pytestmark = pytest.mark.functional


def _payload(tag: str, warehouse_name: str, role: str = "user") -> dict:
    return {
        "id": tag,
        "firstName": "Functional",
        "lastName": "Fixture",
        "name": "Functional Fixture",
        "email": f"{tag.lower()}@functest.invalid",
        "address": "Test address",
        "contactNumber": "0000000000",
        "warehouse": warehouse_name,
        "role": role,
        "department": "",
        "status": "active",
        "password": "FuncTest@12345",
    }


@pytest.fixture
def warehouse_name(client, auth, ctx):
    r = client.get(f"/warehouses/{ctx['warehouse_id']}", headers=auth("admin"))
    if r.status_code != 200:
        pytest.skip("cannot resolve the admin's warehouse name")
    return r.json().get("name")


@case("UM-01", "Create a user with valid information", "User is created successfully")
def test_um_01_create_user(client, auth, unique, warehouse_name):
    tag = unique()
    created_id = None
    try:
        r = client.post("/users/", json=_payload(tag, warehouse_name), headers=auth("admin"))
        assert r.status_code in (200, 201), f"creation failed ({r.status_code}): {r.text[:200]}"
        body = r.json()
        created_id = body.get("id")
        assert created_id, "no id returned for the created user"
        assert body.get("email", "").lower() == f"{tag.lower()}@functest.invalid"
    finally:
        if created_id:
            client.delete(f"/users/{created_id}", headers=auth("admin"))


@case("UM-02", "Create a user using an existing email", "Duplicate account is rejected")
def test_um_02_duplicate_email_rejected(client, auth, unique, warehouse_name):
    tag = unique()
    first_id = None
    second_id = None
    try:
        r1 = client.post("/users/", json=_payload(tag, warehouse_name), headers=auth("admin"))
        assert r1.status_code in (200, 201), "could not create the first user"
        first_id = r1.json().get("id")

        dup = _payload(unique(), warehouse_name)
        dup["email"] = f"{tag.lower()}@functest.invalid"
        r2 = client.post("/users/", json=dup, headers=auth("admin"))
        second_id = r2.json().get("id") if r2.status_code in (200, 201) else None
        assert r2.status_code in (400, 409, 422), (
            f"a duplicate email was accepted ({r2.status_code})")
    finally:
        for uid in (second_id, first_id):
            if uid:
                client.delete(f"/users/{uid}", headers=auth("admin"))


@case("UM-03", "Update permitted user information", "Changes are stored correctly")
def test_um_03_update_user(client, auth, unique, warehouse_name):
    tag = unique()
    uid = None
    try:
        r = client.post("/users/", json=_payload(tag, warehouse_name), headers=auth("admin"))
        assert r.status_code in (200, 201), "setup: could not create a user"
        uid = r.json()["id"]

        upd = client.put(f"/users/{uid}", json={"name": "Renamed Fixture"},
                         headers=auth("admin"))
        assert upd.status_code == 200, f"update failed ({upd.status_code})"

        again = client.get("/users/", headers=auth("admin"))
        assert again.status_code == 200
        rows = again.json()
        rows = rows.get("items", rows) if isinstance(rows, dict) else rows
        mine = [u for u in rows if str(u.get("id")) == str(uid)]
        assert mine, "the updated user is not in the listing"
        assert mine[0].get("name") == "Renamed Fixture", "the change was not persisted"
    finally:
        if uid:
            client.delete(f"/users/{uid}", headers=auth("admin"))


@case("UM-04", "Change user status", "Updated status is applied")
def test_um_04_change_status(client, auth, unique, warehouse_name, db):
    from sqlalchemy import text

    tag = unique()
    uid = None
    try:
        r = client.post("/users/", json=_payload(tag, warehouse_name), headers=auth("admin"))
        assert r.status_code in (200, 201), "setup: could not create a user"
        uid = r.json()["id"]

        upd = client.put(f"/users/{uid}", json={"status": "inactive"}, headers=auth("admin"))
        assert upd.status_code == 200, f"status update failed ({upd.status_code})"

        db.rollback()  # see the committed value, not this session's snapshot
        stored = db.execute(text("SELECT status::text FROM profiles WHERE id = :i"),
                            {"i": uid}).scalar()
        assert stored == "inactive", f"status stored as {stored!r}, expected 'inactive'"
    finally:
        if uid:
            client.delete(f"/users/{uid}", headers=auth("admin"))


@case("UM-05", "View users within assigned warehouse", "Only permitted users are returned")
def test_um_05_listing_is_warehouse_scoped(client, auth, ctx, db):
    from sqlalchemy import text

    r = client.get("/users/", headers=auth("admin"))
    assert r.status_code == 200, f"listing failed ({r.status_code})"
    rows = r.json()
    rows = rows.get("items", rows) if isinstance(rows, dict) else rows
    assert rows, "no users returned at all"

    ids = [str(u["id"]) for u in rows if u.get("id")]
    leaked = db.execute(text("""
        SELECT count(*) FROM profiles
        WHERE id = ANY(CAST(:ids AS uuid[]))
          AND warehouse_id IS NOT NULL
          AND warehouse_id <> CAST(:w AS uuid)
    """), {"ids": ids, "w": ctx["warehouse_id"]}).scalar()
    assert leaked == 0, f"{leaked} users from another warehouse appeared in the listing"


@case("UM-06", "Standard User attempts user management", "Access is denied")
def test_um_06_standard_user_denied(client, auth, ctx):
    r = client.put(f"/users/{ctx['admin_profile_id']}", json={"name": "hijacked"},
                   headers=auth("user"))
    assert r.status_code == 403, f"standard user reached user update ({r.status_code})"


@case("UM-07", "Super Admin changes warehouse context",
      "Users for the selected warehouse are shown")
def test_um_07_super_admin_context_switch(client, db):
    from sqlalchemy import text
    from .conftest import DEMO

    email, pw = DEMO["super"]
    login = client.post("/auth/login", json={"email": email, "password": pw})
    assert login.status_code == 200
    body = login.json()
    offered = body.get("warehouses") or []
    assert len(offered) >= 2, "super admin sees fewer than two warehouses"

    seen = {}
    for wh in offered[:2]:
        sel = client.post("/auth/login/select-warehouse", json={
            "selection_token": body["selection_token"], "warehouse_id": wh["id"]})
        assert sel.status_code == 200, f"selecting {wh['id']} failed"
        token = sel.json()["access_token"]

        r = client.get("/users/", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, f"listing failed for warehouse {wh['id']}"
        rows = r.json()
        rows = rows.get("items", rows) if isinstance(rows, dict) else rows
        ids = [str(u["id"]) for u in rows if u.get("id")]

        leaked = db.execute(text("""
            SELECT count(*) FROM profiles
            WHERE id = ANY(CAST(:ids AS uuid[]))
              AND warehouse_id IS NOT NULL
              AND warehouse_id <> CAST(:w AS uuid)
        """), {"ids": ids, "w": wh["id"]}).scalar()
        assert leaked == 0, (
            f"{leaked} users outside warehouse {wh['name']} were returned "
            "after selecting it")
        seen[wh["id"]] = set(ids)

    a, b = list(seen.values())
    assert a != b, "both warehouse contexts returned an identical user set"
