"""7.3.1 Authentication and Access Control (AU-01 .. AU-08)."""
import pytest

from .conftest import DEMO, case, frontend_only

pytestmark = pytest.mark.functional


@case("AU-01", "Login with valid credentials", "User is authenticated successfully")
def test_au_01_valid_login(client):
    email, pw = DEMO["admin"]
    r = client.post("/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, f"login returned {r.status_code}"
    assert r.json().get("access_token"), "no access_token in the response"


@case("AU-02", "Login with incorrect password", "Login is rejected with an error")
def test_au_02_wrong_password(client):
    email, _ = DEMO["admin"]
    r = client.post("/auth/login", json={"email": email, "password": "not-the-password"})
    assert r.status_code in (400, 401), f"expected a rejection, got {r.status_code}"
    assert "access_token" not in r.json(), "a token was issued for a bad password"


@case("AU-03", "Access protected API without JWT", "Request is rejected")
def test_au_03_no_token(client):
    for path in ("/assets/", "/users/", "/tickets/", "/notifications"):
        r = client.get(path)
        assert r.status_code in (401, 403), f"{path} served an anonymous caller ({r.status_code})"


@case("AU-04", "Standard User attempts Admin operation", "Access is denied")
def test_au_04_user_cannot_do_admin_work(client, auth):
    payload = {
        "id": "x", "firstName": "T", "lastName": "T", "name": "T",
        "email": "t@example.com", "address": "-", "contactNumber": "-",
        "warehouse": "-", "role": "user", "department": "-", "status": "active",
    }
    r = client.post("/users/", json=payload, headers=auth("user"))
    assert r.status_code == 403, f"standard user reached user creation ({r.status_code})"


@case("AU-05", "Admin accesses assigned warehouse", "Access is permitted")
def test_au_05_admin_sees_own_warehouse(client, auth, ctx):
    r = client.get(f"/assets/{ctx['asset_in']}", headers=auth("admin"))
    assert r.status_code == 200, f"admin denied their own warehouse ({r.status_code})"


@case("AU-06", "Admin attempts access to another warehouse", "Access is denied")
def test_au_06_admin_blocked_from_other_warehouse(client, auth, ctx):
    r = client.get(f"/assets/{ctx['asset_out']}", headers=auth("admin"))
    assert r.status_code in (403, 404), (
        f"admin read an asset outside their warehouse ({r.status_code})")


@case("AU-07", "Super Admin selects a warehouse", "Selected warehouse context is applied")
def test_au_07_super_admin_warehouse_selection(client):
    email, pw = DEMO["super"]
    r = client.post("/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200
    body = r.json()
    assert body.get("requires_warehouse_selection"), (
        "super admin was issued a token without choosing a warehouse")
    assert body.get("warehouses"), "no warehouses offered for selection"

    chosen = body["warehouses"][0]
    r2 = client.post("/auth/login/select-warehouse", json={
        "selection_token": body["selection_token"], "warehouse_id": chosen["id"]})
    assert r2.status_code == 200, f"warehouse selection failed ({r2.status_code})"
    token = r2.json().get("access_token")
    assert token, "no token issued after selecting a warehouse"

    me = client.get("/profiles/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert str(me.json().get("warehouse_id")) == str(chosen["id"]), (
        "the token does not carry the selected warehouse")


@case("AU-08", "Logout from authenticated session", "Session is terminated correctly")
@frontend_only(
    "authentication is a stateless JWT; the API exposes no logout route and "
    "holds no server-side session to terminate. Logout is the client "
    "discarding the token, covered by the frontend suite.")
def test_au_08_logout():
    raise AssertionError("unreachable")
