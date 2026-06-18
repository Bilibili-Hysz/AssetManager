"""WebSocket manager for real-time client updates."""
import asyncio
import json
import logging
from aiohttp import web

_log = logging.getLogger(__name__)

MAX_WS_CONNECTIONS = 50


class WebSocketManager:
    """Manages connected WebSocket clients and broadcasts events."""

    def __init__(self):
        self._clients: set[web.WebSocketResponse] = set()
        self._lock = asyncio.Lock()
        self._heartbeat_task: asyncio.Task | None = None

    async def add(self, ws: web.WebSocketResponse):
        async with self._lock:
            if len(self._clients) >= MAX_WS_CONNECTIONS:
                await ws.close(code=1013, message=b"Too many connections")
                return
            self._clients.add(ws)
            _log.debug("WebSocket client connected (%d total)", len(self._clients))
        if self._heartbeat_task is None:
            self._heartbeat_task = asyncio.create_task(self._heartbeat())

    async def remove(self, ws: web.WebSocketResponse):
        async with self._lock:
            self._clients.discard(ws)
            _log.debug("WebSocket client disconnected (%d total)", len(self._clients))

    async def _heartbeat(self):
        while True:
            await asyncio.sleep(30)
            async with self._lock:
                if not self._clients:
                    self._heartbeat_task = None
                    return
                dead = []
                for ws in self._clients:
                    try:
                        await ws.ping()
                    except Exception:
                        dead.append(ws)
                for ws in dead:
                    self._clients.discard(ws)

    async def broadcast(self, event_type: str, data: dict | None = None):
        """Send a JSON event to all connected clients."""
        async with self._lock:
            if not self._clients:
                return
            clients = list(self._clients)

        message = json.dumps({"type": event_type, **(data or {})})
        dead: list[web.WebSocketResponse] = []
        for ws in clients:
            try:
                await ws.send_str(message)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)

    async def close_all(self):
        """Close all connected WebSocket clients."""
        async with self._lock:
            clients = list(self._clients)
            self._clients.clear()

        for ws in clients:
            try:
                await ws.close()
            except Exception:
                pass
