"""Gallery projection routes for the LAN WebUI."""
from __future__ import annotations

import asyncio

from aiohttp import web

from AssetsManager.application.gallery_service import GalleryTraversalLimitError
from AssetsManager.domain.errors import MissingPathError
from AssetsManager.domain.errors import PathEscapeError
from AssetsManager.lan.routes._errors import error_response
from AssetsManager.lan.routes._helpers import (
    get_gallery_service,
    get_lan,
    require_permission,
    validate_path,
)
from AssetsManager.lan.routes._resource_urls import (
    gallery_collection_response,
    gallery_home_response,
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


async def handle_gallery_home(request):
    if not require_permission(request, "browse"):
        return error_response("Browse access required", status=403, code="forbidden")
    lan = get_lan(request)
    service = _service_or_unavailable(request)
    try:
        home = service.get_home_cached(lan.library_root)
        if home is None:
            # A background build is already running; the client shows a
            # building state and retries shortly (large libraries take tens
            # of seconds to project).
            return web.json_response({"building": True}, status=202)
        result = web.json_response(gallery_home_response(home))
        result.headers["Cache-Control"] = "private, no-store"
        return result
    except GalleryTraversalLimitError as exc:
        return error_response(exc)
    except (PermissionError, OSError):
        return error_response("Failed to build gallery", status=500, code="internal_error")


async def handle_gallery_collection(request):
    if not require_permission(request, "browse"):
        return error_response("Browse access required", status=403, code="forbidden")
    lan = get_lan(request)
    service = _service_or_unavailable(request)
    try:
        relative_path = _path_query(request)
        validate_path(lan, relative_path)
        sort = request.query.get("sort", "updated")
        kind = request.query.get("kind", "all")
        if sort not in _ALLOWED_SORTS:
            return error_response("Unsupported gallery sort", status=400, code="bad_request")
        if kind not in _ALLOWED_KINDS:
            return error_response("Unsupported gallery kind", status=400, code="bad_request")
        response = await asyncio.to_thread(
            service.get_collection,
            lan.library_root,
            relative_path,
            sort=sort,
            kind=kind,
        )
    except web.HTTPException:
        raise
    except PathEscapeError:
        return error_response("Path escape detected", status=400, code="path_escape_detected", field="path")
    except MissingPathError:
        return error_response("Collection not found", status=404, code="not_found")
    except GalleryTraversalLimitError as exc:
        return error_response(exc)
    except ValueError as exc:
        return error_response(str(exc), status=400, code="bad_request")
    except (PermissionError, OSError):
        return error_response("Failed to load gallery collection", status=500, code="internal_error")
    if response is None:
        return error_response("Collection not found", status=404, code="not_found")
    result = web.json_response(gallery_collection_response(response))
    result.headers["Cache-Control"] = "private, no-store"
    return result


async def handle_gallery_resolve(request):
    if not require_permission(request, "browse"):
        return error_response("Browse access required", status=403, code="forbidden")
    lan = get_lan(request)
    service = _service_or_unavailable(request)
    try:
        relative_path = _path_query(request)
        validate_path(lan, relative_path)
        response = await asyncio.to_thread(service.resolve, lan.library_root, relative_path)
    except web.HTTPException:
        raise
    except PathEscapeError:
        return error_response("Path escape detected", status=400, code="path_escape_detected", field="path")
    except MissingPathError:
        return error_response("Path not found", status=404, code="not_found")
    except GalleryTraversalLimitError as exc:
        return error_response(exc)
    except ValueError as exc:
        return error_response(str(exc), status=400, code="bad_request")
    except (PermissionError, OSError):
        return error_response("Failed to resolve gallery path", status=500, code="internal_error")
    result = web.json_response(response.to_response())
    result.headers["Cache-Control"] = "private, no-store"
    return result


__all__ = [
    "handle_gallery_collection",
    "handle_gallery_home",
    "handle_gallery_resolve",
]
