"""Ticket details for the staff view come from the API, scoped and minimised."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.models import Asset, Department, Profile, TicketStatusHistory, Warehouse
from app.services.ticket_access import can_view_ticket
from app.services.ticket_detail_service import ticket_details

WH, OTHER = str(uuid.uuid4()), str(uuid.uuid4())
CREATOR, ASSIGNEE, CHANGER = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
ASSET, DEPT = uuid.uuid4(), uuid.uuid4()


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *a, **k):
        return self

    def order_by(self, *a):
        return self

    def all(self):
        return list(self.rows)

    def first(self):
        return self.rows[0] if self.rows else None

    def scalar(self):
        return self.rows[0] if self.rows else None


class FakeDB:
    """Answers each query by the model (or column's model) it starts from."""

    def __init__(self):
        now = datetime.now(timezone.utc)
        self.data = {
            TicketStatusHistory: [SimpleNamespace(id=uuid.uuid4(), old_status=None, new_status="open",
                                                  changed_by=CHANGER, note="raised", created_at=now)],
            Profile: [SimpleNamespace(id=CREATOR, full_name="Nuwan", email="nuwan@example.lk"),
                      SimpleNamespace(id=ASSIGNEE, full_name="Kasun", email="kasun@example.lk"),
                      SimpleNamespace(id=CHANGER, full_name="Amali", email="amali@example.lk")],
            Asset: [SimpleNamespace(warehouse_id=WH, department_id=DEPT)],
            Department: ["Transport"],
            Warehouse: ["Colombo"],
        }

    def query(self, first, *rest):
        model = getattr(first, "class_", first)
        return FakeQuery(self.data[model])


TICKET = SimpleNamespace(id=uuid.uuid4(), warehouse_id=WH, asset_id=ASSET, created_by=CREATOR, assigned_to=ASSIGNEE)


def test_names_site_and_history_are_resolved():
    staff = SimpleNamespace(id=uuid.uuid4(), role="user", warehouse_id=WH)
    out = ticket_details(FakeDB(), TICKET, staff)
    assert out["creator_name"] == "Nuwan" and out["assignee_name"] == "Kasun"
    assert out["warehouse_name"] == "Colombo" and out["department_name"] == "Transport"
    (entry,) = out["history"]
    assert entry["changed_by_name"] == "Amali" and entry["new_status"] == "open"


def test_the_creator_email_is_shown_to_admins_only():
    staff = SimpleNamespace(id=uuid.uuid4(), role="user", warehouse_id=WH)
    admin = SimpleNamespace(id=uuid.uuid4(), role="admin", warehouse_id=WH, _active_warehouse_id=WH)
    assert ticket_details(FakeDB(), TICKET, staff)["creator_email"] is None
    assert ticket_details(FakeDB(), TICKET, admin)["creator_email"] == "nuwan@example.lk"


def test_a_ticket_without_people_or_asset_returns_empty_fields():
    bare = SimpleNamespace(id=uuid.uuid4(), warehouse_id=None, asset_id=None, created_by=None, assigned_to=None)
    db = FakeDB()
    db.data[TicketStatusHistory] = []
    out = ticket_details(db, bare, SimpleNamespace(id=uuid.uuid4(), role="user", warehouse_id=WH))
    assert out == {"creator_name": None, "creator_email": None, "assignee_name": None,
                   "warehouse_name": None, "department_name": None, "history": []}


@pytest.mark.parametrize("user,ticket_wh,created_by,expected", [
    (SimpleNamespace(id="a", role="admin", warehouse_id=WH, _active_warehouse_id=WH), WH, None, True),
    (SimpleNamespace(id="a", role="admin", warehouse_id=WH, _active_warehouse_id=WH), OTHER, None, False),
    (SimpleNamespace(id="u", role="user", warehouse_id=WH), WH, None, True),
    (SimpleNamespace(id="u", role="user", warehouse_id=WH), OTHER, None, False),
    (SimpleNamespace(id="u", role="user", warehouse_id=WH), OTHER, "u", True),   # own ticket elsewhere
], ids=["admin-own", "admin-other", "user-own", "user-other", "user-created-elsewhere"])
def test_can_view_ticket(user, ticket_wh, created_by, expected):
    ticket = SimpleNamespace(warehouse_id=ticket_wh, created_by=created_by, assigned_to=None)
    assert can_view_ticket(ticket, user) is expected


def test_the_details_route_hides_tickets_outside_scope():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.deps import get_current_user, get_db
    from app.routers.tickets import router

    other_ticket = SimpleNamespace(id=uuid.uuid4(), warehouse_id=OTHER, created_by=None, assigned_to=None)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: SimpleNamespace(query=lambda *a: FakeQuery([other_ticket]))
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid.uuid4(), role="user", warehouse_id=WH)
    resp = TestClient(app).get(f"/tickets/{other_ticket.id}/details")
    assert resp.status_code == 404
