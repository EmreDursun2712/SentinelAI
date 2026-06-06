"""WebSocket event stream consumed by the frontend dashboard."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.websocket("/stream")
async def stream(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json({"type": "stream.connected", "payload": {}})
    try:
        while True:
            # Phase 0: keep the connection open; broadcaster wiring lands in Phase 4.
            message = await websocket.receive_text()
            await websocket.send_json({"type": "echo", "payload": {"message": message}})
    except WebSocketDisconnect:
        logger.info("ws.disconnect")
