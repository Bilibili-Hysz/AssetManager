"""Regression coverage for image-preview snapshot and policy invariants."""
from __future__ import annotations

import io
import os
from importlib import import_module

import pytest
from PIL import Image

from AssetsManager.lan.routes.image import handle_image, serve_verified_image
from tests.lan.support.api_helpers import _make_client, _make_lan_app


def _png_bytes(color: tuple[int, int, int]) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (32, 16), color).save(output, format="PNG")
    return output.getvalue()


def _register_image_route(app) -> None:
    app.router.add_get("/api/image", handle_image)


@pytest.mark.anyio
async def test_image_response_uses_the_verified_snapshot_when_path_is_replaced(tmp_path, monkeypatch):
    app, library, _conn = _make_lan_app(tmp_path)
    target = library / "art.png"
    verified_bytes = _png_bytes((20, 40, 60))
    replacement_bytes = _png_bytes((200, 100, 50))
    target.write_bytes(verified_bytes)
    image_routes = import_module("AssetsManager.lan.routes.image")
    original_inspect = image_routes._inspect_image_bytes

    def inspect_then_replace(body: bytes):
        assert body == verified_bytes
        target.write_bytes(replacement_bytes)
        return original_inspect(body)

    monkeypatch.setattr(image_routes, "_inspect_image_bytes", inspect_then_replace)
    _register_image_route(app)
    client = await _make_client(app)
    try:
        response = await client.get("/api/image", params={"path": "art.png"})
        assert response.status == 200
        assert await response.read() == verified_bytes
        assert target.read_bytes() == replacement_bytes
    finally:
        await client.close()


@pytest.mark.anyio
async def test_image_etag_changes_when_bytes_change_with_same_size_and_mtime(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    target = library / "art.png"
    first_bytes = _png_bytes((30, 60, 90))
    second_bytes = _png_bytes((90, 60, 30))
    assert len(first_bytes) == len(second_bytes)
    target.write_bytes(first_bytes)
    fixed_mtime = target.stat().st_mtime_ns
    _register_image_route(app)
    client = await _make_client(app)
    try:
        first = await client.get("/api/image", params={"path": "art.png"})
        assert first.status == 200
        etag = first.headers["ETag"]
        assert await first.read() == first_bytes

        target.write_bytes(second_bytes)
        os.utime(target, ns=(fixed_mtime, fixed_mtime))
        assert target.stat().st_size == len(first_bytes)
        assert target.stat().st_mtime_ns == fixed_mtime

        second = await client.get(
            "/api/image",
            params={"path": "art.png"},
            headers={"If-None-Match": etag},
        )
        assert second.status == 200
        assert second.headers["ETag"] != etag
        assert await second.read() == second_bytes
    finally:
        await client.close()


@pytest.mark.anyio
async def test_image_policy_tightening_after_snapshot_cannot_return_unblurred_304(tmp_path, monkeypatch):
    app, library, _conn = _make_lan_app(tmp_path)
    target = library / "art.png"
    original_bytes = _png_bytes((20, 40, 60))
    target.write_bytes(original_bytes)
    _register_image_route(app)
    client = await _make_client(app)
    try:
        first = await client.get("/api/image", params={"path": "art.png"})
        etag = first.headers["ETag"]
        await first.read()

        calls = 0

        async def policy_tightens(_request, _target):
            nonlocal calls
            calls += 1
            return calls >= 2

        image_routes = import_module("AssetsManager.lan.routes.image")
        monkeypatch.setattr(image_routes, "should_blur_target", policy_tightens)
        response = await client.get(
            "/api/image",
            params={"path": "art.png"},
            headers={"If-None-Match": etag},
        )
        body = await response.read()
        assert calls == 2
        assert response.status == 200
        assert response.headers["Cache-Control"] == "private, no-store"
        assert "ETag" not in response.headers
        assert response.headers["Content-Type"] == "image/webp"
        assert body != original_bytes
    finally:
        await client.close()


@pytest.mark.anyio
async def test_public_verified_image_rechecks_policy_before_source_byte_delivery(tmp_path, monkeypatch):
    app, library, _conn = _make_lan_app(tmp_path)
    target = library / "art.png"
    original_bytes = _png_bytes((20, 40, 60))
    target.write_bytes(original_bytes)

    async def public_media(request):
        return await serve_verified_image(
            request, target, max_size=512, public=True,
        )

    calls = 0

    async def policy_tightens(_request, _target):
        nonlocal calls
        calls += 1
        return calls >= 2

    image_routes = import_module("AssetsManager.lan.routes.image")
    monkeypatch.setattr(image_routes, "should_blur_target", policy_tightens)
    app.router.add_get("/api/public-media", public_media)
    client = await _make_client(app)
    try:
        response = await client.get("/api/public-media")
        body = await response.read()
        assert calls == 2
        assert response.status == 200
        assert response.headers["Cache-Control"] == "private, no-store"
        assert response.headers["Content-Type"] == "image/webp"
        assert body != original_bytes
    finally:
        await client.close()


@pytest.mark.anyio
async def test_decoder_preview_redecodes_snapshot_when_policy_tightens(tmp_path, monkeypatch):
    app, library, _conn = _make_lan_app(tmp_path)
    target = library / "art.raw"
    target.write_bytes(b"captured-raw-source")
    image_routes = import_module("AssetsManager.lan.routes.image")
    decode_calls = 0

    class Decoder:
        def decode_bytes(self, body: bytes, *, max_dim: int):
            nonlocal decode_calls
            assert body == b"captured-raw-source"
            assert max_dim == 1920
            decode_calls += 1
            return Image.new("RGB", (32, 16), (20, 40, 60))

    policy_calls = 0

    async def policy_tightens(_request, _target):
        nonlocal policy_calls
        policy_calls += 1
        return policy_calls >= 2

    monkeypatch.setattr(image_routes, "decoder_for", lambda _suffix: Decoder())
    monkeypatch.setattr(image_routes, "should_blur_target", policy_tightens)
    _register_image_route(app)
    client = await _make_client(app)
    try:
        response = await client.get("/api/image", params={"path": "art.raw"})
        body = await response.read()
        assert response.status == 200
        assert decode_calls == 2
        assert response.headers["Content-Type"] == "image/webp"
        assert response.headers["Cache-Control"] == "private, no-store"
        assert "ETag" not in response.headers
        assert body.startswith(b"RIFF")
    finally:
        await client.close()


@pytest.mark.anyio
async def test_undecodable_decoder_source_cannot_return_304(tmp_path, monkeypatch):
    app, library, _conn = _make_lan_app(tmp_path)
    (library / "broken.raw").write_bytes(b"not-a-raw-image")
    image_routes = import_module("AssetsManager.lan.routes.image")

    class Decoder:
        def decode_bytes(self, _body: bytes, *, max_dim: int):
            return None

    monkeypatch.setattr(image_routes, "decoder_for", lambda _suffix: Decoder())
    _register_image_route(app)
    client = await _make_client(app)
    try:
        response = await client.get(
            "/api/image",
            params={"path": "broken.raw"},
            headers={"If-None-Match": "*"},
        )
        assert response.status == 404
        assert await response.read() == b""
    finally:
        await client.close()
