"""Regression coverage for the SPA's separately emitted font files."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from AssetsManager.lan.api import setup_routes
from AssetsManager.lan.routes import pages
from AssetsManager.lan.routes._helpers import LAN_APP_KEY


@pytest.mark.anyio
async def test_spa_font_route_serves_only_dist_fonts(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    fonts = dist / "fonts"
    fonts.mkdir(parents=True)
    font = fonts / "inter-var-latin.woff2"
    font.write_bytes(b"test-font")
    (dist / "private.txt").write_text("must-not-leak", encoding="utf-8")
    monkeypatch.setattr(pages, "SPA_DIR", dist)

    app = web.Application()
    app[LAN_APP_KEY] = SimpleNamespace(runtime=None)
    setup_routes(app)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        response = await client.get("/fonts/inter-var-latin.woff2")
        assert response.status == 200
        assert response.headers["Content-Type"].startswith("font/woff2")
        assert await response.read() == b"test-font"

        directory = await client.get("/fonts/")
        assert directory.status in {403, 404}
        assert "inter-var-latin.woff2" not in await directory.text()

        escaped = await client.get("/fonts/%2e%2e/private.txt")
        assert escaped.status in {403, 404}
        assert "must-not-leak" not in await escaped.text()
    finally:
        await client.close()
