import logging
from typing import Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status
from jose import JWTError, jwt

from app.core.config import jwt_secret, jwt_algorithm

logger = logging.getLogger(__name__)

router = APIRouter()


def _verify_ws_token(token: Optional[str], user_id: str) -> bool:
    """Return True only if `token` is a valid JWT whose subject matches user_id.

    The notification socket used to trust the path user_id alone, so anyone
    could subscribe to anyone else's stream. Now the caller must present their
    own JWT (as a ?token= query param) and it must belong to that same user.
    """
    if not token:
        return False
    try:
        payload = jwt.decode(token, jwt_secret(), algorithms=[jwt_algorithm()])
    except JWTError:
        return False
    return str(payload.get("sub") or "") == str(user_id)

class ConnectionManager:
    def __init__(self):
        # Maps user_id (str) to their WebSocket connection
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        logger.info(f"WebSocket connected for user: {user_id}")

    def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            logger.info(f"WebSocket disconnected for user: {user_id}")

    async def send_personal_message(self, message: dict, user_id: str):
        if user_id in self.active_connections:
            websocket = self.active_connections[user_id]
            try:
                await websocket.send_json(message)
                logger.info(f"Sent WebSocket message to user: {user_id}")
            except Exception as e:
                logger.error(f"Failed to send WebSocket message to {user_id}: {e}")
                self.disconnect(user_id)
                
    async def broadcast(self, message: dict):
        # For notifying all connected users
        for user_id, websocket in list(self.active_connections.items()):
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"Failed to broadcast WebSocket message to {user_id}: {e}")
                self.disconnect(user_id)

notifier = ConnectionManager()

@router.websocket("/ws/notifications/{user_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    user_id: str,
    token: Optional[str] = Query(default=None),
):
    # The token must be valid and belong to the same user_id in the path,
    # otherwise reject the connection.
    if not _verify_ws_token(token, user_id):
        # accept() before close() is required for the close CODE to actually
        # reach the browser: Starlette/ASGI closing a WebSocket that was
        # never accepted just fails the HTTP-level upgrade handshake, which
        # every browser reports to JS as the generic code 1006 (abnormal
        # closure) — the real 1008 we send here never arrives client-side.
        # Confirmed live: before this fix, an intentionally-invalid token
        # produced `ws.onclose` with code 1006, indistinguishable from a
        # plain network drop, which defeats the frontend's ability to tell
        # "your session is dead, log in again" apart from "transient
        # blip, just retry" (see NotificationBell.tsx). No message is ever
        # sent or received in the brief accepted-then-closed window, so
        # this doesn't grant an unauthenticated caller any real access.
        await websocket.accept()
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        logger.warning("WebSocket auth rejected for user_id=%s", user_id)
        return

    await notifier.connect(websocket, user_id)
    try:
        while True:
            # We don't really expect clients to send much, but we must receive to keep the connection alive
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        notifier.disconnect(user_id)
