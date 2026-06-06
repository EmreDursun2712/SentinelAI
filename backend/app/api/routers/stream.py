"""WebSocket event stream consumed by the frontend dashboard.

Auth: browsers can't set an Authorization header on a WebSocket, so the JWT is
passed as a ``?token=`` query parameter (or the ``access_token`` subprotocol)
and validated **before** the handshake is accepted. Invalid/missing tokens are
rejected with close code 1008 (policy violation).

Once accepted, the socket is registered with the connection manager and receives
every broadcast event. The receive loop exists only to detect disconnects; the
client is not required to send anything.
"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.core.logging import get_logger
from app.core.security import decode_access_token
from app.core.ws_manager import get_connection_manager
from app.models.enums import Role

router = APIRouter()
logger = get_logger(__name__)


def _principal_from_token(token: str | None) -> tuple[str, Role] | None:
    """Validate a JWT and return (username, role), or None if invalid."""
    if not token:
        return None
    claims = decode_access_token(token)
    if not claims:
        return None
    username = claims.get("sub")
    role_raw = claims.get("role")
    if not username or not role_raw:
        return None
    try:
        return str(username), Role(role_raw)
    except ValueError:
        return None


def _extract_token(websocket: WebSocket) -> str | None:
    token = websocket.query_params.get("token")
    if token:
        return token
    # Fallback: a subprotocol of the form "access_token,<jwt>".
    protocols = websocket.headers.get("sec-websocket-protocol")
    if protocols:
        parts = [p.strip() for p in protocols.split(",")]
        if len(parts) == 2 and parts[0] == "access_token":
            return parts[1]
    return None


@router.websocket("/stream")
async def stream(websocket: WebSocket) -> None:
    principal = _principal_from_token(_extract_token(websocket))
    if principal is None:
        # Reject before accepting the handshake.
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        logger.info("ws.rejected", reason="invalid_or_missing_token")
        return

    username, role = principal
    await websocket.accept()
    manager = get_connection_manager()
    await manager.add(websocket)
    await websocket.send_json(
        {"type": "stream.connected", "payload": {"user": username, "role": role.value}}
    )
    try:
        while True:
            # We don't need inbound messages; this unblocks on disconnect.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.remove(websocket)
