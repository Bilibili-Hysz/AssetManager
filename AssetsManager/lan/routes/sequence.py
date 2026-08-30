"""Frame-sequence neighbor lookup: ``GET /api/sequence/neighbors?path=...``.

Read-only companion to the desktop viewer's sequence navigation: LAN/Web
clients resolve the previous/next frame of an image sequence without
fetching any pixel data. Paths are resolved through the shared PathGuard
(``validate_path``), stay library-relative in the response, and the
capability matches the other read surfaces (``browse``, handler-enforced as
defense in depth). The service is pure filesystem detection — no import-time
scanning, no database writes.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from aiohttp import web

from AssetsManager.application.sequence_service import find_neighbors
from AssetsManager.lan.routes._errors import error_response
from AssetsManager.lan.routes._helpers import get_lan, require_permission, validate_path


def _empty_payload() -> dict:
    return {
        "sequence": False,
        "index": None,
        "count": 0,
        "prev": None,
        "next": None,
        "fps": None,
    }


async def handle_sequence_neighbors(request: web.Request) -> web.Response:
    """Return prev/next frame paths when *path* belongs to a frame sequence."""
    if not require_permission(request, "browse"):
        return error_response("Browse access required", status=403, code="forbidden")
    lan = get_lan(request)
    rel_path = request.query.get("path", "")
    if not rel_path:
        return error_response(
            "path query parameter is required", status=400, code="bad_request"
        )
    target = validate_path(lan, rel_path)
    if not target.is_file():
        return error_response("File not found", status=404, code="not_found")
    neighbors = await asyncio.to_thread(find_neighbors, target.parent, target.name)
    if neighbors is None:
        return web.json_response(_empty_payload())

    def library_relative(path: str | None) -> str | None:
        if path is None:
            return None
        try:
            return Path(path).relative_to(Path(lan.library_root).resolve()).as_posix()
        except ValueError:
            return None

    return web.json_response({
        "sequence": True,
        "index": neighbors.index,
        "count": neighbors.count,
        "prev": library_relative(neighbors.prev_path),
        "next": library_relative(neighbors.next_path),
        "fps": neighbors.fps,
    })


__all__ = ["handle_sequence_neighbors"]
