"""E-D3: media route ETag/If-None-Match revalidation and cache headers.

The image/thumbnail routes serve immutable-per-source bytes, so successful
responses are privately cacheable (``private, max-age=3600``) and revalidate
via a weak ETag.  The 304 short-circuit must sit after the permission and
PathGuard checks and never fire for blurred output.
"""
from __future__ import annotations

import pytest

from AssetsManager.lan.routes._helpers import LAN_APP_KEY
from AssetsManager.lan.routes.image import handle_image
from tests.lan.support.api_helpers import _make_client, _make_lan_app, _write_valid_png


def _register_image_route(app):
    app.router.add_get("/api/image", handle_image)


def _assert_cacheable(response):
    assert response.headers["Cache-Control"] == "private, max-age=3600"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["ETag"].startswith('W/"')
    return response.headers["ETag"]


@pytest.mark.anyio
async def test_thumbnail_first_request_carries_validator_and_cache_headers(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    _write_valid_png(library / "art.png")
    client = await _make_client(app)
    try:
        response = await client.get("/api/thumbnails/art.png")
        assert response.status == 200
        await response.read()
        _assert_cacheable(response)
    finally:
        await client.close()


@pytest.mark.anyio
async def test_thumbnail_if_none_match_hit_returns_304_without_body(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    _write_valid_png(library / "art.png")
    client = await _make_client(app)
    try:
        first = await client.get("/api/thumbnails/art.png")
        assert first.status == 200
        etag = _assert_cacheable(first)
        await first.read()

        second = await client.get(
            "/api/thumbnails/art.png", headers={"If-None-Match": etag},
        )
        assert second.status == 304
        assert await second.read() == b""
        # 304 keeps the validator and cache policy alive for the client.
        assert second.headers["ETag"] == etag
        assert second.headers["Cache-Control"] == "private, max-age=3600"
    finally:
        await client.close()


@pytest.mark.anyio
async def test_thumbnail_etag_varies_with_processing_params(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    _write_valid_png(library / "art.png")
    client = await _make_client(app)
    try:
        small = await client.get("/api/thumbnails/art.png", params={"size": "256"})
        large = await client.get("/api/thumbnails/art.png", params={"size": "512"})
        assert small.status == large.status == 200
        small_etag = _assert_cacheable(small)
        large_etag = _assert_cacheable(large)
        assert small_etag != large_etag
    finally:
        await client.close()


@pytest.mark.anyio
async def test_image_route_revalidates_with_if_none_match(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    _write_valid_png(library / "art.png")
    _register_image_route(app)
    client = await _make_client(app)
    try:
        first = await client.get("/api/image", params={"path": "art.png"})
        assert first.status == 200
        etag = _assert_cacheable(first)
        body = await first.read()
        assert body

        second = await client.get(
            "/api/image", params={"path": "art.png"}, headers={"If-None-Match": etag},
        )
        assert second.status == 304
        assert await second.read() == b""
        assert second.headers["ETag"] == etag
        assert second.headers["Cache-Control"] == "private, max-age=3600"
    finally:
        await client.close()


@pytest.mark.anyio
async def test_image_route_etag_binds_the_normalized_query(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    _write_valid_png(library / "art.png")
    _register_image_route(app)
    client = await _make_client(app)
    try:
        plain = await client.get("/api/image", params={"path": "art.png"})
        decorated = await client.get(
            "/api/image", params={"path": "art.png", "v": "2"},
        )
        assert plain.status == decorated.status == 200
        assert _assert_cacheable(plain) != _assert_cacheable(decorated)
    finally:
        await client.close()


@pytest.mark.anyio
async def test_blurred_output_keeps_no_store_and_never_revalidates(tmp_path):
    app, library, conn = _make_lan_app(tmp_path)
    source = library / "secret.png"
    _write_valid_png(source)
    conn.execute(
        "INSERT INTO file_tags (file_path, tag) VALUES (?, ?)",
        (str(source.resolve()), "private"),
    )
    conn.commit()
    app[LAN_APP_KEY].blur_tags = {"private"}
    client = await _make_client(app)
    try:
        response = await client.get(
            "/api/thumbnails/secret.png",
            headers={"If-None-Match": 'W/"stale"'},
        )
        body = await response.read()
        assert response.status == 200
        # Blurred bytes stay uncacheable: a cached pre-blur copy would be a
        # privacy leak, so there is no validator and no 304 short-circuit.
        assert response.headers["Cache-Control"] == "private, no-store"
        assert "ETag" not in response.headers
        assert body
    finally:
        await client.close()


@pytest.mark.anyio
async def test_if_none_match_cannot_bypass_permission_checks(tmp_path, monkeypatch):
    from AssetsManager.core.settings import AppSettings

    class _GuestSettings:
        def get(self, key, default=None):
            return {"lan_guest_preview": False}.get(key, default)

    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda cls: _GuestSettings()))
    app, library, _conn = _make_lan_app(tmp_path)
    _write_valid_png(library / "art.png")
    client = await _make_client(app)
    try:
        response = await client.get(
            "/api/thumbnails/art.png", headers={"If-None-Match": "*"},
        )
        assert response.status == 403
        body = await response.json()
        assert body["code"] == "forbidden"
    finally:
        await client.close()
