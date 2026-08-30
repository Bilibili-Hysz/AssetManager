from __future__ import annotations


import pytest
from PIL import Image

from AssetsManager.lan.routes._helpers import LAN_APP_KEY
from AssetsManager.lan.routes.image import handle_image, serve_verified_image
from tests.lan.support.api_helpers import _make_client, _make_lan_app


def _image(path, *, color=(50, 90, 150), size=(32, 16)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


def _register_image_route(app):
    # The production registration is intentionally owned by lan/api.py.  Keep
    # this test scoped to the new handler so the task can be tested independently
    # while another main-thread change wires the route into setup_routes().
    app.router.add_get("/api/image", handle_image)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_image_route_requires_preview_permission(tmp_path, monkeypatch):
    from AssetsManager.core.settings import AppSettings

    class _GuestSettings:
        def get(self, key, default=None):
            return {"lan_guest_preview": False}.get(key, default)

    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda cls: _GuestSettings()))
    app, library, _conn = _make_lan_app(tmp_path)
    _image(library / "art.png")
    _register_image_route(app)
    client = await _make_client(app)
    try:
        response = await client.get("/api/image", params={"path": "art.png"})
        assert response.status == 403
        body = await response.json()
        assert body["error"] == "Forbidden"
        assert body["code"] == "forbidden"
    finally:
        await client.close()


@pytest.mark.anyio
@pytest.mark.parametrize("relative_path", ["../outside.png", "folder", "notes.txt", "script.svg"])
async def test_image_route_rejects_escape_directories_and_non_images(tmp_path, relative_path):
    app, library, _conn = _make_lan_app(tmp_path)
    _image(library / "folder" / "inside.png")
    (library / "notes.txt").write_text("not an image", encoding="utf-8")
    _register_image_route(app)
    client = await _make_client(app)
    try:
        response = await client.get("/api/image", params={"path": relative_path})
        assert response.status in {400, 404}
    finally:
        await client.close()


@pytest.mark.anyio
async def test_image_route_streams_verified_image_with_conservative_headers(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    image = library / "nested" / "高清 image.png"
    _image(image)
    expected = image.read_bytes()
    _register_image_route(app)
    client = await _make_client(app)
    try:
        response = await client.get(
            "/api/image",
            params={"path": "nested/高清 image.png"},
        )
        assert response.status == 200
        assert response.headers["Content-Type"] == "image/png"
        # Non-blur media is privately cacheable and carries a revalidation
        # validator (E-D3); blurred output keeps "private, no-store".
        assert response.headers["Cache-Control"] == "private, max-age=3600"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["ETag"].startswith('W/"')
        assert await response.read() == expected
    finally:
        await client.close()


@pytest.mark.anyio
async def test_image_route_rejects_image_suffix_with_non_image_content(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    (library / "fake.png").write_bytes(b"this is not a PNG")
    _register_image_route(app)
    client = await _make_client(app)
    try:
        response = await client.get("/api/image", params={"path": "fake.png"})
        assert response.status == 404
    finally:
        await client.close()


@pytest.mark.anyio
async def test_image_route_blurs_tagged_asset_without_falling_back_to_original(tmp_path):
    app, library, conn = _make_lan_app(tmp_path)
    image = library / "private.png"
    _image(image, color=(255, 0, 0), size=(64, 64))
    conn.execute(
        "INSERT INTO file_tags (file_path, tag) VALUES (?, ?)",
        (str(image.resolve()), "private"),
    )
    conn.commit()
    lan = app[LAN_APP_KEY]
    lan.blur_tags = {"private"}
    _register_image_route(app)
    client = await _make_client(app)
    try:
        response = await client.get("/api/image", params={"path": "private.png"})
        body = await response.read()
        assert response.status == 200
        assert response.headers["Content-Type"] == "image/webp"
        assert body != image.read_bytes()
        assert body.startswith(b"RIFF")
    finally:
        await client.close()




@pytest.mark.anyio
async def test_public_verified_media_rejects_svg_and_invalid_raster(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    valid = library / "valid.png"
    _image(valid)
    (library / "unsafe.svg").write_text("<svg><script>alert(1)</script></svg>", encoding="utf-8")
    (library / "fake.jpg").write_bytes(b"not an image")

    async def public_media(request):
        name = request.query.get("name", "")
        return await serve_verified_image(
            request,
            (library / name).resolve(),
            max_size=512,
            public=True,
        )

    app.router.add_get("/api/public-media", public_media)
    client = await _make_client(app)
    try:
        ok = await client.get("/api/public-media", params={"name": "valid.png"})
        assert ok.status == 200
        assert ok.headers["X-Content-Type-Options"] == "nosniff"
        assert ok.headers["Cache-Control"] == "public, max-age=3600"
        assert (await ok.read()).startswith(b"\x89PNG")
        for name in ("unsafe.svg", "fake.jpg", "missing.png"):
            response = await client.get("/api/public-media", params={"name": name})
            assert response.status == 404
    finally:
        await client.close()
