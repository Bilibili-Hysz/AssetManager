"""Regression coverage for thumbnail snapshot, policy, and validator order."""
from __future__ import annotations

import io
from typing import Any, cast

import pytest

from AssetsManager.application.thumbnail_service import ThumbnailSourceChangedError
from AssetsManager.application.thumbnail_service import ThumbnailResult
from AssetsManager.lan.routes import thumbnails
from AssetsManager.lan.routes._helpers import LAN_APP_KEY
from tests.lan.support.api_helpers import _make_client, _make_lan_app, _write_valid_png


@pytest.mark.anyio
async def test_thumbnail_revalidates_selected_source_before_returning_304(tmp_path, monkeypatch):
    app, library, _conn = _make_lan_app(tmp_path)
    _write_valid_png(library / "art.png")
    client = await _make_client(app)
    try:
        first = await client.get("/api/thumbnails/art.png")
        assert first.status == 200
        etag = first.headers["ETag"]
        await first.read()

        monkeypatch.setattr(
            thumbnails,
            "validate_thumbnail_source",
            lambda path, identity: (_ for _ in ()).throw(ThumbnailSourceChangedError(path)),
        )
        response = await client.get(
            "/api/thumbnails/art.png", headers={"If-None-Match": etag},
        )
        assert response.status == 409
        assert (await response.json())["code"] == "source_changed"
    finally:
        await client.close()


@pytest.mark.anyio
async def test_thumbnail_rejects_invalid_bytes_with_an_image_suffix(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    (library / "fake.png").write_bytes(b"not a PNG")
    client = await _make_client(app)
    try:
        response = await client.get("/api/thumbnails/fake.png", params={"size": 512})
        assert response.status == 404
    finally:
        await client.close()


@pytest.mark.anyio
async def test_thumbnail_rerenders_when_blur_policy_tightens_after_resolution(tmp_path, monkeypatch):
    app, library, _conn = _make_lan_app(tmp_path)
    _write_valid_png(library / "secret.png")
    service = cast(Any, app[LAN_APP_KEY]).services.thumbnail_service
    monkeypatch.setattr(service, "check_blur", lambda *_args, **_kwargs: True)
    client = await _make_client(app)
    try:
        response = await client.get("/api/thumbnails/secret.png", params={"size": 512})
        body = await response.read()
        assert response.status == 200
        assert response.headers["Content-Type"] == "image/webp"
        assert response.headers["Cache-Control"] == "private, no-store"
        assert "ETag" not in response.headers
        from PIL import Image

        with Image.open(io.BytesIO(body)) as image:
            assert image.format == "WEBP"
    finally:
        await client.close()


@pytest.mark.anyio
async def test_thumbnail_rerenders_after_processing_when_policy_tightens(tmp_path, monkeypatch):
    app, library, _conn = _make_lan_app(tmp_path)
    _write_valid_png(library / "art.png")
    service = cast(Any, app[LAN_APP_KEY]).services.thumbnail_service
    rendered: list[bool] = []

    def render(_body, _size, should_blur):
        rendered.append(should_blur)
        return b"rendered", "image/webp"

    monkeypatch.setattr(service, "process_image_bytes", render)
    monkeypatch.setattr(service, "check_blur", lambda *_args: len(rendered) >= 1)
    client = await _make_client(app)
    try:
        response = await client.get("/api/thumbnails/art.png", params={"size": 128})
        assert response.status == 200
        assert await response.read() == b"rendered"
        assert rendered == [False, True]
        assert response.headers["Cache-Control"] == "private, no-store"
        assert "ETag" not in response.headers
    finally:
        await client.close()


@pytest.mark.anyio
async def test_thumbnail_fails_closed_when_policy_tightens_after_failed_render(tmp_path, monkeypatch):
    app, library, _conn = _make_lan_app(tmp_path)
    _write_valid_png(library / "art.png")
    service = cast(Any, app[LAN_APP_KEY]).services.thumbnail_service
    rendered: list[bool] = []

    def fail_render(_body, _size, should_blur):
        rendered.append(should_blur)
        return None

    monkeypatch.setattr(service, "process_image_bytes", fail_render)
    monkeypatch.setattr(service, "check_blur", lambda *_args: len(rendered) >= 1)
    client = await _make_client(app)
    try:
        response = await client.get("/api/thumbnails/art.png", params={"size": 128})
        assert response.status == 500
        assert rendered == [False, True]
    finally:
        await client.close()


@pytest.mark.anyio
@pytest.mark.parametrize("size, expected", [(512, [True]), (128, [False, True])])
async def test_thumbnail_policy_change_during_etag_hash_renders_blurred(
    tmp_path, monkeypatch, size, expected,
):
    app, library, _conn = _make_lan_app(tmp_path)
    _write_valid_png(library / "art.png")
    service = cast(Any, app[LAN_APP_KEY]).services.thumbnail_service
    rendered: list[bool] = []
    policy_tightened = False
    original_etag = thumbnails.build_snapshot_media_etag

    def render(_body, _size, should_blur):
        rendered.append(should_blur)
        return b"rendered", "image/webp"

    def hash_then_tighten(*args, **kwargs):
        nonlocal policy_tightened
        policy_tightened = True
        return original_etag(*args, **kwargs)

    monkeypatch.setattr(service, "process_image_bytes", render)
    monkeypatch.setattr(service, "check_blur", lambda *_args: policy_tightened)
    monkeypatch.setattr(thumbnails, "build_snapshot_media_etag", hash_then_tighten)
    client = await _make_client(app)
    try:
        response = await client.get("/api/thumbnails/art.png", params={"size": size})
        assert response.status == 200
        assert await response.read() == b"rendered"
        assert rendered == expected
        assert response.headers["Cache-Control"] == "private, no-store"
        assert "ETag" not in response.headers
    finally:
        await client.close()


@pytest.mark.anyio
async def test_thumbnail_batch_omits_early_entries_after_later_policy_change(tmp_path, monkeypatch):
    app, library, _conn = _make_lan_app(tmp_path)
    _write_valid_png(library / "first.png")
    _write_valid_png(library / "second.png")
    rendered: list[tuple[str, bool]] = []

    class _Service:
        def resolve(self, target, *_args, **_kwargs):
            return ThumbnailResult(source_path=target)

        def process_image(self, target, _size, should_blur, _identity):
            rendered.append((target.name, should_blur))
            return b"blurred" if should_blur else b"plain", "image/webp"

        def check_blur(self, *_args):
            return sum(not blur for _name, blur in rendered) >= 2

    monkeypatch.setattr(thumbnails, "get_thumbnail_service", lambda _request: _Service())
    client = await _make_client(app)
    try:
        response = await client.post(
            "/api/thumbnails/batch",
            json={"paths": ["first.png", "second.png"], "size": 128},
        )
        assert response.status == 200
        assert (await response.json())["thumbnails"] == {}
        assert rendered == [
            ("first.png", False),
            ("second.png", False),
        ]
    finally:
        await client.close()
