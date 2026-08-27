"""Router happy-path tests using FastAPI TestClient + dependency overrides.

These tests don't talk to a real database. They override `get_db` to return a
fake session and `get_current_user` to return a mock profile, then verify the
HTTP shape of each endpoint.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import get_current_user, get_db
from app.routers.user_tickets import router as user_tickets_router


@pytest.fixture
def app(user_id, make_profile):
    """Minimal FastAPI app with only the user-tickets router mounted."""
    app = FastAPI()
    app.include_router(user_tickets_router)

    fake_db = MagicMock()
    fake_user = make_profile(user_id)

    app.dependency_overrides[get_db] = lambda: fake_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    app.state.fake_db = fake_db
    app.state.fake_user = fake_user
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


# ---------------------------------------------------------------------------
# Phase 1, listing & details
# ---------------------------------------------------------------------------


def test_list_my_tickets_returns_paginated_payload(app, client, make_ticket, user_id):
    ticket = make_ticket(created_by=user_id, title="T-1", ticket_number="TKT-2026-0001")

    query = MagicMock()
    query.count.return_value = 1
    query.offset.return_value.limit.return_value.all.return_value = [ticket]

    with patch(
        "app.routers.user_tickets.svc.build_user_tickets_query",
        return_value=query,
    ):
        resp = client.get("/user/tickets?page=1&page_size=20")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert body["items"][0]["ticket_number"] == "TKT-2026-0001"
    assert body["items"][0]["title"] == "T-1"


def test_get_my_ticket_returns_full_detail_with_relations(
    app, client, make_ticket, user_id
):
    ticket = make_ticket(created_by=user_id)
    comment = SimpleNamespace(
        id=uuid.uuid4(),
        ticket_id=ticket.id,
        user_id=user_id,
        comment="working on it",
        is_internal=False,
        created_at=datetime.now(timezone.utc),
    )

    app.state.fake_db.query.return_value.filter.return_value.first.return_value = ticket

    with patch(
        "app.routers.user_tickets.svc.fetch_ticket_comments", return_value=[comment]
    ), patch(
        "app.routers.user_tickets.svc.fetch_ticket_attachments", return_value=[]
    ), patch(
        "app.routers.user_tickets.svc.fetch_ticket_history", return_value=[]
    ):
        resp = client.get(f"/user/tickets/{ticket.id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(ticket.id)
    assert body["description"] == ticket.description
    assert len(body["comments"]) == 1
    assert body["comments"][0]["comment"] == "working on it"


def test_get_my_ticket_404_when_not_found(app, client):
    app.state.fake_db.query.return_value.filter.return_value.first.return_value = None
    resp = client.get(f"/user/tickets/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_get_my_ticket_403_when_not_owner(app, client, make_ticket, other_user_id):
    foreign = make_ticket(created_by=other_user_id, assigned_to=None)
    app.state.fake_db.query.return_value.filter.return_value.first.return_value = foreign
    resp = client.get(f"/user/tickets/{foreign.id}")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Phase 2, create & update
# ---------------------------------------------------------------------------


def test_create_my_ticket_returns_201_and_uses_auto_number(
    app, client, make_ticket, user_id
):
    new_ticket = make_ticket(
        created_by=user_id,
        ticket_number="TKT-2026-0007",
        title="Battery failure",
    )

    with patch(
        "app.routers.user_tickets.svc.create_user_ticket",
        return_value=new_ticket,
    ) as create_mock:
        resp = client.post(
            "/user/tickets",
            json={
                "title": "Battery failure",
                "description": "Truck won't start in cold weather.",
                "use_ai_predictions": False,
            },
        )

    assert resp.status_code == 201
    body = resp.json()
    assert body["ticket_number"] == "TKT-2026-0007"
    assert body["title"] == "Battery failure"
    create_mock.assert_called_once()
    kwargs = create_mock.call_args.kwargs
    assert kwargs["user_id"] == user_id
    assert kwargs["use_ai"] is False


def test_update_my_ticket_403_when_not_owner(app, client):
    with patch(
        "app.routers.user_tickets.svc.get_owned_ticket_or_none", return_value=None
    ):
        app.state.fake_db.query.return_value.filter.return_value.first.return_value = (
            MagicMock()  # ticket exists, just not owned
        )
        resp = client.put(
            f"/user/tickets/{uuid.uuid4()}",
            json={"title": "x"},
        )
    assert resp.status_code == 403


def test_update_my_ticket_400_when_payload_empty(app, client, make_ticket, user_id):
    ticket = make_ticket(created_by=user_id)
    with patch(
        "app.routers.user_tickets.svc.get_owned_ticket_or_none", return_value=ticket
    ):
        resp = client.put(f"/user/tickets/{ticket.id}", json={})
    assert resp.status_code == 400


def test_update_my_ticket_succeeds_for_owner(app, client, make_ticket, user_id):
    ticket = make_ticket(created_by=user_id, title="old")

    def fake_update(db, t, updates):
        for k, v in updates.items():
            setattr(t, k, v)
        return t

    with patch(
        "app.routers.user_tickets.svc.get_owned_ticket_or_none", return_value=ticket
    ), patch(
        "app.routers.user_tickets.svc.update_user_ticket", side_effect=fake_update
    ), patch(
        "app.routers.user_tickets.svc.fetch_ticket_comments", return_value=[]
    ), patch(
        "app.routers.user_tickets.svc.fetch_ticket_attachments", return_value=[]
    ), patch(
        "app.routers.user_tickets.svc.fetch_ticket_history", return_value=[]
    ):
        resp = client.put(
            f"/user/tickets/{ticket.id}",
            json={"title": "new title"},
        )

    assert resp.status_code == 200
    assert resp.json()["title"] == "new title"


# ---------------------------------------------------------------------------
# Phase 3, comments
# ---------------------------------------------------------------------------


def test_list_comments_returns_array(app, client, make_ticket, user_id):
    ticket = make_ticket(created_by=user_id)
    comment = SimpleNamespace(
        id=uuid.uuid4(),
        ticket_id=ticket.id,
        user_id=user_id,
        comment="hello",
        is_internal=False,
        created_at=datetime.now(timezone.utc),
    )
    app.state.fake_db.query.return_value.filter.return_value.first.return_value = ticket

    with patch(
        "app.routers.user_tickets.svc.fetch_ticket_comments", return_value=[comment]
    ):
        resp = client.get(f"/user/tickets/{ticket.id}/comments")

    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["comment"] == "hello"


def test_add_comment_201_and_returns_object(app, client, make_ticket, user_id):
    ticket = make_ticket(created_by=user_id)
    saved = SimpleNamespace(
        id=uuid.uuid4(),
        ticket_id=ticket.id,
        user_id=user_id,
        comment="please prioritise",
        is_internal=False,
        created_at=datetime.now(timezone.utc),
    )
    app.state.fake_db.query.return_value.filter.return_value.first.return_value = ticket

    with patch(
        "app.routers.user_tickets.svc.add_user_comment", return_value=saved
    ):
        resp = client.post(
            f"/user/tickets/{ticket.id}/comments",
            json={"comment": "please prioritise"},
        )

    assert resp.status_code == 201
    assert resp.json()["comment"] == "please prioritise"
    assert resp.json()["user_id"] == str(user_id)
