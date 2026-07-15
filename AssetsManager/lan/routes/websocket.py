"""WebSocket route."""
from aiohttp import WSMsgType, web

from AssetsManager.lan.routes._helpers import get_lan, get_request_user


async def handle_websocket(request):
    lan = get_lan(request)
    # Authentication is verified once by the application middleware, including
    # HttpOnly-cookie sessions used by browser WebSocket handshakes.
    if "token" in request.query or "key" in request.query or not get_request_user(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    ws = web.WebSocketResponse(autoping=False)
    await ws.prepare(request)
    if not await lan.ws_manager.add(ws):
        return ws
    try:
        async for msg in ws:
            if msg.type is WSMsgType.PONG:
                lan.ws_manager.acknowledge_pong(ws, msg.data)
            elif msg.type is WSMsgType.PING:
                await ws.pong(msg.data)
    finally:
        await lan.ws_manager.remove(ws)
    return ws
