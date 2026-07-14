"""User and invite routes: /api/users/*, /api/invites/*."""
from aiohttp import web

from AssetsManager.lan.routes._helpers import get_auth_service, get_lan, get_services, require_admin


async def handle_users(request):
    if not require_admin(request):
        return web.json_response({"error": "Admin access required"}, status=403)
    auth_service = get_auth_service(request)
    users = auth_service.list_users()
    for u in users:
        u.pop("password_hash", None)
    return web.json_response({"users": users})


async def handle_toggle_user(request):
    if not require_admin(request):
        return web.json_response({"error": "Admin access required"}, status=403)
    auth_service = get_auth_service(request)

    try:
        user_id = int(request.match_info.get("id", ""))
    except ValueError:
        return web.json_response({"error": "Invalid user ID"}, status=400)
    try:
        body = await request.json()
    except Exception:
        body = {}
    active = body.get("active", True)

    if active:
        ok = auth_service.activate_user(user_id)
    else:
        ok = auth_service.deactivate_user(user_id)
    if ok:
        get_lan(request).invalidate_user_cache()
    return web.json_response({"ok": ok})


async def handle_invites(request):
    if not require_admin(request):
        return web.json_response({"error": "Admin access required"}, status=403)
    auth_service = get_auth_service(request)

    codes = auth_service.list_invite_codes()
    return web.json_response({"invites": codes})


async def handle_create_invite(request):
    user = require_admin(request)
    if not user:
        return web.json_response({"error": "Admin access required"}, status=403)
    auth_service = get_auth_service(request)

    code = auth_service.generate_invite_code(created_by=user.get("username", "admin"))
    if code:
        return web.json_response({"code": code})
    return web.json_response({"error": "Failed to generate code"}, status=500)


async def handle_revoke_invite(request):
    if not require_admin(request):
        return web.json_response({"error": "Admin access required"}, status=403)
    auth_service = get_auth_service(request)

    code = request.match_info.get("code", "")
    ok = auth_service.revoke_invite_code(code)
    return web.json_response({"ok": ok})


async def handle_activity(request):
    if not require_admin(request):
        return web.json_response({"error": "Admin access required"}, status=403)
    return web.json_response({"activities": get_services(request).activity_log.recent(20)})


async def handle_online_users(request):
    if not require_admin(request):
        return web.json_response({"error": "Admin access required"}, status=403)
    return web.json_response({"users": get_services(request).online_users.list_all()})
