import asyncio
import json
import logging
from typing import Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.plc.collector import get_latest_telemetry

logger = logging.getLogger("app.api.websocket")
router = APIRouter(tags=["Real-Time Telemetry"])

class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"WebSocket client connected. Total clients: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info(f"WebSocket client disconnected. Total clients: {len(self.active_connections)}")

    async def broadcast_telemetry(self):
        """Broadcasts live sensor readings to all connected clients."""
        while True:
            if self.active_connections:
                data = get_latest_telemetry()
                payload = json.dumps(data, default=str)
                # Iterate over a copy of the set to handle disconnects during broadcast
                for connection in list(self.active_connections):
                    try:
                        await connection.send_text(payload)
                    except Exception:
                        self.disconnect(connection)
            await asyncio.sleep(1.5)

manager = ConnectionManager()

@router.websocket("/ws/telemetry")
async def websocket_telemetry_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive & listen for client messages (e.g., pause/resume)
            msg = await websocket.receive_text()
            # Client can send {"action": "ping"}
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.warning(f"WebSocket connection error: {e}")
        manager.disconnect(websocket)

async def start_ws_broadcast():
    asyncio.create_task(manager.broadcast_telemetry())
