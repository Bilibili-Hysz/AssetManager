"""Permission-protected command-palette quick search route."""
from __future__ import annotations

import asyncio
import logging

from aiohttp import web

from AssetsManager.lan.routes._helpers import (
    get_lan,
    get_search_service,
    require_permission,
    validate_path,
)
from AssetsManager.lan.routes._resource_urls import thumbnail_url


_log = logging.getLogger(__name__)
_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100
# SVG is an image asset for search/category purposes, but it is not a raster
# preview source and must not be projected as a thumbnail URL.
_THUMBNAIL_EXTS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".ico",
})


def _parse_limit(request) -> int:
    raw_limit = request.query.get("limit")
    if raw_limit is None:
        return _DEFAULT_LIMIT
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer between 1 and 100") from exc
    if limit < 1 or limit > _MAX_LIMIT:
        raise ValueError("limit must be an integer between 1 and 100")
    return limit


def _quick_search_response(result, *, include_thumbnail: bool) -> dict[str, str]:
    response = {
        "name": result.name,
        "path": result.path,
        "type": result.type,
        "extension": result.extension,
        "category": result.category,
    }
    if include_thumbnail and result.type == "file" and result.extension in _THUMBNAIL_EXTS:
        response["thumbnail_url"] = thumbnail_url(result.path)
    return response


async def handle_quicksearch(request):
    """Return a small mixed file/directory result set for the command palette."""
    if not require_permission(request, "browse"):
        return web.json_response({"error": "Browse access required"}, status=403)

    can_preview = require_permission(request, "preview")

    try:
        limit = _parse_limit(request)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)

    query = request.query.get("q", "")
    if not query.strip():
        return web.json_response({"results": []})

    lan = get_lan(request)
    try:
        # Resolve the root through the same LAN path guard used by metadata and
        # file routes before handing it to the application service.
        library_root = validate_path(lan, "")
        results = await asyncio.to_thread(
            get_search_service(request).quick_search,
            library_root,
            query,
            limit=limit,
        )
    except web.HTTPException:
        raise
    except Exception:
        _log.exception("Quick search failed")
        return web.json_response({"error": "Quick search failed"}, status=500)

    return web.json_response(
        {"results": [_quick_search_response(result, include_thumbnail=can_preview) for result in results]}
    )


__all__ = ["handle_quicksearch"]
