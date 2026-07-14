"""Tag routes: /api/tags, /api/tags/{name}."""
import logging
from urllib.parse import unquote

from aiohttp import web

from AssetsManager.lan.routes._helpers import (
    get_lan, get_tag_service, require_admin, require_permission, validated_existing_key,
)

_log = logging.getLogger(__name__)


async def handle_tags(request):
    if not require_permission(request, "browse"):
        return web.json_response({"error": "Browse access required"}, status=403)
    lan = get_lan(request)
    svc = get_tag_service(request)
    try:
        tags = svc.list_tags(lan.library_root)
    except Exception:
        _log.exception("Failed to list LAN tags")
        return web.json_response({"error": "Failed to list tags"}, status=500)
    return web.json_response({"tags": tags})


async def handle_create_tag(request):
    if not require_admin(request):
        return web.json_response({"error": "Admin access required"}, status=403)
    lan = get_lan(request)
    svc = get_tag_service(request)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid request"}, status=400)
    tag = body.get("tag", "").strip()
    file_path = body.get("file_path", "")
    if not tag or len(tag) > 200:
        return web.json_response({"error": "Invalid tag name"}, status=400)
    if not file_path:
        return web.json_response({"error": "file_path required"}, status=400)
    try:
        key = validated_existing_key(lan, file_path)
        svc.add_tag(lan.library_root, key, tag)
        return web.json_response({"ok": True})
    except web.HTTPException:
        raise
    except Exception:
        _log.exception("Failed to create LAN tag")
        return web.json_response({"error": "Failed to create tag"}, status=500)


async def handle_rename_tag(request):
    if not require_admin(request):
        return web.json_response({"error": "Admin access required"}, status=403)
    lan = get_lan(request)
    svc = get_tag_service(request)
    old_name = unquote(request.match_info["name"])
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid request"}, status=400)
    new_name = body.get("new_name", "").strip()
    if not new_name or len(new_name) > 200:
        return web.json_response({"error": "Invalid tag name"}, status=400)
    try:
        svc.rename_tag(lan.library_root, old_name, new_name)
        return web.json_response({"ok": True})
    except Exception:
        _log.exception("Failed to rename LAN tag")
        return web.json_response({"error": "Failed to rename tag"}, status=500)


async def handle_delete_tag(request):
    if not require_admin(request):
        return web.json_response({"error": "Admin access required"}, status=403)
    lan = get_lan(request)
    svc = get_tag_service(request)
    tag_name = unquote(request.match_info["name"])
    try:
        svc.delete_tag(lan.library_root, tag_name)
        return web.json_response({"ok": True})
    except Exception:
        _log.exception("Failed to delete LAN tag")
        return web.json_response({"error": "Failed to delete tag"}, status=500)
