"""WebSocket route."""
from aiohttp import web

from AssetsManager.lan.routes._helpers import get_lan, get_request_user


async def handle_websocket(request):
    lan = get_lan(request)
    # Authentication is verified once by the application middleware, including
    # HttpOnly-cookie sessions used by browser WebSocket handshakes.
    if "token" in request.query or "key" in request.query or not get_request_user(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    ws = web.WebSocketResponse()
    await ws.prepare(request)
    if not await lan.ws_manager.add(ws):
        return ws
    try:
        async for msg in ws:
            pass
    finally:
        await lan.ws_manager.remove(ws)
    return ws
