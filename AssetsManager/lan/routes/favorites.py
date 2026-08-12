"""Principal-scoped Favorites routes backed by the library SQLite database."""
from __future__ import annotations

import asyncio
import sqlite3

from aiohttp import web

from AssetsManager.application.gallery_service import GalleryTraversalLimitError
from AssetsManager.domain.errors import MissingPathError, PathEscapeError, ValidationError
from AssetsManager.lan.routes._errors import error_response
from AssetsManager.lan.routes._helpers import (
    get_favorite_service,
    get_gallery_service,
    get_lan,
    get_request_principal,
    require_permission,
)

MAX_FAVORITE_PATH_LENGTH = 4_096


def _service_or_unavailable(request, getter, label: str):
    service = getter(request)
    if service is None:
        raise web.HTTPServiceUnavailable(reason=f"{label} service unavailable")
    return service


def _owner_key(request) -> str:
    principal = get_request_principal(request)
    if principal is None:
        raise web.HTTPUnauthorized(reason="Authentication required")
    if principal.kind == "user" and principal.user_profile is not None:
        user_id = principal.user_profile.get("id")
        if user_id is not None:
            return f"user:{user_id}"
    return f"principal:{principal.kind}"


async def _request_path(request) -> str:
    if request.method == "DELETE":
        value = request.query.get("path", "")
    else:
        try:
            body = await request.json()
        except Exception:
            raise web.HTTPBadRequest(reason="Invalid request")
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(reason="Invalid request")
        value = body.get("path", "")
    if not isinstance(value, str) or not value.strip():
        raise web.HTTPBadRequest(reason="path required")
    value = value.strip()
    if len(value) > MAX_FAVORITE_PATH_LENGTH:
        raise web.HTTPBadRequest(reason="Path is too long")
    return value


def _error_response(error: Exception) -> web.Response:
    """Favorites-specific messages over the canonical error contract."""
    if isinstance(error, MissingPathError):
        return error_response("Favorite target not found", status=404, code="not_found")
    if isinstance(error, (PathEscapeError, ValidationError, GalleryTraversalLimitError)):
        return error_response(error)
    if isinstance(error, ValueError):
        return error_response(str(error), status=400, code="bad_request")
    return error_response("Favorites operation failed", status=500, code="internal_error")


async def handle_favorites(request):
    if not require_permission(request, "browse"):
        return web.json_response({"error": "Browse access required"}, status=403)
    lan = get_lan(request)
    favorite_service = _service_or_unavailable(
        request, get_favorite_service, "Favorites"
    )
    gallery_service = _service_or_unavailable(
        request, get_gallery_service, "Gallery"
    )
    try:
        paths = await asyncio.to_thread(
            favorite_service.list_paths, lan.library_root, _owner_key(request)
        )
        entries = await asyncio.to_thread(
            gallery_service.describe_entries, lan.library_root, paths
        )
    except (GalleryTraversalLimitError, sqlite3.Error, RuntimeError, ValueError) as exc:
        return _error_response(exc)
    response = web.json_response({"favorites": entries})
    response.headers["Cache-Control"] = "private, no-store"
    return response


async def handle_add_favorite(request):
    if not require_permission(request, "browse"):
        return web.json_response({"error": "Browse access required"}, status=403)
    lan = get_lan(request)
    service = _service_or_unavailable(request, get_favorite_service, "Favorites")
    try:
        relative_path = await _request_path(request)
        path, changed = await asyncio.to_thread(
            service.add, lan.library_root, _owner_key(request), relative_path
        )
    except web.HTTPException:
        raise
    except (MissingPathError, PathEscapeError, ValidationError, sqlite3.Error, RuntimeError, ValueError) as exc:
        return _error_response(exc)
    return web.json_response({"ok": True, "path": path, "favorite": True, "changed": changed})


async def handle_remove_favorite(request):
    if not require_permission(request, "browse"):
        return web.json_response({"error": "Browse access required"}, status=403)
    lan = get_lan(request)
    service = _service_or_unavailable(request, get_favorite_service, "Favorites")
    try:
        relative_path = await _request_path(request)
        path, changed = await asyncio.to_thread(
            service.remove, lan.library_root, _owner_key(request), relative_path
        )
    except web.HTTPException:
        raise
    except (PathEscapeError, ValidationError, sqlite3.Error, RuntimeError, ValueError) as exc:
        return _error_response(exc)
    return web.json_response({"ok": True, "path": path, "favorite": False, "changed": changed})


__all__ = [
    "handle_add_favorite",
    "handle_favorites",
    "handle_remove_favorite",
]
