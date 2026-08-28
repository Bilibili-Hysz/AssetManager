from __future__ import annotations

import pytest
from PIL import Image

from AssetsManager.lan.routes._helpers import LAN_APP_KEY
from tests.lan.support.api_helpers import _local_ui_headers, _make_client, _make_lan_app


def _image(path, color=(50, 90, 150), size=(32, 16)):
    Image.new("RGB", size, color).save(path)


@pytest.mark.anyio
async def test_share_preview_verifies_content_and_uses_private_cache(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    image = library / "image.png"
    _image(image)
    (library / "fake.png").write_bytes(b"not a png")
    client = await _make_client(app)
    try:
        created = await client.post(
            "/api/shares",
            json={"paths": ["."], "allow_preview": True},
            headers=_local_ui_headers(app),
        )
        share_id = (await created.json())["id"]

        valid = await client.get(f"/api/shares/{share_id}/preview/image.png")
        assert valid.status == 200
        assert valid.headers["Content-Type"] == "image/png"
        assert valid.headers["Cache-Control"] == "private, no-store"
        assert await valid.read() == image.read_bytes()

        invalid = await client.get(f"/api/shares/{share_id}/preview/fake.png")
        assert invalid.status == 404
        assert await invalid.read() == b""
    finally:
        await client.close()


@pytest.mark.anyio
async def test_share_preview_applies_blur_and_fails_closed(tmp_path, monkeypatch):
    app, library, conn = _make_lan_app(tmp_path)
    image = library / "private.png"
    _image(image, color=(255, 0, 0), size=(64, 64))
    conn.execute(
        "INSERT INTO file_tags (file_path, tag) VALUES (?, ?)",
        (str(image.resolve()), "private"),
    )
    conn.commit()
    app[LAN_APP_KEY].blur_tags = {"private"}
    client = await _make_client(app)
    try:
        created = await client.post(
            "/api/shares",
            json={"paths": ["private.png"], "allow_preview": True},
            headers=_local_ui_headers(app),
        )
        share_id = (await created.json())["id"]
        response = await client.get(f"/api/shares/{share_id}/preview/private.png")
        body = await response.read()
        assert response.status == 200
        assert response.headers["Content-Type"] == "image/webp"
        assert response.headers["Cache-Control"] == "private, no-store"
        assert body.startswith(b"RIFF")
        assert body != image.read_bytes()

        monkeypatch.setattr(app[LAN_APP_KEY].services.thumbnail_service, "process_image", lambda *args, **kwargs: None)
        failed = await client.get(f"/api/shares/{share_id}/preview/private.png")
        assert failed.status == 500
        assert (await failed.json())["code"] == "internal_error"
        assert image.read_bytes() not in await failed.read()
    finally:
        await client.close()


@pytest.mark.anyio
async def test_password_share_preview_keeps_token_scope_and_cache_policy(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    image = library / "image.png"
    _image(image)
    client = await _make_client(app)
    try:
        created = await client.post(
            "/api/shares",
            json={"paths": ["image.png"], "password": "secret123", "allow_preview": True},
            headers=_local_ui_headers(app),
        )
        share_id = (await created.json())["id"]
        assert (await client.get(f"/api/shares/{share_id}/preview/image.png")).status == 401
        verified = await client.post(f"/api/shares/{share_id}/verify", json={"password": "secret123"})
        assert verified.status == 200
        response = await client.get(f"/api/shares/{share_id}/preview/image.png")
        assert response.status == 200
        assert response.headers["Cache-Control"] == "private, no-store"
    finally:
        await client.close()
