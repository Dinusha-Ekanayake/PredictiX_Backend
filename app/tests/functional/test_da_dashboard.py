"""7.3.6 Dashboard and Analytics (DA-01 .. DA-08)."""
import pytest

from .conftest import case, frontend_only

pytestmark = pytest.mark.functional


@case("DA-01", "Open Dashboard", "Overall operational information is displayed")
def test_da_01_dashboard_summary(client, auth):
    r = client.get("/admin-dashboard/summary", headers=auth("admin"))
    assert r.status_code == 200, f"dashboard summary failed ({r.status_code})"
    body = r.json()
    assert isinstance(body, dict) and body, "empty dashboard payload"


@case("DA-02", "Open Assets analytical view", "Asset related insights are displayed")
def test_da_02_asset_analytics(client, auth, ctx, db):
    from sqlalchemy import text

    r = client.get("/assets/analytics", headers=auth("admin"))
    assert r.status_code == 200, f"asset analytics failed ({r.status_code})"
    body = r.json()
    assert isinstance(body, dict) and body, "empty analytics payload"

    # Any total the view reports must not exceed the admin's own warehouse.
    scoped = db.execute(text(
        "SELECT count(*) FROM assets WHERE warehouse_id = CAST(:w AS uuid)"
    ), {"w": ctx["warehouse_id"]}).scalar()
    for key in ("total", "total_assets", "count"):
        if isinstance(body.get(key), int):
            assert body[key] <= scoped, (
                f"analytics reports {body[key]} assets but the admin's warehouse "
                f"holds {scoped} — the view is not warehouse scoped")
            break


@case("DA-03", "Open Tickets analytical view", "Ticket statistics are displayed")
def test_da_03_ticket_stats(client, auth):
    r = client.get("/tickets/status-counts", headers=auth("admin"))
    assert r.status_code == 200, f"ticket statistics failed ({r.status_code})"
    body = r.json()
    assert body, "empty ticket statistics"


@case("DA-04", "Open Users area with authorized account", "User information is displayed")
def test_da_04_users_area(client, auth):
    r = client.get("/users/", headers=auth("admin"))
    assert r.status_code == 200, f"users area failed ({r.status_code})"
    rows = r.json()
    rows = rows.get("items", rows) if isinstance(rows, dict) else rows
    assert rows, "no users returned"


@case("DA-05", "Open Warehouse area", "Warehouse specific analytics are displayed")
def test_da_05_warehouse_area(client, auth):
    r = client.get("/warehouse-dashboard/summary", headers=auth("admin"))
    assert r.status_code == 200, f"warehouse dashboard failed ({r.status_code})"
    assert r.json(), "empty warehouse dashboard payload"


@case("DA-06", "Apply available dashboard filters", "KPIs and charts update accordingly")
def test_da_06_filters_change_results(client, auth):
    a = client.get("/assets/", params={"status": "active", "limit": 100},
                   headers=auth("admin"))
    b = client.get("/assets/", params={"status": "under_maintenance", "limit": 100},
                   headers=auth("admin"))
    assert a.status_code == 200 and b.status_code == 200, "filtered requests failed"

    def ids(resp):
        rows = resp.json()
        rows = rows.get("items", rows) if isinstance(rows, dict) else rows
        return {x.get("id") for x in rows}

    assert ids(a) != ids(b), "two different status filters returned an identical set"


@case("DA-07", "Refresh after underlying data change", "Updated information is displayed")
def test_da_07_reflects_new_data(client, auth, ctx, unique):
    before = client.get("/assets/count", headers=auth("admin"))
    assert before.status_code == 200, f"count endpoint failed ({before.status_code})"
    start = before.json()
    start = start.get("count", start) if isinstance(start, dict) else start

    aid = None
    try:
        created = client.post("/assets/", json={
            "asset_code": unique(), "warehouse_id": ctx["warehouse_id"],
            "asset_name": "Refresh Fixture",
        }, headers=auth("admin"))
        assert created.status_code in (200, 201), "setup: could not create an asset"
        aid = created.json()["id"]

        after = client.get("/assets/count", headers=auth("admin"))
        now = after.json()
        now = now.get("count", now) if isinstance(now, dict) else now
        assert int(now) == int(start) + 1, (
            f"count went {start} -> {now} after adding one asset; a stale cache "
            "is being served")
    finally:
        if aid:
            client.delete(f"/assets/{aid}", headers=auth("admin"))


@case("DA-08", "Standard User opens restricted analytical function",
      "Restricted controls are hidden or denied")
def test_da_08_restricted_for_standard_user(client, auth):
    r = client.get("/admin-dashboard/summary", headers=auth("user"))
    assert r.status_code in (401, 403), (
        f"a standard user reached the admin dashboard ({r.status_code})")
