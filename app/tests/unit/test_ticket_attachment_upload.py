"""Ticket attachments arrive only as uploads the API validates and stores."""
from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services import attachment_service, image_upload_service as uploads

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
SVG = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"


# ── Service ───────────────────────────────────────────────────────────────────

class FakeBucket:
    def __init__(self, fail_upload=False):
        self.uploaded, self.removed, self.fail_upload = [], [], fail_upload

    def upload(self, path, file, file_options):
        if self.fail_upload:
            raise RuntimeError("storage said no")
        self.uploaded.append((path, file_options["content-type"]))

    def get_public_url(self, path):
        return f"https://proj.supabase.co/storage/v1/object/public/ticket-attachments/{path}?"

    def remove(self, paths):
        self.removed.extend(paths)


class FakeSession:
    def __init__(self, fail_commit=False):
        self.added, self.rollbacks, self.fail_commit = [], 0, fail_commit

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        if self.fail_commit:
            raise RuntimeError("db down")

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, obj):
        pass


@pytest.fixture()
def bucket(monkeypatch):
    from app.core.storage import supabase_storage

    fake = FakeBucket()
    monkeypatch.setattr(supabase_storage, "client", SimpleNamespace(storage=SimpleNamespace(from_=lambda name: fake)))
    return fake


TICKET = SimpleNamespace(id=uuid.uuid4())


def test_a_valid_image_is_stored_under_a_server_generated_name(bucket):
    db = FakeSession()
    row = attachment_service.store_ticket_attachment(
        db, ticket=TICKET, uploaded_by="u1", content=PNG, original_filename="../../etc/passwd.html")

    (path, content_type), = bucket.uploaded
    assert path.startswith(f"{TICKET.id}/") and path.endswith(".png")
    assert content_type == "image/png"            # from the bytes, not the client
    assert row.mime_type == "image/png" and row.uploaded_by == "u1"
    assert row.original_filename == "passwd.html"   # display name only, no directories
    assert not row.file_path.endswith("?")


@pytest.mark.parametrize("content,error", [
    (SVG, uploads.UnsupportedImage),
    (b"%PDF-1.7 not an image", uploads.UnsupportedImage),
    (PNG + b"\x00" * attachment_service.MAX_ATTACHMENT_BYTES, uploads.ImageTooLarge),
], ids=["svg", "pdf", "oversized"])
def test_bad_files_are_rejected_before_storage_is_touched(bucket, content, error):
    with pytest.raises(error):
        attachment_service.store_ticket_attachment(
            FakeSession(), ticket=TICKET, uploaded_by="u1", content=content, original_filename="x.png")
    assert bucket.uploaded == []


def test_unconfigured_storage_is_an_error_not_a_fake_url(monkeypatch):
    from app.core.storage import supabase_storage

    monkeypatch.setattr(supabase_storage, "client", None)
    with pytest.raises(uploads.StorageUnavailable):
        attachment_service.store_ticket_attachment(
            FakeSession(), ticket=TICKET, uploaded_by="u1", content=PNG, original_filename="x.png")


def test_a_storage_failure_is_reported(monkeypatch):
    from app.core.storage import supabase_storage

    failing = FakeBucket(fail_upload=True)
    monkeypatch.setattr(supabase_storage, "client", SimpleNamespace(storage=SimpleNamespace(from_=lambda n: failing)))
    with pytest.raises(uploads.StorageFailed):
        attachment_service.store_ticket_attachment(
            FakeSession(), ticket=TICKET, uploaded_by="u1", content=PNG, original_filename="x.png")


def test_a_failed_database_write_removes_the_uploaded_object(bucket):
    db = FakeSession(fail_commit=True)
    with pytest.raises(RuntimeError, match="db down"):
        attachment_service.store_ticket_attachment(
            db, ticket=TICKET, uploaded_by="u1", content=PNG, original_filename="x.png")
    assert db.rollbacks == 1
    assert bucket.removed == [bucket.uploaded[0][0]]


@pytest.mark.parametrize("raw,expected", [
    (None, None), ("", None), ("photo.png", "photo.png"), ("C:\\Users\\me\\x.png", "x.png"),
    ("a\x00b\nc.png", "abc.png"), ("x" * 400, "x" * 255),
])
def test_clean_filename(raw, expected):
    assert attachment_service.clean_filename(raw) == expected


def test_unconfigured_report_storage_raises_instead_of_inventing_a_url(monkeypatch):
    from app.core.storage import supabase_storage

    monkeypatch.setattr(supabase_storage, "client", None)
    with pytest.raises(RuntimeError, match="not configured"):
        supabase_storage.upload_file(bucket="reports", file_path="x.pdf", destination_path="x.pdf")


# ── Routes ────────────────────────────────────────────────────────────────────

class _Query:
    def __init__(self, result):
        self.result = result

    def filter(self, *a, **k):
        return self

    def first(self):
        return self.result


def _client(router, user, ticket):
    from app.deps import get_current_user, get_db, require_user

    app = FastAPI()
    app.include_router(router)
    db = SimpleNamespace(query=lambda *a: _Query(ticket))
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[require_user] = lambda: user
    return TestClient(app)


WH, OTHER_WH = str(uuid.uuid4()), str(uuid.uuid4())
STAFF = SimpleNamespace(id=uuid.uuid4(), role="user", warehouse_id=WH)


def _ticket(warehouse_id):
    return SimpleNamespace(id=uuid.uuid4(), warehouse_id=warehouse_id, created_by=uuid.uuid4(), assigned_to=None)


@pytest.fixture()
def stored(monkeypatch):
    calls = []

    def fake_store(db, **kw):
        calls.append(kw)
        return {"id": uuid.uuid4(), "ticket_id": kw["ticket"].id, "file_path": "https://x/y.png",
                "mime_type": "image/png", "original_filename": kw["original_filename"],
                "uploaded_by": kw["uploaded_by"], "created_at": datetime.now(timezone.utc)}

    monkeypatch.setattr(attachment_service, "store_ticket_attachment", fake_store)
    return calls


def test_staff_upload_stores_the_file_for_a_visible_ticket(stored):
    from app.routers.ticket_attachments import router

    ticket = _ticket(WH)
    resp = _client(router, STAFF, ticket).post(
        "/ticket-attachments/upload", data={"ticket_id": str(ticket.id)},
        files={"file": ("p.png", io.BytesIO(PNG), "image/png")})
    assert resp.status_code == 201, resp.text
    assert stored[0]["uploaded_by"] == STAFF.id and stored[0]["content"] == PNG


def test_staff_upload_to_an_invisible_ticket_is_a_404(stored):
    from app.routers.ticket_attachments import router

    ticket = _ticket(OTHER_WH)
    resp = _client(router, STAFF, ticket).post(
        "/ticket-attachments/upload", data={"ticket_id": str(ticket.id)},
        files={"file": ("p.png", io.BytesIO(PNG), "image/png")})
    assert resp.status_code == 404 and stored == []


@pytest.mark.parametrize("error,status", [
    (uploads.ImageTooLarge("big"), 413), (uploads.UnsupportedImage("svg"), 415),
    (uploads.StorageUnavailable("off"), 503), (uploads.StorageFailed("no"), 502),
])
def test_upload_errors_map_to_http_statuses(monkeypatch, error, status):
    from app.routers.ticket_attachments import router

    def boom(db, **kw):
        raise error

    monkeypatch.setattr(attachment_service, "store_ticket_attachment", boom)
    ticket = _ticket(WH)
    resp = _client(router, STAFF, ticket).post(
        "/ticket-attachments/upload", data={"ticket_id": str(ticket.id)},
        files={"file": ("p.png", io.BytesIO(PNG), "image/png")})
    assert resp.status_code == status


def test_the_url_attach_endpoint_no_longer_exists():
    from app.routers.ticket_attachments import router

    resp = _client(router, STAFF, _ticket(WH)).post(
        "/ticket-attachments/", json={"ticket_id": str(uuid.uuid4()), "file_path": "https://evil.example/x.png"})
    assert resp.status_code == 405


def test_user_upload_respects_the_user_ticket_rule(stored, monkeypatch):
    from app.routers.user_tickets import router
    from app.services import user_ticket_service

    ticket = _ticket(WH)
    monkeypatch.setattr(user_ticket_service, "user_can_view_ticket", lambda t, uid, wh: False)
    client = _client(router, STAFF, ticket)
    denied = client.post(f"/user/tickets/{ticket.id}/attachments/upload",
                         files={"file": ("p.png", io.BytesIO(PNG), "image/png")})
    assert denied.status_code == 403 and stored == []

    monkeypatch.setattr(user_ticket_service, "user_can_view_ticket", lambda t, uid, wh: True)
    allowed = client.post(f"/user/tickets/{ticket.id}/attachments/upload",
                          files={"file": ("p.png", io.BytesIO(PNG), "image/png")})
    assert allowed.status_code == 201, allowed.text
