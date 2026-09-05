"""Secure original-image preview route: ``GET /api/image?path=...``."""
from __future__ import annotations

import asyncio
from pathlib import Path

from aiohttp import web

from AssetsManager.domain.asset import IMAGE_EXTS
from AssetsManager.lan.path_guard import PathGuardError, assert_under_root
from AssetsManager.lan.routes._errors import error_response
from AssetsManager.lan.safe_open import MAX_INLINE_READ_BYTES, SafeOpenError, read_safe_file
from AssetsManager.application.media.decoders import decoder_for
from AssetsManager.application.thumbnail_service import finalize_pil_image, process_image_snapshot
from AssetsManager.lan.routes._helpers import (
    BLURRED_PREVIEW_SIZE,
    MEDIA_CACHE_HEADERS,
    PRIVATE_PREVIEW_HEADERS,
    PUBLIC_PREVIEW_HEADERS,
    build_media_etag,
    etag_matches,
    get_lan,
    get_thumbnail_service,
    media_not_modified,
    require_permission,
    serve_blur_gated_raster,
    should_blur_target,
    validate_path,
)

# SVG is intentionally excluded: it is an active XML document and may contain
# script/external-resource content.  Gallery image previews must be passive data.
_SAFE_IMAGE_EXTS = IMAGE_EXTS - {".svg"}
# Image validation and optional blur processing currently require a bytes
# snapshot.  Bound that snapshot so a crafted large image cannot exhaust the
# LAN server process; decoded/thumbnail output remains separately bounded by
# its max-dimension setting.
MAX_IMAGE_SOURCE_BYTES = MAX_INLINE_READ_BYTES
_IMAGE_CONTENT_TYPES = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "GIF": "image/gif",
    "BMP": "image/bmp",
    "WEBP": "image/webp",
    "TIFF": "image/tiff",
    "ICO": "image/x-icon",
}


def _inspect_image_bytes(body: bytes) -> str | None:
    try:
        from io import BytesIO
        from PIL import Image
        with BytesIO(body) as stream:
            with Image.open(stream) as image:
                image.verify()
                return _IMAGE_CONTENT_TYPES.get(str(image.format).upper())
    except Exception:
        return None


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


def _media_source_etag(request: web.Request, target: Path, *, blurred: bool) -> str:
    """Source-identity validator for /api/image: mtime+size plus the
    normalized query, with the blur decision bound in so a policy flip
    invalidates cached copies."""
    try:
        source_stat = target.stat()
    except OSError:
        source_stat = None
    return build_media_etag(
        "image",
        source_stat.st_mtime_ns if source_stat else None,
        source_stat.st_size if source_stat else None,
        blurred,
        query=dict(request.query),
    )


async def _serve_decoded_raster(
    request: web.Request,
    target: Path,
    media_decoder,
    *,
    max_size: int,
    public: bool = False,
    etag: str | None = None,
) -> web.StreamResponse:
    """Deliver a decoder-backed format (RAW/PSD) through the WEBP pipeline.

    The successful decode IS the content gate: a file that merely carries a
    media suffix fails ``decode_bytes`` and gets the same fail-closed 404 as
    the Pillow ``verify`` gate below. RAW/PSD originals are not
    browser-renderable rasters, so the original-bytes delivery paths never
    apply here — the response is always the shared WEBP pipeline output.
    """
    lan = get_lan(request)
    try:
        source_body, _identity = await asyncio.to_thread(
            read_safe_file,
            lan.library_root,
            target,
            max_bytes=MAX_IMAGE_SOURCE_BYTES,
        )
    except (SafeOpenError, OSError, ValueError):
        return _not_found()
    pil = await asyncio.to_thread(
        media_decoder.decode_bytes, source_body, max_dim=max_size,
    )
    if pil is None:
        return _not_found()
    should_blur = await should_blur_target(request, target)
    processed = await asyncio.to_thread(finalize_pil_image, pil, max_size, should_blur)
    if processed is None:
        # Privacy invariant from serve_blur_gated_raster: a processing failure
        # is a 500 — the original is never served for a blurred asset.
        return error_response(
            "Failed to process image", status=500, code="internal_error",
            headers=PRIVATE_PREVIEW_HEADERS,
        )
    body, content_type = processed
    if should_blur:
        headers = PRIVATE_PREVIEW_HEADERS
    elif public:
        headers = PUBLIC_PREVIEW_HEADERS
    else:
        # LAN image route: private hour-cache revalidated via If-None-Match.
        headers = {**MEDIA_CACHE_HEADERS, **({"ETag": etag} if etag else {})}
    return web.Response(body=body, content_type=content_type, headers=headers)


async def serve_verified_image(
    request: web.Request,
    target: Path,
    *,
    max_size: int,
    public: bool = False,
) -> web.StreamResponse:
    """Deliver a root-confined, verified raster using thumbnail/blur policy."""
    media_decoder = (
        None
        if target.suffix.lower() in _SAFE_IMAGE_EXTS
        else decoder_for(target.suffix)
    )
    if not target.is_file() or (
        target.suffix.lower() not in _SAFE_IMAGE_EXTS and media_decoder is None
    ):
        return _not_found()
    lan = get_lan(request)
    try:
        target = assert_under_root(lan.library_root, target)
    except PathGuardError:
        return _not_found()
    if media_decoder is not None:
        return await _serve_decoded_raster(
            request, target, media_decoder, max_size=max_size, public=public,
        )
    try:
        source_body, _source_identity = await asyncio.to_thread(
            read_safe_file,
            lan.library_root,
            target,
            max_bytes=MAX_IMAGE_SOURCE_BYTES,
        )
    except (SafeOpenError, OSError, ValueError):
        return _not_found()
    content_type = await asyncio.to_thread(_inspect_image_bytes, source_body)
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

    if resolved.should_blur:
        processed = await asyncio.to_thread(
            process_image_snapshot, svc, target, source_body, max_size, True,
        )
        if processed is None:
            return error_response(
                "Failed to process image", status=500, code="internal_error",
                headers=PRIVATE_PREVIEW_HEADERS,
            )
        body, processed_content_type = processed
        return web.Response(
            body=body,
            content_type=processed_content_type,
            headers=PRIVATE_PREVIEW_HEADERS,
        )

    headers = PUBLIC_PREVIEW_HEADERS if public else PRIVATE_PREVIEW_HEADERS
    if max_size < 256 or resolved.cache_hit:
        processed = await asyncio.to_thread(
            process_image_snapshot, svc, target, source_body, max_size, False,
        )
        if processed is not None:
            body, processed_content_type = processed
            return web.Response(body=body, content_type=processed_content_type, headers=headers)

    return web.Response(body=source_body, content_type=content_type, headers=headers)


async def handle_image(request: web.Request) -> web.StreamResponse:
    """Stream a safe library image, applying the existing blur policy."""
    if not require_permission(request, "preview"):
        return error_response("Forbidden", status=403, code="forbidden")

    lan = get_lan(request)
    rel_path = request.query.get("path", "")  # query already decoded once
    target = validate_path(lan, rel_path)

    # Re-check containment after the final resolution before handing the path
    # to FileResponse or Pillow.  PathGuard resolves symlinks and rejects
    # escapes, but the on-disk entry may have been swapped since; the single
    # shared predicate keeps this TOCTOU defense out of route-local logic.
    media_decoder = (
        None
        if target.suffix.lower() in _SAFE_IMAGE_EXTS
        else decoder_for(target.suffix)
    )
    if not target.is_file() or (
        target.suffix.lower() not in _SAFE_IMAGE_EXTS and media_decoder is None
    ):
        return _not_found()
    try:
        target = assert_under_root(lan.library_root, target)
    except PathGuardError:
        return _not_found()

    if media_decoder is not None:
        # The blur decision must precede the validator so a 304 can never
        # mask newly blurred content.
        if await should_blur_target(request, target):
            return await _serve_decoded_raster(
                request, target, media_decoder, max_size=BLURRED_PREVIEW_SIZE,
            )
        etag = _media_source_etag(request, target, blurred=False)
        if etag_matches(request, etag):
            return media_not_modified(etag)
        return await _serve_decoded_raster(
            request, target, media_decoder, max_size=BLURRED_PREVIEW_SIZE, etag=etag,
        )

    content_type = await asyncio.to_thread(_inspect_image, target)
    if content_type is None:
        return _not_found()

    should_blur = await should_blur_target(request, target)
    etag = None
    if not should_blur:
        # Revalidation lands after permission/PathGuard/blur checks and
        # before the file read: a hit skips the decode and transfer.
        etag = _media_source_etag(request, target, blurred=False)
        if etag_matches(request, etag):
            return media_not_modified(etag)
    return await serve_blur_gated_raster(
        request,
        target,
        should_blur=should_blur,
        content_type=content_type,
        max_size=BLURRED_PREVIEW_SIZE,
        etag=etag,
    )


__all__ = ["handle_image", "serve_verified_image"]
