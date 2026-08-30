"""LAN route integration for media decoder formats (port batch N-B).

The successful decode is the content gate for RAW/PSD (same fail-closed
semantics as the Pillow ``verify`` gate), and delivery always goes through
the shared WEBP pipeline — RAW/PSD originals are never served as bytes.
"""

from __future__ import annotations

import io

import pytest

from AssetsManager.lan.routes import image as image_routes
from AssetsManager.lan.routes import thumbnails as thumbnail_routes
from tests.lan.support.api_helpers import _make_client, _make_lan_app


def _write_psd(path, size=(8, 6), color=(200, 60, 30)):
    psd_tools = pytest.importorskip("psd_tools")
    psd_tools.PSDImage.new(mode="RGB", size=size, color=color).save(path)
    return path


def _webp_dimensions(body: bytes):
    from PIL import Image

    with Image.open(io.BytesIO(body)) as image:
        image.verify()
    return image.format, image.size


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_thumbnail_route_renders_psd_through_webp_pipeline(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    _write_psd(library / "art.psd")
    client = await _make_client(app)
    try:
        response = await client.get("/api/thumbnails/art.psd", params={"size": "512"})
        assert response.status == 200
        assert response.headers["Content-Type"] == "image/webp"
        fmt, size = _webp_dimensions(await response.read())
        assert fmt == "WEBP"
        assert size == (8, 6)
    finally:
        await client.close()


@pytest.mark.anyio
async def test_thumbnail_batch_renders_psd(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    _write_psd(library / "art.psd")
    client = await _make_client(app)
    try:
        response = await client.post(
            "/api/thumbnails/batch",
            json={"paths": ["art.psd"], "size": 512},
        )
        assert response.status == 200
        payload = await response.json()
        assert "art.psd" in payload["thumbnails"]
    finally:
        await client.close()


@pytest.mark.anyio
async def test_image_route_renders_psd_as_webp_and_never_serves_original(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    source = _write_psd(library / "art.psd")
    original = source.read_bytes()
    client = await _make_client(app)
    try:
        response = await client.get("/api/image", params={"path": "art.psd"})
        assert response.status == 200
        assert response.headers["Content-Type"] == "image/webp"
        body = await response.read()
        assert body != original  # RAW/PSD originals are not browser rasters
        fmt, size = _webp_dimensions(body)
        assert fmt == "WEBP"
    finally:
        await client.close()


@pytest.mark.anyio
async def test_media_suffix_with_non_media_content_fails_closed(tmp_path):
    """A text file wearing a .psd suffix must 404, exactly like .png does."""
    app, library, _conn = _make_lan_app(tmp_path)
    (library / "fake.psd").write_bytes(b"this is not a Photoshop document")
    client = await _make_client(app)
    try:
        thumbnail = await client.get("/api/thumbnails/fake.psd")
        assert thumbnail.status == 404
        preview = await client.get("/api/image", params={"path": "fake.psd"})
        assert preview.status == 404
    finally:
        await client.close()


@pytest.mark.anyio
async def test_routes_without_media_extras_keep_pre_nb_behavior(tmp_path, monkeypatch):
    """Missing-deps fallback: with no registered decoder every route 404s."""
    app, library, _conn = _make_lan_app(tmp_path)
    _write_psd(library / "art.psd")
    monkeypatch.setattr(thumbnail_routes, "decoder_for", lambda ext: None)
    monkeypatch.setattr(image_routes, "decoder_for", lambda ext: None)
    client = await _make_client(app)
    try:
        thumbnail = await client.get("/api/thumbnails/art.psd", params={"size": "512"})
        assert thumbnail.status == 404
        preview = await client.get("/api/image", params={"path": "art.psd"})
        assert preview.status == 404
    finally:
        await client.close()
