from __future__ import annotations

import pytest

from AssetsManager.application.thumbnail_service import (
    MAX_THUMBNAIL_SOURCE_BYTES,
    ThumbnailResult,
    ThumbnailService,
)
from AssetsManager.lan.routes import thumbnails
from AssetsManager.lan.routes._helpers import LAN_APP_KEY
from tests.lan.support.api_helpers import _make_client, _make_lan_app, _write_valid_png


def _write_webp(path, size=(256, 128)):
    from PIL import Image

    Image.new("RGB", size, color="green").save(path, format="WEBP")


def test_thumbnail_target_key_preserves_posix_case_variants(monkeypatch, tmp_path):
    monkeypatch.setattr(thumbnails.os.path, "normcase", lambda value: value)

    upper = tmp_path / "Photo.PNG"
    lower = tmp_path / "photo.png"

    assert thumbnails._thumbnail_target_key(upper) != thumbnails._thumbnail_target_key(lower)


@pytest.mark.anyio
async def test_thumbnail_route_rejects_oversized_source_before_decode(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    source = library / "large.png"
    source.write_bytes(b"x" * (MAX_THUMBNAIL_SOURCE_BYTES + 1))
    client = await _make_client(app)
    try:
        response = await client.get("/api/thumbnails/large.png")
        assert response.status == 413
        payload = await response.json()
        assert payload["code"] == "payload_too_large"
        assert payload["details"] == {}
        assert payload["source_bytes"] == MAX_THUMBNAIL_SOURCE_BYTES + 1
    finally:
        await client.close()


@pytest.mark.anyio
async def test_thumbnail_route_skips_malformed_cache_artifact(tmp_path):
    pytest.importorskip("PIL")
    app, library, _conn = _make_lan_app(tmp_path)
    source = library / "image.png"
    _write_valid_png(source)
    svc = ThumbnailService()
    cached = app[LAN_APP_KEY].thumbnail_dir / f"{svc._cache_key(source)}.webp"
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(b"malformed cache")
    client = await _make_client(app)
    try:
        response = await client.get("/api/thumbnails/image.png?size=512")
        body = await response.read()
        assert response.status == 200
        assert body != b"malformed cache"
        from PIL import Image
        import io

        with Image.open(io.BytesIO(body)) as image:
            image.verify()
    finally:
        await client.close()


@pytest.mark.anyio
async def test_thumbnail_route_skips_undersized_cache_artifact(tmp_path):
    pytest.importorskip("PIL")
    app, library, _conn = _make_lan_app(tmp_path)
    source = library / "image.png"
    _write_valid_png(source)
    svc = ThumbnailService()
    cached = app[LAN_APP_KEY].thumbnail_dir / f"{svc._cache_key(source)}.webp"
    cached.parent.mkdir(parents=True, exist_ok=True)
    _write_webp(cached, (64, 32))
    client = await _make_client(app)
    try:
        response = await client.get("/api/thumbnails/image.png?size=512")
        body = await response.read()
        assert response.status == 200
        from PIL import Image
        import io

        with Image.open(io.BytesIO(body)) as image:
            assert max(image.size) <= 512
            image.verify()
    finally:
        await client.close()


@pytest.mark.anyio
async def test_thumbnail_route_marks_blurred_output_private(tmp_path):
    pytest.importorskip("PIL")
    app, library, conn = _make_lan_app(tmp_path)
    source = library / "private.png"
    _write_valid_png(source)
    conn.execute(
        "INSERT INTO file_tags (file_path, tag) VALUES (?, ?)",
        (str(source.resolve()), "private"),
    )
    conn.commit()
    app[LAN_APP_KEY].blur_tags = {"private"}
    client = await _make_client(app)
    try:
        response = await client.get("/api/thumbnails/private.png?size=128")
        body = await response.read()
        assert response.status == 200
        assert response.headers["Cache-Control"] == "private, no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        from PIL import Image
        import io

        with Image.open(io.BytesIO(body)) as image:
            image.verify()
    finally:
        await client.close()


@pytest.mark.anyio
async def test_thumbnail_route_keeps_unblurred_processed_output_public(tmp_path):
    pytest.importorskip("PIL")
    app, library, _conn = _make_lan_app(tmp_path)
    source = library / "image.png"
    _write_valid_png(source)
    client = await _make_client(app)
    try:
        response = await client.get("/api/thumbnails/image.png?size=128")
        await response.read()
        assert response.status == 200
        assert response.headers["Cache-Control"] == "public, max-age=3600"
    finally:
        await client.close()


@pytest.mark.anyio
async def test_thumbnail_batch_deduplicates_decode_and_preserves_aliases(tmp_path, monkeypatch):
    app, library, _conn = _make_lan_app(tmp_path)
    source = library / "image.png"
    _write_valid_png(source)
    calls = []

    class _CountingService:
        def resolve(self, target, *_args, **_kwargs):
            calls.append(("resolve", target))
            return ThumbnailResult(source_path=target)

        def process_image(self, target, *_args):
            calls.append(("process", target))
            return b"thumbnail", "image/webp"

    monkeypatch.setattr(thumbnails, "get_thumbnail_service", lambda _request: _CountingService())
    client = await _make_client(app)
    try:
        response = await client.post(
            "/api/thumbnails/batch",
            json={"paths": ["image.png", "image.png"]},
        )
        assert response.status == 200
        assert response.headers["Cache-Control"] == "private, no-store"
        assert (await response.json())["thumbnails"] == {
            "image.png": "dGh1bWJuYWls",
        }
        assert [kind for kind, _target in calls] == ["resolve", "process"]
    finally:
        await client.close()


@pytest.mark.anyio
async def test_thumbnail_batch_keeps_distinct_posix_case_variants(tmp_path, monkeypatch):
    app, library, _conn = _make_lan_app(tmp_path)
    upper = library / "posix-upper" / "Photo.PNG"
    lower = library / "posix-lower" / "photo.png"
    upper.parent.mkdir()
    lower.parent.mkdir()
    _write_valid_png(upper)
    _write_valid_png(lower)
    monkeypatch.setattr(
        thumbnails,
        "validate_path",
        lambda _lan, rel_path: {"Photo.PNG": upper, "photo.png": lower}[rel_path],
    )
    calls = []

    class _CountingService:
        def resolve(self, target, *_args, **_kwargs):
            calls.append(("resolve", target))
            return ThumbnailResult(source_path=target)

        def process_image(self, target, *_args):
            calls.append(("process", target))
            return b"thumbnail", "image/webp"

    monkeypatch.setattr(thumbnails, "get_thumbnail_service", lambda _request: _CountingService())
    monkeypatch.setattr(thumbnails.os.path, "normcase", lambda value: value)
    client = await _make_client(app)
    try:
        response = await client.post(
            "/api/thumbnails/batch",
            json={"paths": ["Photo.PNG", "photo.png"]},
        )
        assert response.status == 200
        assert set((await response.json())["thumbnails"]) == {"Photo.PNG", "photo.png"}
        assert [kind for kind, _target in calls] == [
            "resolve", "process", "resolve", "process"
        ]
    finally:
        await client.close()


@pytest.mark.anyio
async def test_thumbnail_batch_deduplicates_path_aliases(tmp_path, monkeypatch):
    app, library, _conn = _make_lan_app(tmp_path)
    source = library / "image.png"
    _write_valid_png(source)
    calls = []

    class _CountingService:
        def resolve(self, target, *_args, **_kwargs):
            calls.append(("resolve", target))
            return ThumbnailResult(source_path=target)

        def process_image(self, target, *_args):
            calls.append(("process", target))
            return b"thumbnail", "image/webp"

    monkeypatch.setattr(thumbnails, "get_thumbnail_service", lambda _request: _CountingService())
    client = await _make_client(app)
    try:
        response = await client.post(
            "/api/thumbnails/batch",
            json={"paths": ["image.png", "./image.png"]},
        )
        assert response.status == 200
        assert (await response.json())["thumbnails"] == {
            "image.png": "dGh1bWJuYWls",
            "./image.png": "dGh1bWJuYWls",
        }
        assert [kind for kind, _target in calls] == ["resolve", "process"]
    finally:
        await client.close()


@pytest.mark.anyio
async def test_thumbnail_batch_rejects_unique_source_budget(tmp_path, monkeypatch):
    app, library, _conn = _make_lan_app(tmp_path)
    first = library / "first.png"
    second = library / "second.png"
    first.write_bytes(b"a" * 6)
    second.write_bytes(b"b" * 5)
    monkeypatch.setattr(thumbnails, "MAX_THUMBNAIL_BATCH_BYTES", 10)
    client = await _make_client(app)
    try:
        response = await client.post(
            "/api/thumbnails/batch",
            json={"paths": ["first.png", "second.png"]},
        )
        assert response.status == 413
        payload = await response.json()
        assert payload["code"] == "payload_too_large"
        assert payload["total_bytes"] == 11
        assert payload["limit_bytes"] == 10
    finally:
        await client.close()
