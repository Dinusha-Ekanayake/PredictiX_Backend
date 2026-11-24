"""Notification WebSocket: authentication and delivery to every open tab."""
from __future__ import annotations

import asyncio
import json
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

os.environ.setdefault("JWT_SECRET", "unit-test-secret-not-used-anywhere-else")

from app.routers.auth import _create_token  # noqa: E402
from app.routers import websockets as ws_module  # noqa: E402

USER = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(ws_module, "notifier", ws_module.ConnectionManager())
    app = FastAPI()
    app.include_router(ws_module.router)
    return TestClient(app)


def _token(sub: str) -> str:
    return _create_token(sub, "user@example.com", "user")


def _auth(token: str) -> str:
    return json.dumps({"type": "auth", "token": token})


def test_first_message_auth_opens_the_stream(client):
    with client.websocket_connect(f"/ws/notifications/{USER}") as ws:
        ws.send_text(_auth(_token(USER)))
        ws.send_text("ping")
        assert ws.receive_text() == "pong"


def test_query_string_token_still_works_for_older_clients(client):
    with client.websocket_connect(f"/ws/notifications/{USER}?token={_token(USER)}") as ws:
        ws.send_text("ping")
        assert ws.receive_text() == "pong"


@pytest.mark.parametrize("first_message", [
    _auth("not-a-jwt"),
    "ping",
    json.dumps({"type": "auth"}),
    json.dumps({"type": "hello", "token": "x"}),
])
def test_bad_auth_message_is_closed_with_1008(client, first_message):
    with client.websocket_connect(f"/ws/notifications/{USER}") as ws:
        ws.send_text(first_message)
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    assert closed.value.code == 1008


def test_another_users_token_cannot_open_this_stream(client):
    with client.websocket_connect(f"/ws/notifications/{USER}") as ws:
        ws.send_text(_auth(_token(OTHER)))
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    assert closed.value.code == 1008


def test_each_open_tab_is_registered_and_removed_on_close(client):
    manager = ws_module.notifier
    with client.websocket_connect(f"/ws/notifications/{USER}") as tab1, \
         client.websocket_connect(f"/ws/notifications/{USER}") as tab2:
        for tab in (tab1, tab2):
            tab.send_text(_auth(_token(USER)))
            tab.send_text("ping")
            assert tab.receive_text() == "pong"
        assert len(manager.active_connections[USER]) == 2

    assert USER not in manager.active_connections


def test_a_dead_socket_is_dropped_without_affecting_others():
    class Dead:
        async def send_json(self, message):
            raise RuntimeError("gone")

    class Alive:
        def __init__(self):
            self.got = []

        async def send_json(self, message):
            self.got.append(message)

    manager = ws_module.ConnectionManager()
    dead, alive = Dead(), Alive()
    manager.register(dead, USER)
    manager.register(alive, USER)
    asyncio.run(manager.send_personal_message({"id": "n"}, USER))
    assert alive.got == [{"id": "n"}]
    assert manager.active_connections[USER] == {alive}


def test_every_open_tab_receives_the_notification():
    class Tab:
        def __init__(self):
            self.got = []

        async def send_json(self, message):
            self.got.append(message)

    manager = ws_module.ConnectionManager()
    tab1, tab2, stranger = Tab(), Tab(), Tab()
    manager.register(tab1, USER)
    manager.register(tab2, USER)
    manager.register(stranger, OTHER)
    asyncio.run(manager.send_personal_message({"id": "n1"}, USER))
    assert tab1.got == tab2.got == [{"id": "n1"}]
    assert stranger.got == []


def test_client_leaving_before_auth_is_handled_quietly(client, caplog):
    with client.websocket_connect(f"/ws/notifications/{USER}"):
        pass  # closes without sending the auth message
    assert "Traceback" not in caplog.text
    assert USER not in ws_module.notifier.active_connections
