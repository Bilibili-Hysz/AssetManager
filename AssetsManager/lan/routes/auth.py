"""Auth routes: /api/auth/*."""
from aiohttp import web

from AssetsManager.lan.dto import UserResponse
from AssetsManager.lan.routes._errors import error_response
from AssetsManager.lan.routes._helpers import get_auth_service, get_auth_token, get_lan, get_request_principal, set_auth_cookie
from AssetsManager.lan.utils import generate_auth_token


def _record_activity(request, action, details, username=None):
    services = getattr(get_lan(request), "services", None)
    activity_log = getattr(services, "activity_log", None)
    if activity_log is not None:
        activity_log.add(username, action, details, ip=request.remote or "unknown")


async def handle_login(request):
    lan = get_lan(request)
    try:
        body = await request.json()
    except Exception:
        return error_response("Invalid request", status=400, code="bad_request")

    username = body.get("username", "").strip()
    password = body.get("password", "")
    auth_service = get_auth_service(request)

    if username:
        user, err = auth_service.authenticate_user(username, password)
        if user:
            token = auth_service.generate_user_token(user["id"], user["username"], user["role"])
            response = web.json_response({"user": UserResponse.from_record(user).to_dict()})
            set_auth_cookie(response, token, secure=lan.ssl_active)
            _record_activity(request, "login", "signed in", user["username"])
            return response
        return error_response(err, status=401, code="unauthorized")

    if lan.password_hash:
        if auth_service.verify_password(password, lan.password_hash):
            token = auth_service.generate_token(lan.password_hash)
            response = web.json_response({"ok": True})
            set_auth_cookie(response, token, secure=lan.ssl_active)
            _record_activity(request, "login", "signed in")
            return response
        return error_response("Invalid password", status=401, code="unauthorized")

    return error_response("Credentials required", status=400, code="bad_request")


async def handle_register(request):
    lan = get_lan(request)
    try:
        body = await request.json()
    except Exception:
        return error_response("Invalid request", status=400, code="bad_request")

    username = body.get("username", "").strip()
    password = body.get("password", "")
    email = body.get("email")
    invite_code = body.get("invite_code")
    auth_service = get_auth_service(request)

    user_id, err = auth_service.register_user(username, password, email=email, invite_code=invite_code)
    if user_id:
        user, auth_err = auth_service.authenticate_user(username, password)
        if not user:
            return error_response(auth_err or "Registration failed", status=500, code="internal_error")
        token = auth_service.generate_user_token(user["id"], user["username"], user["role"])
        lan.invalidate_user_cache()
        response = web.json_response({"user": UserResponse.from_record(user).to_dict()})
        set_auth_cookie(response, token, secure=lan.ssl_active)
        return response
    return error_response(err, status=400, code="bad_request")


async def handle_verify_key(request):
    lan = get_lan(request)
    try:
        body = await request.json()
    except Exception:
        return error_response("Invalid request", status=400, code="bad_request")

    key = body.get("key", "").strip()
    if not key:
        return error_response("Key required", status=400, code="bad_request")
    if not lan.access_key_hash:
        return error_response("No key configured", status=400, code="bad_request")

    auth_service = get_auth_service(request)
    if auth_service.verify_key(key, lan.access_key_hash):
        token = generate_auth_token(lan.local_ui_auth_secret)
        response = web.json_response({"ok": True})
        set_auth_cookie(response, token, secure=lan.ssl_active)
        _record_activity(request, "login", "verified access key")
        return response
    return error_response("Invalid key", status=401, code="unauthorized")


async def handle_logout(request):
    response = web.json_response({"ok": True})
    response.del_cookie("lan_token", path="/")
    token = get_auth_token(request)
    if token:
        get_lan(request).revoke_auth_token(token)
    return response


async def handle_me(request):
    principal = get_request_principal(request)
    if principal is not None:
        payload = {"principal": principal.to_dict()}
        if principal.kind == "user":
            if principal.user_profile is not None:
                payload["user"] = dict(principal.user_profile)
        return web.json_response(payload)
    return error_response("Not authenticated", status=401, code="unauthorized")
