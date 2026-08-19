"""7.3.3 Asset Management (AS-01 .. AS-10)."""
import pytest

from .conftest import case

pytestmark = pytest.mark.functional


def _rows(payload):
    """Endpoints return either a bare list or a paginated envelope."""
    if isinstance(payload, dict):
        for key in ("items", "assets", "data", "results"):
            if key in payload:
                return payload[key]
    return payload


@case("AS-01", "Create asset with valid details", "Asset is created successfully")
def test_as_01_create_asset(client, auth, ctx, unique):
    tag = unique()
    aid = None
    try:
        r = client.post("/assets/", json={
            "asset_code": tag,
            "warehouse_id": ctx["warehouse_id"],
            "asset_name": "Functional Fixture Vehicle",
            "asset_type": "vehicle",
        }, headers=auth("admin"))
        assert r.status_code in (200, 201), f"creation failed ({r.status_code}): {r.text[:200]}"
        aid = r.json().get("id")
        assert aid, "no id returned"
        assert r.json().get("asset_code") == tag
    finally:
        if aid:
            client.delete(f"/assets/{aid}", headers=auth("admin"))


@case("AS-02", "Create asset with missing required data", "Validation error is returned")
def test_as_02_missing_required_fields(client, auth, ctx):
    r = client.post("/assets/", json={"warehouse_id": ctx["warehouse_id"]},
                    headers=auth("admin"))
    assert r.status_code == 422, f"expected a validation error, got {r.status_code}"


@case("AS-03", "Update asset details", "Updated information is stored")
def test_as_03_update_asset(client, auth, ctx, unique):
    tag = unique()
    aid = None
    try:
        r = client.post("/assets/", json={
            "asset_code": tag, "warehouse_id": ctx["warehouse_id"],
            "asset_name": "Before Rename",
        }, headers=auth("admin"))
        assert r.status_code in (200, 201), "setup: could not create an asset"
        aid = r.json()["id"]

        upd = client.put(f"/assets/{aid}", json={"asset_name": "After Rename"},
                         headers=auth("admin"))
        assert upd.status_code == 200, f"update failed ({upd.status_code})"

        got = client.get(f"/assets/{aid}", headers=auth("admin"))
        assert got.status_code == 200
        assert got.json().get("asset_name") == "After Rename", "the change was not persisted"
    finally:
        if aid:
            client.delete(f"/assets/{aid}", headers=auth("admin"))


@case("AS-04", "Change asset operational status", "New status is reflected correctly")
def test_as_04_change_status(client, auth, ctx, unique):
    tag = unique()
    aid = None
    try:
        r = client.post("/assets/", json={
            "asset_code": tag, "warehouse_id": ctx["warehouse_id"],
            "asset_name": "Status Fixture",
        }, headers=auth("admin"))
        assert r.status_code in (200, 201), "setup: could not create an asset"
        aid = r.json()["id"]

        # The endpoint declares `status` as a query parameter, not a body field.
        upd = client.patch(f"/assets/{aid}/status", params={"status": "under_maintenance"},
                           headers=auth("admin"))
        assert upd.status_code == 200, f"status change failed ({upd.status_code}): {upd.text[:160]}"

        got = client.get(f"/assets/{aid}", headers=auth("admin"))
        assert got.json().get("status") == "under_maintenance", "status did not persist"
    finally:
        if aid:
            client.delete(f"/assets/{aid}", headers=auth("admin"))


@case("AS-05", "Search for an asset", "Matching assets are displayed")
def test_as_05_search(client, auth, ctx):
    detail = client.get(f"/assets/{ctx['asset_in']}", headers=auth("admin"))
    assert detail.status_code == 200
    code = detail.json()["asset_code"]

    r = client.get("/assets/", params={"search": code}, headers=auth("admin"))
    assert r.status_code == 200, f"search failed ({r.status_code})"
    rows = _rows(r.json())
    assert any(a.get("asset_code") == code for a in rows), (
        f"searching for {code} did not return it")


@case("AS-06", "Apply asset filters", "Correct subset of assets is displayed")
def test_as_06_filter(client, auth):
    r = client.get("/assets/", params={"status": "active", "limit": 50}, headers=auth("admin"))
    assert r.status_code == 200, f"filtered listing failed ({r.status_code})"
    rows = _rows(r.json())
    assert rows, "the active filter returned nothing"
    bad = [a for a in rows if a.get("status") not in (None, "active")]
    assert not bad, f"{len(bad)} rows do not match the requested status filter"


@case("AS-07", "Open an asset detail view", "Asset and maintenance information is shown")
def test_as_07_detail_view(client, auth, ctx):
    r = client.get(f"/assets/{ctx['asset_in']}", headers=auth("admin"))
    assert r.status_code == 200
    body = r.json()
    for field in ("id", "asset_code", "asset_name", "status", "warehouse_id"):
        assert field in body, f"detail response is missing {field}"


@case("AS-08", "View asset maintenance history", "Related maintenance records are displayed")
def test_as_08_maintenance_history(client, auth, ctx, db):
    from sqlalchemy import text

    expected = db.execute(text(
        "SELECT count(*) FROM maintenance_events WHERE asset_id = CAST(:a AS uuid)"
    ), {"a": ctx["asset_in"]}).scalar()

    r = client.get("/maintenance/", params={"asset_id": ctx["asset_in"]}, headers=auth("admin"))
    if r.status_code == 404:
        r = client.get(f"/assets/{ctx['asset_in']}/maintenance", headers=auth("admin"))
    assert r.status_code == 200, f"maintenance history unavailable ({r.status_code})"
    rows = _rows(r.json())
    assert isinstance(rows, list), "history did not return a list"
    if expected:
        assert rows, f"asset has {expected} maintenance events but the API returned none"


@case("AS-09", "Request asset summary", "AI generated summary is returned")
def test_as_09_asset_summary(client, auth, ctx, requires_hf):
    r = client.get(f"/asset-summaries/by-asset/{ctx['asset_in']}", headers=auth("admin"))
    assert r.status_code == 200, f"summary request failed ({r.status_code}): {r.text[:200]}"

    body = r.json()
    text_out = (body.get("summary") or "").strip()
    assert text_out, "an empty summary was returned"

    # The response now says which path produced the text. The expectation is a
    # model-generated summary, so a template means the Space did not answer —
    # reported rather than smoothed over, because model_version is stamped
    # either way and would otherwise imply a model wrote this.
    assert body.get("source") == "model", (
        f"summary came from the {body.get('source')!r} path, not the model; "
        f"the Hugging Face Space did not return usable output")


@case("AS-10", "Access asset outside authorized warehouse", "Access is denied")
def test_as_10_cross_warehouse_denied(client, auth, ctx):
    r = client.get(f"/assets/{ctx['asset_out']}", headers=auth("admin"))
    assert r.status_code in (403, 404), (
        f"an out-of-warehouse asset was served ({r.status_code})")
