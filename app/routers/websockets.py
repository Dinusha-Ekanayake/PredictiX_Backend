"""Real-time notification stream over WebSocket.

Authentication happens in the first message, not the URL:

    client: connect to /ws/notifications/{user_id}
    client: {"type": "auth", "token": "<access JWT>"}
    server: keeps the socket open, or closes it with 1008

A token in the query string ends up in proxy and server access logs, so the
`?token=` form is accepted only for older frontends and is not used by the
current one.
"""
import asyncio
import json
import logging
from typing import Dict, Optional, Set

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.core.security import InvalidTokenError, decode_token

logger = logging.getLogger(__name__)

router = APIRouter()

#: How long a new connection may wait before sending its auth message.
AUTH_TIMEOUT_SECONDS = 10.0


def _verify_ws_token(token: Optional[str], user_id: str) -> bool:
    """Return True only if `token` is a valid access JWT whose subject is user_id.

    The path user_id alone proves nothing, so trusting it would let anyone
    subscribe to anyone else's stream.
    """
    if not token:
        return False
    try:
        payload = decode_token(token)
    except InvalidTokenError:
        return False
    if payload.get("type", "access") != "access":
        return False
    return str(payload.get("sub") or "") == str(user_id)


def _token_from_auth_message(raw: str) -> Optional[str]:
    """The token from a {"type": "auth", "token": ...} message, or None."""
    try:
        message = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(message, dict) or message.get("type") != "auth":
        return None
    token = message.get("token")
    return token if isinstance(token, str) else None


class ConnectionManager:
    """Open sockets per user. A user may have several tabs or devices open."""

    def __init__(self) -> None:
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    def register(self, websocket: WebSocket, user_id: str) -> None:
        self.active_connections.setdefault(user_id, set()).add(websocket)
        logger.info("WebSocket connected for user %s (%d open)", user_id[:8], len(self.active_connections[user_id]))

    def disconnect(self, user_id: str, websocket: Optional[WebSocket] = None) -> None:
        sockets = self.active_connections.get(user_id)
        if not sockets:
            return
        if websocket is None:
            sockets.clear()
        else:
            sockets.discard(websocket)
        if not sockets:
            del self.active_connections[user_id]
        logger.info("WebSocket disconnected for user %s", user_id[:8])

    async def send_personal_message(self, message: dict, user_id: str) -> None:
        for websocket in list(self.active_connections.get(user_id, ())):
            try:
                await websocket.send_json(message)
            except Exception as exc:  # noqa: BLE001 - a dead socket must not stop the others
                logger.warning("Dropping WebSocket for user %s: %s", user_id[:8], exc)
                self.disconnect(user_id, websocket)

    async def broadcast(self, message: dict) -> None:
        for user_id in list(self.active_connections):
            await self.send_personal_message(message, user_id)


notifier = ConnectionManager()


async def _reject(websocket: WebSocket, user_id: str) -> None:
    # The socket is accepted before it is closed because a close sent during
    # the handshake reaches the browser as 1006 (network error) instead of
    # 1008, and the frontend relies on 1008 to tell "session expired" apart
    # from a dropped connection. No data is exchanged in between.
    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
    logger.warning("WebSocket auth rejected for user_id=%s", user_id[:8])


@router.websocket("/ws/notifications/{user_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    user_id: str,
    token: Optional[str] = Query(default=None),
):
    await websocket.accept()

    if token is None:
        try:
            first = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_TIMEOUT_SECONDS)
        except WebSocketDisconnect:
            return  # the client left before authenticating; nothing to close
        except asyncio.TimeoutError:
            await _reject(websocket, user_id)
            return
        token = _token_from_auth_message(first)

    if not _verify_ws_token(token, user_id):
        await _reject(websocket, user_id)
        return

    notifier.register(websocket, user_id)
    try:
        while True:
            # Clients only send keep-alive pings; reading keeps the socket open.
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        notifier.disconnect(user_id, websocket)
