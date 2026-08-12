"""User and invite routes: /api/users/*, /api/invites/*."""
from aiohttp import web

from AssetsManager.lan.dto import InviteResponse, UserResponse
from AssetsManager.lan.routes._errors import error_response
from AssetsManager.lan.routes._helpers import get_auth_service, get_lan, get_services, require_admin


async def handle_users(request):
    if not require_admin(request):
        return error_response("Admin access required", status=403, code="forbidden")
    auth_service = get_auth_service(request)
    users = auth_service.list_users()
    return web.json_response({"users": [UserResponse.from_record(u).to_dict() for u in users]})


async def handle_toggle_user(request):
    if not require_admin(request):
        return error_response("Admin access required", status=403, code="forbidden")
    auth_service = get_auth_service(request)

    try:
        user_id = int(request.match_info.get("id", ""))
    except ValueError:
        return error_response("Invalid user ID", status=400, code="bad_request")
    try:
        body = await request.json()
    except Exception:
        body = {}
    active = body.get("active", True)

    if active:
        ok = auth_service.activate_user(user_id)
    else:
        ok = await get_lan(request).ws_manager.revoke_authority(
            ("user", user_id),
            lambda: auth_service.deactivate_user(user_id),
        )
    if ok:
        get_lan(request).invalidate_user_cache()
    return web.json_response({"ok": ok})


async def handle_invites(request):
    if not require_admin(request):
        return error_response("Admin access required", status=403, code="forbidden")
    auth_service = get_auth_service(request)

    codes = auth_service.list_invite_codes()
    return web.json_response({"invites": [InviteResponse.from_record(c).to_dict() for c in codes]})


async def handle_create_invite(request):
    user = require_admin(request)
    if not user:
        return error_response("Admin access required", status=403, code="forbidden")
    auth_service = get_auth_service(request)

    code = auth_service.generate_invite_code(created_by=user.display_name)
    if code:
        return web.json_response({"code": code})
    return error_response("Failed to generate code", status=500, code="internal_error")


async def handle_revoke_invite(request):
    if not require_admin(request):
        return error_response("Admin access required", status=403, code="forbidden")
    auth_service = get_auth_service(request)

    code = request.match_info.get("code", "")
    ok = auth_service.revoke_invite_code(code)
    return web.json_response({"ok": ok})


async def handle_activity(request):
    if not require_admin(request):
        return error_response("Admin access required", status=403, code="forbidden")
    return web.json_response({"activities": get_services(request).activity_log.recent(20)})


async def handle_online_users(request):
    if not require_admin(request):
        return error_response("Admin access required", status=403, code="forbidden")
    return web.json_response({"users": get_services(request).online_users.list_all()})
