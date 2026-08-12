"""Tag routes: /api/tags, /api/tags/remove, /api/tags/{name}."""
import logging

from aiohttp import web

from AssetsManager.domain.errors import DuplicateError, ValidationError
from AssetsManager.lan.dto import TagResponse
from AssetsManager.lan.routes._errors import error_response
from AssetsManager.lan.routes._helpers import (
    get_lan, get_tag_service, require_admin, require_permission, validated_existing_key,
)

_log = logging.getLogger(__name__)


async def handle_tags(request):
    if not require_permission(request, "browse"):
        return error_response("Browse access required", status=403, code="forbidden")
    lan = get_lan(request)
    svc = get_tag_service(request)
    try:
        tags = svc.list_tags(lan.library_root)
    except Exception:
        _log.exception("Failed to list LAN tags")
        return error_response("Failed to list tags", status=500, code="internal_error")
    return web.json_response({"tags": [TagResponse.from_record(tag).to_dict() for tag in tags]})


async def handle_create_tag(request):
    if not require_admin(request):
        return error_response("Admin access required", status=403, code="forbidden")
    lan = get_lan(request)
    svc = get_tag_service(request)
    try:
        body = await request.json()
    except Exception:
        return error_response("Invalid request", status=400, code="bad_request")
    try:
        tag = svc.validate_tag_name(body.get("tag", ""))
    except ValidationError:
        return error_response("Invalid tag name", status=400, code="bad_request")
    file_path = body.get("file_path", "")
    if not file_path:
        return error_response("file_path required", status=400, code="bad_request")
    try:
        key = validated_existing_key(lan, file_path)
        svc.add_tag(lan.library_root, key, tag)
        return web.json_response({"ok": True})
    except web.HTTPException:
        raise
    except ValidationError:
        return error_response("Invalid tag name", status=400, code="bad_request")
    except Exception:
        _log.exception("Failed to create LAN tag")
        return error_response("Failed to create tag", status=500, code="internal_error")


async def handle_remove_tag(request):
    """Remove one tag from one existing library path (admin/local UI only)."""
    if not require_admin(request):
        return error_response("Admin access required", status=403, code="forbidden")

    lan = get_lan(request)
    svc = get_tag_service(request)
    try:
        body = await request.json()
    except Exception:
        return error_response("Invalid request", status=400, code="bad_request")
    if not isinstance(body, dict):
        return error_response("Invalid request", status=400, code="bad_request")

    try:
        tag = svc.validate_tag_name(body.get("tag", ""))
    except ValidationError:
        return error_response("Invalid tag name", status=400, code="bad_request")

    file_path = body.get("file_path", "")
    if not isinstance(file_path, str) or not file_path:
        return error_response("file_path required", status=400, code="bad_request")

    try:
        key = validated_existing_key(lan, file_path)
        svc.remove_tag(lan.library_root, key, tag)
        return web.json_response({"ok": True})
    except web.HTTPException:
        raise
    except ValidationError:
        return error_response("Invalid tag name", status=400, code="bad_request")
    except Exception:
        _log.exception("Failed to remove LAN tag")
        return error_response("Failed to remove tag", status=500, code="internal_error")


async def handle_rename_tag(request):
    if not require_admin(request):
        return error_response("Admin access required", status=403, code="forbidden")
    lan = get_lan(request)
    svc = get_tag_service(request)
    old_name = request.match_info["name"]  # aiohttp decodes match_info once
    try:
        body = await request.json()
    except Exception:
        return error_response("Invalid request", status=400, code="bad_request")
    try:
        new_name = svc.validate_tag_name(body.get("new_name", ""), field="new_name")
    except ValidationError:
        return error_response("Invalid tag name", status=400, code="bad_request")
    try:
        svc.rename_tag(lan.library_root, old_name, new_name)
        return web.json_response({"ok": True})
    except ValidationError:
        return error_response("Invalid tag name", status=400, code="bad_request")
    except DuplicateError:
        return error_response(
            "A tag with this name already exists", status=409, code="conflict"
        )
    except Exception:
        _log.exception("Failed to rename LAN tag")
        return error_response("Failed to rename tag", status=500, code="internal_error")


async def handle_delete_tag(request):
    if not require_admin(request):
        return error_response("Admin access required", status=403, code="forbidden")
    lan = get_lan(request)
    svc = get_tag_service(request)
    tag_name = request.match_info["name"]  # aiohttp decodes match_info once
    try:
        svc.delete_tag(lan.library_root, tag_name)
        return web.json_response({"ok": True})
    except Exception:
        _log.exception("Failed to delete LAN tag")
        return error_response("Failed to delete tag", status=500, code="internal_error")
