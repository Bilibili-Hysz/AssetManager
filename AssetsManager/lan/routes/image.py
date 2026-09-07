"""Secure original-image preview route: ``GET /api/image?path=...``."""
from __future__ import annotations

import asyncio
from pathlib import Path

from aiohttp import web

from AssetsManager.domain.asset import IMAGE_EXTS
from AssetsManager.lan.path_guard import PathGuardError, assert_under_root
from AssetsManager.lan.routes._errors import error_response
from AssetsManager.lan.safe_open import FileIdentity, MAX_INLINE_READ_BYTES, SafeOpenError, read_safe_file
from AssetsManager.application.media.decoders import decoder_for
from AssetsManager.application.thumbnail_service import finalize_pil_image, process_image_snapshot
from AssetsManager.lan.routes._helpers import (
    BLURRED_PREVIEW_SIZE,
    MEDIA_CACHE_HEADERS,
    PRIVATE_PREVIEW_HEADERS,
    PUBLIC_PREVIEW_HEADERS,
    build_snapshot_media_etag,
    etag_matches,
    get_lan,
    get_thumbnail_service,
    inspect_raster_bytes as _inspect_image_bytes,
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


async def _blurred_snapshot_response(
    request: web.Request,
    target: Path,
    source_body: bytes,
    source_identity: FileIdentity,
    max_size: int,
) -> web.StreamResponse:
    """Render captured source bytes under the current blur policy."""
    svc = get_thumbnail_service(request)
    processed = await asyncio.to_thread(
        process_image_snapshot,
        svc,
        target,
        source_body,
        max_size,
        True,
        source_identity.as_tuple(),
    )
    if processed is None:
        return error_response(
            "Failed to process image", status=500, code="internal_error",
            headers=PRIVATE_PREVIEW_HEADERS,
        )
    body, content_type = processed
    return web.Response(
        body=body,
        content_type=content_type,
        headers=PRIVATE_PREVIEW_HEADERS,
    )


def _not_found() -> web.Response:
    # Match the existing thumbnail/download route convention: no path details
    # are returned to the caller for missing or disallowed filesystem objects.
    return web.Response(status=404)


async def _serve_decoded_raster(
    request: web.Request,
    target: Path,
    media_decoder,
    *,
    source_body: bytes,
    source_identity: FileIdentity,
    max_size: int,
    public: bool = False,
) -> web.StreamResponse:
    """Deliver a decoder-backed format (RAW/PSD) through the WEBP pipeline.

    The successful decode IS the content gate: a file that merely carries a
    media suffix fails ``decode_bytes`` and gets the same fail-closed 404 as
    the Pillow ``verify`` gate below. RAW/PSD originals are not
    browser-renderable rasters, so the original-bytes delivery paths never
    apply here — the response is always the shared WEBP pipeline output.
    """
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
    etag = None
    if not should_blur:
        if not public:
            etag = await asyncio.to_thread(
                build_snapshot_media_etag,
                "image",
                source_identity,
                body,
                content_type,
                query=dict(request.query),
            )
        # Hashing occurs before the final policy decision so this await remains
        # adjacent to an eventual unblurred response or 304.
        if await should_blur_target(request, target):
            # ``finalize_pil_image`` owns and closes ``pil``. Decode the same
            # admitted bytes again so a late policy change cannot become 500.
            pil = await asyncio.to_thread(
                media_decoder.decode_bytes, source_body, max_dim=max_size,
            )
            processed = (
                await asyncio.to_thread(finalize_pil_image, pil, max_size, True)
                if pil is not None
                else None
            )
            if processed is None:
                return error_response(
                    "Failed to process image", status=500, code="internal_error",
                    headers=PRIVATE_PREVIEW_HEADERS,
                )
            body, content_type = processed
            should_blur = True
    if should_blur:
        headers = PRIVATE_PREVIEW_HEADERS
    elif public:
        headers = PUBLIC_PREVIEW_HEADERS
    else:
        assert etag is not None
        if etag_matches(request, etag):
            return media_not_modified(etag)
        headers = {**MEDIA_CACHE_HEADERS, "ETag": etag}
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
    try:
        source_body, source_identity = await asyncio.to_thread(
            read_safe_file,
            lan.library_root,
            target,
            max_bytes=MAX_IMAGE_SOURCE_BYTES,
        )
    except (SafeOpenError, OSError, ValueError):
        return _not_found()
    if media_decoder is not None:
        return await _serve_decoded_raster(
            request,
            target,
            media_decoder,
            source_body=source_body,
            source_identity=source_identity,
            max_size=max_size,
            public=public,
        )
    content_type = await asyncio.to_thread(_inspect_image_bytes, source_body)
    if content_type is None:
        return _not_found()

    should_blur = await should_blur_target(request, target)
    if should_blur:
        return await _blurred_snapshot_response(
            request, target, source_body, source_identity, max_size,
        )

    headers = PUBLIC_PREVIEW_HEADERS if public else PRIVATE_PREVIEW_HEADERS
    if max_size < 256:
        svc = get_thumbnail_service(request)
        processed = await asyncio.to_thread(
            process_image_snapshot, svc, target, source_body, max_size, False,
        )
        if processed is not None:
            body, processed_content_type = processed
            # Re-evaluate after processing: the source bytes remain the same,
            # but a policy change must never expose the unblurred render.
            if await should_blur_target(request, target):
                return await _blurred_snapshot_response(
                    request, target, source_body, source_identity, max_size,
                )
            return web.Response(body=body, content_type=processed_content_type, headers=headers)

    # Last blur-policy await before direct public/private source-byte delivery.
    if await should_blur_target(request, target):
        return await _blurred_snapshot_response(
            request, target, source_body, source_identity, max_size,
        )
    return web.Response(body=source_body, content_type=content_type, headers=headers)


async def handle_image(request: web.Request) -> web.StreamResponse:
    """Stream a safe library image, applying the existing blur policy."""
    if not require_permission(request, "preview"):
        return error_response("Forbidden", status=403, code="forbidden")

    lan = get_lan(request)
    rel_path = request.query.get("path", "")  # query already decoded once
    target = validate_path(lan, rel_path)

    # Re-check containment after final resolution before taking the one
    # root-confined snapshot used for validation and delivery.
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

    try:
        source_body, source_identity = await asyncio.to_thread(
            read_safe_file,
            lan.library_root,
            target,
            max_bytes=MAX_IMAGE_SOURCE_BYTES,
        )
    except (SafeOpenError, OSError, ValueError):
        return _not_found()
    if media_decoder is not None:
        return await _serve_decoded_raster(
            request,
            target,
            media_decoder,
            source_body=source_body,
            source_identity=source_identity,
            max_size=BLURRED_PREVIEW_SIZE,
        )

    content_type = await asyncio.to_thread(_inspect_image_bytes, source_body)
    if content_type is None:
        return _not_found()
    should_blur = await should_blur_target(request, target)
    if not should_blur:
        etag = await asyncio.to_thread(
            build_snapshot_media_etag,
            "image",
            source_identity,
            source_body,
            content_type,
            query=dict(request.query),
        )
        # No later await follows this policy check before direct bytes/304.
        should_blur = await should_blur_target(request, target)
        if not should_blur:
            if etag_matches(request, etag):
                return media_not_modified(etag)
            return web.Response(
                body=source_body,
                content_type=content_type,
                headers={**MEDIA_CACHE_HEADERS, "ETag": etag},
            )
    return await serve_blur_gated_raster(
        request,
        target,
        should_blur=should_blur,
        content_type=content_type,
        max_size=BLURRED_PREVIEW_SIZE,
        source_body=source_body,
        source_identity=source_identity,
    )


__all__ = ["handle_image", "serve_verified_image"]
