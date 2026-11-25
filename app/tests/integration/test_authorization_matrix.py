"""Authorization matrix: role × endpoint × own or other warehouse.

Every request is a read, or one the API must refuse before writing, so this
is safe to run against the shared database. A 404 for another warehouse's
record is the expected answer: the API does not reveal that it exists.
"""
from __future__ import annotations

import io

import pytest

pytestmark = pytest.mark.integration

# (label, role, method, path template, body, expected status)
CASES = [
    # Authentication
    ("no token", None, "GET", "/assets/count", None, 401),
    ("garbage token", "garbage", "GET", "/assets/count", None, 401),
    ("selection token as session", "selection", "GET", "/assets/count", None, 401),
    ("anonymous warehouse list", None, "GET", "/auth/warehouses", None, 401),
    ("admin warehouse list", "admin", "GET", "/auth/warehouses", None, 403),
    ("super admin warehouse list", "super", "GET", "/auth/warehouses", None, 200),
    # Own warehouse is visible
    ("admin own asset", "admin", "GET", "/assets/{asset_same}", None, 200),
    ("admin own ticket", "admin", "GET", "/tickets/{ticket_same}", None, 200),
    ("admin user list", "admin", "GET", "/users/", None, 200),
    ("admin own user's assets", "admin", "GET", "/users/{user_same}/assets", None, 200),
    ("user own warehouse ticket", "user", "GET", "/tickets/{ticket_same}", None, 200),
    ("admin own ticket details", "admin", "GET", "/tickets/{ticket_same}/details", None, 200),
    # Other warehouse is invisible
    ("admin other asset", "admin", "GET", "/assets/{asset_other}", None, 404),
    ("admin other ticket", "admin", "GET", "/tickets/{ticket_other}", None, 404),
    ("admin other comments", "admin", "GET", "/ticket-comments/?ticket_id={ticket_other}", None, 404),
    ("admin other attachments", "admin", "GET", "/ticket-attachments/?ticket_id={ticket_other}", None, 404),
    ("admin other status history", "admin", "GET", "/ticket-status-history/?ticket_id={ticket_other}", None, 404),
    ("admin other summary", "admin", "GET", "/ticket-summaries/by-ticket/{ticket_other}", None, 404),
    ("admin other maintenance event", "admin", "GET", "/maintenance/{event_other}", None, 404),
    ("admin other user's assets", "admin", "GET", "/users/{user_other}/assets", None, 404),
    ("admin other cost prediction", "admin", "GET", "/predictions/cost/{asset_other}", None, 404),
    ("user other user's assets", "user", "GET", "/users/{user_other}/assets", None, 404),
    ("user other warehouse ticket", "user", "GET", "/tickets/{ticket_other}", None, 404),
    ("admin other ticket details", "admin", "GET", "/tickets/{ticket_other}/details", None, 404),
    ("user other ticket details", "user", "GET", "/tickets/{ticket_other}/details", None, 404),
    # Attachments only arrive as uploads the API validates, never as bare URLs
    ("attachment by URL is gone", "admin", "POST", "/ticket-attachments/",
     {"ticket_id": "{ticket_same}", "file_path": "https://evil.example/x.png"}, 405),
    # Privilege escalation is refused before any write
    ("admin grants super_admin", "admin", "PUT", "/users/{user_same}", {"role": "super_admin"}, 403),
    ("admin edits other warehouse user", "admin", "PUT", "/users/{user_other}", {"role": "admin"}, 404),
    ("admin clears own warehouse", "admin", "PUT", "/profiles/{admin_id}", {"warehouse_id": None}, 403),
    ("admin reads a super admin", "admin", "GET", "/profiles/{super_id}", None, 404),
    ("admin creates a warehouse", "admin", "POST", "/warehouses/", {"name": "x", "code": "x"}, 403),
    ("user lists all profiles", "user", "GET", "/profiles/", None, 403),
    ("user generates AI report", "user", "GET", "/warehouse-dashboard/generate-report", None, 403),
    # Cross-warehouse writes are refused before any write
    ("admin ticket on other asset", "admin", "POST", "/tickets/",
     {"title": "t", "description": "d", "asset_id": "{asset_other}", "created_by": "{admin_id}"}, 404),
    ("admin notifies other user", "admin", "POST", "/notifications",
     {"title": "t", "message": "m", "user_id": "{user_other}"}, 404),
    ("notification with external link", "admin", "POST", "/notifications",
     {"title": "t", "message": "m", "link_url": "https://evil.example"}, 422),
    # Password change never signs the user out on a wrong password
    ("wrong current password", "admin", "PUT", "/profiles/me/password",
     {"current_password": "definitely-wrong", "new_password": "NewPassw0rd!"}, 400),
]


def _fill(value, world):
    ids = {
        "asset_same": world["asset_same"], "asset_other": world["asset_other"],
        "ticket_same": world["ticket_same"], "ticket_other": world["ticket_other"],
        "user_same": world["user_same"], "user_other": world["user_other"],
        "event_other": world["event_other"], "admin_id": world["admin"]["id"],
        "super_id": world["super"][0],
    }
    if isinstance(value, str):
        return value.format(**ids)
    if isinstance(value, dict):
        return {k: _fill(v, world) for k, v in value.items()}
    return value


@pytest.mark.parametrize("label,role,method,path,body,expected", CASES, ids=[c[0] for c in CASES])
def test_authorization(api, world, bearer, label, role, method, path, body, expected):
    if role is None:
        headers = {}
    elif role == "garbage":
        headers = {"Authorization": "Bearer not-a-token"}
    else:
        headers = bearer(role)
    resp = api.request(method, _fill(path, world), json=_fill(body, world), headers=headers)
    assert resp.status_code == expected, f"{label}: {resp.status_code} {resp.text[:200]}"


def test_image_upload_rejects_disguised_svg(api, world, bearer):
    svg = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
    resp = api.post(f"/assets/{world['asset_same']}/image",
                    files={"file": ("x.png", io.BytesIO(svg), "image/png")}, headers=bearer("admin"))
    assert resp.status_code == 415


PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360000002000154a24f5b0000000049454e44ae426082"
)


def test_attachment_upload_rejects_disguised_svg(api, world, bearer):
    svg = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
    resp = api.post("/ticket-attachments/upload", data={"ticket_id": world["ticket_same"]},
                    files={"file": ("x.png", io.BytesIO(svg), "image/png")}, headers=bearer("admin"))
    assert resp.status_code == 415


def test_attachment_upload_to_another_warehouse_is_refused(api, world, bearer):
    resp = api.post("/ticket-attachments/upload", data={"ticket_id": world["ticket_other"]},
                    files={"file": ("x.png", io.BytesIO(PNG_1PX), "image/png")}, headers=bearer("admin"))
    assert resp.status_code == 404


def test_login_is_rate_limited(api):
    codes = [api.post("/auth/login", json={"email": "nobody@example.invalid", "password": "x"}).status_code
             for _ in range(15)]
    assert 429 in codes, "per-account login limit never triggered"
