"""Gallery projection routes for the LAN WebUI."""
from __future__ import annotations

import asyncio

from aiohttp import web

from AssetsManager.application.gallery_service import GalleryTraversalLimitError
from AssetsManager.domain.errors import MissingPathError as DomainMissingPathError
from AssetsManager.domain.errors import PathEscapeError as DomainPathEscapeError
from AssetsManager.lan.path_guard import MissingPathError as LanMissingPathError
from AssetsManager.lan.path_guard import PathEscapeError as LanPathEscapeError
from AssetsManager.lan.routes._helpers import (
    get_gallery_service,
    get_lan,
    require_permission,
    validate_path,
)

MAX_GALLERY_PATH_LENGTH = 4_096
_ALLOWED_KINDS = {"all", "artwork", "works"}
_ALLOWED_SORTS = {"updated", "name"}


def _path_query(request) -> str:
    raw = request.query.get("path", "")
    path = raw  # URLSearchParams already decoded the query once
    if len(path) > MAX_GALLERY_PATH_LENGTH:
        raise web.HTTPBadRequest(reason="Path is too long")
    return path


def _service_or_unavailable(request):
    service = get_gallery_service(request)
    if service is None:
        raise web.HTTPServiceUnavailable(reason="Gallery service unavailable")
    return service


def _traversal_response(error: GalleryTraversalLimitError) -> web.Response:
    return web.json_response({"error": str(error)}, status=error.status)


async def handle_gallery_home(request):
    if not require_permission(request, "browse"):
        return web.json_response({"error": "Browse access required"}, status=403)
    lan = get_lan(request)
    service = _service_or_unavailable(request)
    try:
        response = await asyncio.to_thread(service.get_home, lan.library_root)
    except GalleryTraversalLimitError as exc:
        return _traversal_response(exc)
    except (PermissionError, OSError):
        return web.json_response({"error": "Failed to build gallery"}, status=500)
    result = web.json_response(response.to_response())
    result.headers["Cache-Control"] = "private, no-store"
    return result


async def handle_gallery_collection(request):
    if not require_permission(request, "browse"):
        return web.json_response({"error": "Browse access required"}, status=403)
    lan = get_lan(request)
    service = _service_or_unavailable(request)
    try:
        relative_path = _path_query(request)
        validate_path(lan, relative_path)
        sort = request.query.get("sort", "updated")
        kind = request.query.get("kind", "all")
        if sort not in _ALLOWED_SORTS:
            return web.json_response({"error": "Unsupported gallery sort"}, status=400)
        if kind not in _ALLOWED_KINDS:
            return web.json_response({"error": "Unsupported gallery kind"}, status=400)
        response = await asyncio.to_thread(
            service.get_collection,
            lan.library_root,
            relative_path,
            sort=sort,
            kind=kind,
        )
    except web.HTTPException:
        raise
    except (LanPathEscapeError, DomainPathEscapeError):
        return web.json_response({"error": "Path escape detected"}, status=400)
    except (LanMissingPathError, DomainMissingPathError):
        return web.json_response({"error": "Collection not found"}, status=404)
    except GalleryTraversalLimitError as exc:
        return _traversal_response(exc)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except (PermissionError, OSError):
        return web.json_response({"error": "Failed to load gallery collection"}, status=500)
    if response is None:
        return web.json_response({"error": "Collection not found"}, status=404)
    result = web.json_response(response.to_response())
    result.headers["Cache-Control"] = "private, no-store"
    return result


async def handle_gallery_resolve(request):
    if not require_permission(request, "browse"):
        return web.json_response({"error": "Browse access required"}, status=403)
    lan = get_lan(request)
    service = _service_or_unavailable(request)
    try:
        relative_path = _path_query(request)
        validate_path(lan, relative_path)
        response = await asyncio.to_thread(service.resolve, lan.library_root, relative_path)
    except web.HTTPException:
        raise
    except (LanPathEscapeError, DomainPathEscapeError):
        return web.json_response({"error": "Path escape detected"}, status=400)
    except (LanMissingPathError, DomainMissingPathError):
        return web.json_response({"error": "Path not found"}, status=404)
    except GalleryTraversalLimitError as exc:
        return _traversal_response(exc)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except (PermissionError, OSError):
        return web.json_response({"error": "Failed to resolve gallery path"}, status=500)
    result = web.json_response(response.to_response())
    result.headers["Cache-Control"] = "private, no-store"
    return result


__all__ = [
    "handle_gallery_collection",
    "handle_gallery_home",
    "handle_gallery_resolve",
]
