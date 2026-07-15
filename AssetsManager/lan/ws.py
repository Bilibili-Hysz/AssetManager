"""WebSocket manager for real-time client updates."""
import asyncio
import json
import logging
from aiohttp import web

_log = logging.getLogger(__name__)

MAX_WS_CONNECTIONS = 50
WS_HEARTBEAT_INTERVAL = 30
WS_OPERATION_TIMEOUT = 5
HEARTBEAT_PING_TIMEOUT = 10.0


class WebSocketManager:
    """Manages connected WebSocket clients and broadcasts events."""

    def __init__(self):
        self._clients: set[web.WebSocketResponse] = set()
        self._lock = asyncio.Lock()
        self._heartbeat_task: asyncio.Task | None = None
        self._pong_waiters: dict[web.WebSocketResponse, tuple[bytes, asyncio.Event]] = {}
        self._ping_sequence = 0

    async def add(self, ws: web.WebSocketResponse) -> bool:
        async with self._lock:
            if len(self._clients) >= MAX_WS_CONNECTIONS:
                accepted = False
            else:
                self._clients.add(ws)
                accepted = True
                _log.debug("WebSocket client connected (%d total)", len(self._clients))
                if self._heartbeat_task is None or self._heartbeat_task.done():
                    self._heartbeat_task = asyncio.create_task(self._heartbeat())
        if not accepted:
            await self._close(ws, code=1013, message=b"Too many connections")
            return False
        return True

    async def remove(self, ws: web.WebSocketResponse):
        async with self._lock:
            self._clients.discard(ws)
            self._pong_waiters.pop(ws, None)
            _log.debug("WebSocket client disconnected (%d total)", len(self._clients))

    def acknowledge_pong(self, ws: web.WebSocketResponse, message: bytes):
        waiter = self._pong_waiters.get(ws)
        if waiter is not None and waiter[0] == message:
            waiter[1].set()

    async def _heartbeat(self):
        while True:
            await asyncio.sleep(WS_HEARTBEAT_INTERVAL)
            async with self._lock:
                if not self._clients:
                    self._heartbeat_task = None
                    return
            await self._heartbeat_cycle()

    async def _heartbeat_cycle(self):
        """Check all clients concurrently without holding the client lock."""
        async with self._lock:
            clients = list(self._clients)

        async def check(ws: web.WebSocketResponse):
            waiter: tuple[bytes, asyncio.Event] | None = None
            try:
                async with self._lock:
                    self._ping_sequence += 1
                    payload = str(self._ping_sequence).encode()
                    waiter = (payload, asyncio.Event())
                    self._pong_waiters[ws] = waiter
                await asyncio.wait_for(ws.ping(payload), HEARTBEAT_PING_TIMEOUT)
                await asyncio.wait_for(waiter[1].wait(), HEARTBEAT_PING_TIMEOUT)
            except Exception:
                return ws
            finally:
                async with self._lock:
                    if self._pong_waiters.get(ws) is waiter:
                        self._pong_waiters.pop(ws, None)
            return None

        results = await asyncio.gather(
            *(check(ws) for ws in clients), return_exceptions=True
        )
        dead = {
            ws
            for ws, result in zip(clients, results)
            if isinstance(result, BaseException) or result is not None
        }
        if dead:
            async with self._lock:
                dead.intersection_update(self._clients)
                self._clients.difference_update(dead)
            await asyncio.gather(*(self._close(ws) for ws in dead))

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
                self._clients.difference_update(dead)
                for ws in dead:
                    self._pong_waiters.pop(ws, None)

    @staticmethod
    async def _close(ws: web.WebSocketResponse, **kwargs):
        try:
            await asyncio.wait_for(ws.close(**kwargs), timeout=WS_OPERATION_TIMEOUT)
        except Exception:
            pass

    async def close_all(self):
        """Close all connected WebSocket clients."""
        heartbeat = self._heartbeat_task
        self._heartbeat_task = None
        if heartbeat and heartbeat is not asyncio.current_task():
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
        async with self._lock:
            clients = list(self._clients)
            self._clients.clear()
            self._pong_waiters.clear()
        await asyncio.gather(*(self._close(ws) for ws in clients))
