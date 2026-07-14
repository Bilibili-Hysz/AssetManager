"""Auth routes: /api/auth/*."""
from aiohttp import web

from AssetsManager.lan.routes._helpers import get_auth_service, get_lan, get_request_user, set_auth_cookie
from AssetsManager.lan.utils import generate_auth_token


async def handle_login(request):
    lan = get_lan(request)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid request"}, status=400)

    username = body.get("username", "").strip()
    password = body.get("password", "")
    auth_service = get_auth_service(request)

    if username:
        user, err = auth_service.authenticate_user(username, password)
        if user:
            token = auth_service.generate_user_token(user["id"], user["username"], user["role"])
            response = web.json_response({"token": token, "user": user})
            set_auth_cookie(response, token)
            return response
        return web.json_response({"error": err}, status=401)

    if lan.password_hash:
        if auth_service.verify_password(password, lan.password_hash):
            token = auth_service.generate_token(lan.password_hash)
            response = web.json_response({"token": token})
            set_auth_cookie(response, token)
            return response
        return web.json_response({"error": "Invalid password"}, status=401)

    return web.json_response({"token": "no-auth"})


async def handle_register(request):
    lan = get_lan(request)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid request"}, status=400)

    username = body.get("username", "").strip()
    password = body.get("password", "")
    email = body.get("email")
    invite_code = body.get("invite_code")
    auth_service = get_auth_service(request)

    auth_service.init_tables()

    user_id, err = auth_service.register_user(username, password, email=email, invite_code=invite_code)
    if user_id:
        user, auth_err = auth_service.authenticate_user(username, password)
        if not user:
            return web.json_response({"error": auth_err or "Registration failed"}, status=500)
        token = auth_service.generate_user_token(user["id"], user["username"], user["role"])
        lan.invalidate_user_cache()
        response = web.json_response({"token": token, "user": user})
        set_auth_cookie(response, token)
        return response
    return web.json_response({"error": err}, status=400)


async def handle_verify_key(request):
    lan = get_lan(request)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid request"}, status=400)

    key = body.get("key", "").strip()
    if not key:
        return web.json_response({"error": "Key required"}, status=400)
    if not lan.access_key_hash:
        return web.json_response({"error": "No key configured"}, status=400)

    auth_service = get_auth_service(request)
    if auth_service.verify_key(key, lan.access_key_hash):
        token = generate_auth_token(lan.token_secret)
        response = web.json_response({"token": token})
        set_auth_cookie(response, token)
        return response
    return web.json_response({"error": "Invalid key"}, status=401)


async def handle_logout(request):
    response = web.json_response({"ok": True})
    response.del_cookie("lan_token", path="/")
    return response


async def handle_me(request):
    user = get_request_user(request)
    if user:
        return web.json_response({"user": user})
    return web.json_response({"error": "Not authenticated"}, status=401)
