"""Secure original-image preview route: ``GET /api/image?path=...``."""
from __future__ import annotations

import asyncio
from pathlib import Path

from aiohttp import web

from AssetsManager.domain.asset import IMAGE_EXTS
from AssetsManager.lan.routes._errors import error_response
from AssetsManager.lan.routes._helpers import (
    get_lan,
    get_thumbnail_service,
    require_permission,
    validate_path,
)

# SVG is intentionally excluded: it is an active XML document and may contain
# script/external-resource content.  Gallery image previews must be passive data.
_SAFE_IMAGE_EXTS = IMAGE_EXTS - {".svg"}
_IMAGE_CONTENT_TYPES = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "GIF": "image/gif",
    "BMP": "image/bmp",
    "WEBP": "image/webp",
    "TIFF": "image/tiff",
    "ICO": "image/x-icon",
}
# Keep blurred previews bounded like the existing high-resolution thumbnail
# route.  Unblurred assets are delivered as a streamed FileResponse instead.
_BLURRED_PREVIEW_SIZE = 1920
_PRIVATE_PREVIEW_HEADERS = {
    "Cache-Control": "private, no-store",
    "X-Content-Type-Options": "nosniff",
}
_PUBLIC_PREVIEW_HEADERS = {
    "Cache-Control": "public, max-age=3600",
    "X-Content-Type-Options": "nosniff",
}


def _inspect_image(path: Path) -> str | None:
    """Validate the file as a supported raster image and return its MIME type.

    ``Image.verify`` reads image structure without materializing the whole
    raster.  This prevents an image-looking text/executable file from being
    exposed merely because it has an image suffix.
    """
    try:
        from PIL import Image

        with Image.open(path) as image:
            image.verify()
            return _IMAGE_CONTENT_TYPES.get(str(image.format).upper())
    except Exception:
        # Image parsing is a security gate: fail closed for malformed, unknown,
        # truncated, or otherwise unsupported content.
        return None


def _not_found() -> web.Response:
    # Match the existing thumbnail/download route convention: no path details
    # are returned to the caller for missing or disallowed filesystem objects.
    return web.Response(status=404)


async def serve_verified_image(
    request: web.Request,
    target: Path,
    *,
    max_size: int,
    public: bool = False,
) -> web.StreamResponse:
    """Deliver a root-confined, verified raster using thumbnail/blur policy."""
    if not target.is_file() or target.suffix.lower() not in _SAFE_IMAGE_EXTS:
        return _not_found()
    target = target.resolve()
    lan = get_lan(request)
    if not target.is_relative_to(Path(lan.library_root).resolve()):
        return _not_found()
    content_type = await asyncio.to_thread(_inspect_image, target)
    if content_type is None:
        return _not_found()

    svc = get_thumbnail_service(request)
    resolved = await asyncio.to_thread(
        svc.resolve,
        target,
        lan.thumbnail_dir,
        max_size=max_size,
        blur_tags=lan.blur_tags,
        library_root=lan.library_root,
    )
    if not resolved.found or resolved.source_path is None:
        return _not_found()

    headers = _PUBLIC_PREVIEW_HEADERS if public else _PRIVATE_PREVIEW_HEADERS
    if resolved.should_blur:
        processed = await asyncio.to_thread(svc.process_image, target, max_size, True)
        if processed is None:
            return error_response(
                "Failed to process image",
                status=500,
                code="internal_error",
                headers=_PRIVATE_PREVIEW_HEADERS,
            )
        body, processed_content_type = processed
        return web.Response(
            body=body,
            content_type=processed_content_type,
            headers=_PRIVATE_PREVIEW_HEADERS,
        )

    if max_size < 256 or resolved.cache_hit:
        processed = await asyncio.to_thread(svc.process_image, target, max_size, False)
        if processed is not None:
            body, processed_content_type = processed
            return web.Response(body=body, content_type=processed_content_type, headers=headers)

    response = web.FileResponse(target, headers=headers)
    response.headers["Content-Type"] = content_type
    return response


async def handle_image(request: web.Request) -> web.StreamResponse:
    """Stream a safe library image, applying the existing blur policy."""
    if not require_permission(request, "preview"):
        return error_response("Forbidden", status=403, code="forbidden")

    lan = get_lan(request)
    rel_path = request.query.get("path", "")  # query already decoded once
    target = validate_path(lan, rel_path)

    # Resolve/validate the target before handing it to either FileResponse or
    # Pillow.  PathGuard follows symlinks and rejects paths outside the library.
    if not target.is_file() or target.suffix.lower() not in _SAFE_IMAGE_EXTS:
        return _not_found()
    target = target.resolve()
    if not target.is_relative_to(Path(lan.library_root).resolve()):
        return _not_found()

    content_type = await asyncio.to_thread(_inspect_image, target)
    if content_type is None:
        return _not_found()

    svc = get_thumbnail_service(request)
    resolved = await asyncio.to_thread(
        svc.resolve,
        target,
        lan.thumbnail_dir,
        max_size=_BLURRED_PREVIEW_SIZE,
        blur_tags=lan.blur_tags,
        library_root=lan.library_root,
    )
    if not resolved.found or resolved.source_path is None:
        return _not_found()

    if resolved.should_blur:
        # Never fall back to the original when processing a private asset
        # fails: that would turn an operational error into a privacy leak.
        processed = await asyncio.to_thread(
            svc.process_image,
            target,
            _BLURRED_PREVIEW_SIZE,
            True,
        )
        if processed is None:
            return error_response(
                "Failed to process image",
                status=500,
                code="internal_error",
                headers=_PRIVATE_PREVIEW_HEADERS,
            )
        body, processed_content_type = processed
        return web.Response(
            body=body,
            content_type=processed_content_type,
            headers=_PRIVATE_PREVIEW_HEADERS,
        )

    # FileResponse streams the original and does not read it into memory.
    response = web.FileResponse(target, headers=_PRIVATE_PREVIEW_HEADERS)
    # FileResponse guesses from the suffix; use the verified image format so a
    # mismatched extension cannot produce an incorrect Content-Type.
    response.headers["Content-Type"] = content_type
    return response


__all__ = ["handle_image", "serve_verified_image"]
