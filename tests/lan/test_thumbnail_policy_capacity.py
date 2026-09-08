"""Thumbnail variation and capacity boundaries over real HTTP.

Work package ``week-2026-09-14-lan-workpack``, implementation step 2
(thumbnail variation/capacity boundary half).  All requests go through the
composed LAN app and its real routes; the only seams used are the established
harness ones (cache-artifact seeding as in ``test_thumbnail_admission``) and
the real tag store for policy changes:

1. Cache miss -> hit sequence: status, content type, cache headers, and the
   served bytes are pinned at every point, including the ``304`` revalidation
   of the hit representation.
2. Blur policy flip between real requests: after the policy tightens, the
   route must never return the old unblurred body — not unconditionally and
   not through a stale-validator ``304``.
3. The same never-leak guarantee for a cached unblurred artifact: a cache
   hit resolved after the flip must re-render the artifact blurred.
4. 64 MiB source boundary: a source of exactly the limit is admitted and
   rendered; one byte more is rejected with ``413`` without polluting the
   thumbnail cache or its metadata rows, and a later valid request still
   succeeds.
"""
import io
import os

import pytest
from PIL import Image

from AssetsManager.application.thumbnail_service import ThumbnailService
from AssetsManager.lan.routes import thumbnails
from AssetsManager.lan.routes._helpers import LAN_APP_KEY
from tests.lan.support.api_helpers import _make_client, _make_lan_app, _write_valid_png


def _render(body, size, blurred):
    """Standalone reference render of already-captured source bytes."""
    return ThumbnailService().process_image_bytes(body, size, blurred)[0]


def _write_noisy_png(path, side=64):
    """A structured (noise) source: Gaussian blur must change its bytes."""
    Image.frombytes("RGB", (side, side), os.urandom(side * side * 3)).save(
        path, format="PNG",
    )


def _write_noisy_webp(path, size=(256, 128)):
    Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3)).save(
        path, format="WEBP",
    )


def _seed_cache_artifact(lan, source, size=(256, 128)):
    """Seed a valid WEBP cache artifact (existing admission-test technique)."""
    artifact = lan.thumbnail_dir / f"{lan.services.thumbnail_service._cache_key(source)}.webp"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    _write_noisy_webp(artifact, size)
    return artifact


def _cache_artifacts(lan):
    if not lan.thumbnail_dir.exists():
        return []
    return sorted(path.name for path in lan.thumbnail_dir.glob("*"))


def _tighten_blur_policy(app, conn, source):
    """Flip the blur policy through the real tag store, between requests."""
    conn.execute(
        "INSERT INTO file_tags (file_path, tag) VALUES (?, ?)",
        (str(source.resolve()), "private"),
    )
    conn.commit()
    app[LAN_APP_KEY].blur_tags = {"private"}


def _png_padded_to(target_bytes):
    """A valid PNG whose file size is exactly ``target_bytes`` bytes.

    Random noise keeps the PNG body large enough to stay under the limit;
    the trailing bytes after IEND are ignored by the PNG decoder, which lets
    the file land exactly on the 64 MiB admission boundary.
    """
    side = 2048
    image = Image.frombytes("RGB", (side, side), os.urandom(side * side * 3))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", compress_level=1)
    png = buffer.getvalue()
    assert len(png) <= target_bytes, "noise body must fit inside the limit"
    return png + b"\x00" * (target_bytes - len(png))


@pytest.mark.anyio
async def test_thumbnail_cache_miss_then_hit_sequence_pins_headers(tmp_path):
    pytest.importorskip("PIL")
    app, library, _conn = _make_lan_app(tmp_path)
    source = library / "image.png"
    _write_valid_png(source)
    client = await _make_client(app)
    try:
        # Miss: rendered from the original source.
        miss = await client.get("/api/thumbnails/image.png", params={"size": "128"})
        miss_body = await miss.read()
        assert miss.status == 200
        assert miss.headers["Content-Type"] == "image/webp"
        assert miss.headers["Cache-Control"] == "private, no-cache"
        assert miss.headers["X-Content-Type-Options"] == "nosniff"
        assert miss.headers["ETag"].startswith('W/"')
        assert miss_body == _render(source.read_bytes(), 128, False)

        # Hit: the seeded artifact is resolved and re-encoded, not the source.
        lan = app[LAN_APP_KEY]
        artifact = _seed_cache_artifact(lan, source)
        hit = await client.get("/api/thumbnails/image.png", params={"size": "128"})
        hit_body = await hit.read()
        assert hit.status == 200
        assert hit.headers["Content-Type"] == "image/webp"
        assert hit.headers["Cache-Control"] == "private, no-cache"
        assert hit.headers["X-Content-Type-Options"] == "nosniff"
        assert hit.headers["ETag"].startswith('W/"')
        assert hit_body != miss_body
        assert hit_body == _render(artifact.read_bytes(), 128, False)

        # Revalidation of the hit representation short-circuits with 304.
        revalidated = await client.get(
            "/api/thumbnails/image.png",
            params={"size": "128"},
            headers={"If-None-Match": hit.headers["ETag"]},
        )
        assert revalidated.status == 304
        assert revalidated.headers["ETag"] == hit.headers["ETag"]
        assert revalidated.headers["Cache-Control"] == "private, no-cache"
        assert await revalidated.read() == b""
    finally:
        await client.close()


@pytest.mark.anyio
async def test_blur_policy_flip_never_returns_stale_unblurred_body(tmp_path):
    pytest.importorskip("PIL")
    app, library, conn = _make_lan_app(tmp_path)
    source = library / "secret.png"
    _write_noisy_png(source)
    client = await _make_client(app)
    try:
        before = await client.get("/api/thumbnails/secret.png", params={"size": "128"})
        unblurred = await before.read()
        stale_etag = before.headers["ETag"]
        assert before.status == 200
        assert before.headers["Cache-Control"] == "private, no-cache"
        assert unblurred == _render(source.read_bytes(), 128, False)

        # The policy tightens between real requests, through the tag store.
        _tighten_blur_policy(app, conn, source)

        flipped = await client.get("/api/thumbnails/secret.png", params={"size": "128"})
        blurred = await flipped.read()
        assert flipped.status == 200
        assert flipped.headers["Cache-Control"] == "private, no-store"
        assert "ETag" not in flipped.headers
        assert blurred != unblurred
        assert blurred == _render(source.read_bytes(), 128, True)

        # The stale validator from the unblurred era must never short-circuit
        # into a 304 of the old body.
        conditional = await client.get(
            "/api/thumbnails/secret.png",
            params={"size": "128"},
            headers={"If-None-Match": stale_etag},
        )
        conditional_body = await conditional.read()
        assert conditional.status == 200
        assert conditional.headers["Cache-Control"] == "private, no-store"
        assert "ETag" not in conditional.headers
        assert conditional_body == blurred
        assert conditional_body != unblurred
    finally:
        await client.close()


@pytest.mark.anyio
async def test_blur_tightening_after_cache_hit_never_serves_cached_unblurred_body(
    tmp_path,
):
    pytest.importorskip("PIL")
    app, library, conn = _make_lan_app(tmp_path)
    source = library / "leak.png"
    _write_noisy_png(source)
    lan = app[LAN_APP_KEY]
    artifact = _seed_cache_artifact(lan, source)
    client = await _make_client(app)
    try:
        # While the policy is clean the cached artifact is served re-encoded.
        before = await client.get("/api/thumbnails/leak.png", params={"size": "128"})
        unblurred_hit = await before.read()
        stale_etag = before.headers["ETag"]
        assert before.status == 200
        assert before.headers["Cache-Control"] == "private, no-cache"
        assert unblurred_hit == _render(artifact.read_bytes(), 128, False)

        _tighten_blur_policy(app, conn, source)

        # The cache hit is re-resolved under the tightened policy: the cached
        # unblurred bytes themselves must never reach the client.
        after = await client.get("/api/thumbnails/leak.png", params={"size": "128"})
        blurred_hit = await after.read()
        assert after.status == 200
        assert after.headers["Cache-Control"] == "private, no-store"
        assert "ETag" not in after.headers
        assert blurred_hit != artifact.read_bytes()
        assert blurred_hit != unblurred_hit
        assert blurred_hit == _render(artifact.read_bytes(), 128, True)

        # And the old validator cannot resurrect the unblurred representation.
        conditional = await client.get(
            "/api/thumbnails/leak.png",
            params={"size": "128"},
            headers={"If-None-Match": stale_etag},
        )
        conditional_body = await conditional.read()
        assert conditional.status == 200
        assert conditional.headers["Cache-Control"] == "private, no-store"
        assert conditional_body == blurred_hit
    finally:
        await client.close()


@pytest.mark.anyio
async def test_thumbnail_source_limit_boundary_keeps_cache_clean(tmp_path):
    pytest.importorskip("PIL")
    limit = thumbnails.MAX_THUMBNAIL_SOURCE_BYTES
    app, library, _conn = _make_lan_app(tmp_path)
    lan = app[LAN_APP_KEY]
    service = lan.services.thumbnail_service
    client = await _make_client(app)
    try:
        # Over limit: rejected before any decode, cache, or metadata write.
        over = library / "over.png"
        over.write_bytes(b"x" * (limit + 1))
        rejected = await client.get("/api/thumbnails/over.png", params={"size": "128"})
        assert rejected.status == 413
        payload = await rejected.json()
        assert payload["code"] == "payload_too_large"
        assert payload["source_bytes"] == limit + 1
        assert payload["limit_bytes"] == limit
        assert _cache_artifacts(lan) == []
        assert service.list_cache_metadata(str(lan.library_root)) == []

        # The failed admission must not poison later valid requests.
        good = library / "fine.png"
        _write_valid_png(good)
        recovered = await client.get("/api/thumbnails/fine.png", params={"size": "128"})
        assert recovered.status == 200
        await recovered.read()

        # Critical boundary: exactly the limit is a valid, admitted source.
        boundary = library / "boundary.png"
        boundary.write_bytes(_png_padded_to(limit))
        accepted = await client.get("/api/thumbnails/boundary.png", params={"size": "128"})
        accepted_body = await accepted.read()
        assert accepted.status == 200
        assert accepted.headers["Content-Type"] == "image/webp"
        with Image.open(io.BytesIO(accepted_body)) as image:
            assert image.format == "WEBP"
            assert max(image.size) <= 128
        # The LAN on-demand route never pollutes the persistent cache.
        assert _cache_artifacts(lan) == []
    finally:
        await client.close()
