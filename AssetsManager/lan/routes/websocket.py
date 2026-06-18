"""WebSocket route."""
from aiohttp import web

from AssetsManager.lan.routes._helpers import AUTH_SERVICE_APP_KEY, get_auth_token, get_lan


async def handle_websocket(request):
    from AssetsManager.lan.auth import verify_auth_token, verify_key, verify_token

    lan = get_lan(request)

    token = get_auth_token(request)
    if not token:
        return web.json_response({"error": "Unauthorized"}, status=401)

    authenticated = False
    if lan.access_key_hash and verify_key(token, lan.access_key_hash):
        authenticated = True
    elif lan.token_secret and verify_auth_token(token, lan.token_secret):
        authenticated = True
    elif lan.password_hash and verify_token(token, lan.password_hash):
        authenticated = True
    else:
        auth_service = request.app.get(AUTH_SERVICE_APP_KEY)
        if auth_service:
            user = auth_service.verify_user_token(token)
            if user:
                authenticated = True

    if not authenticated:
        return web.json_response({"error": "Unauthorized"}, status=401)

    ws = web.WebSocketResponse()
    await ws.prepare(request)
    await lan.ws_manager.add(ws)
    try:
        async for msg in ws:
            pass
    finally:
        await lan.ws_manager.remove(ws)
    return ws
