"""Acceptance contracts for the legacy share and fallback paths."""
from pathlib import Path

import pytest

from tests.lan.test_lan_api import _make_client, _make_lan_app


def test_legacy_password_share_uses_verified_cookie_state_without_url_tokens():
    script = (Path(__file__).parents[2] / "AssetsManager" / "lan" / "static" / "share.js").read_text(
        encoding="utf-8"
    )

    assert "shareState.paths = d.share.paths || []" in script
    assert "shareState.allowPreview = d.share.allow_preview" in script
    assert "?token=" not in script


@pytest.mark.anyio
async def test_spa_page_routes_fall_back_to_legacy_shell_when_no_build_exists(tmp_path, monkeypatch):
    from AssetsManager.lan.routes import pages
    from AssetsManager.lan.routes import shares

    monkeypatch.setattr(pages, "_spa_index", lambda: None)
    monkeypatch.setattr(shares, "_spa_index", lambda: None)
    app, _, _ = _make_lan_app(tmp_path)
    client = await _make_client(app)
    try:
        expected = {
            "/": "/static/app.js",
            "/browse": "/static/app.js",
            "/login": "/static/login.js",
            "/detail": "/static/detail.js",
            "/s/missing-share": "/static/share.js",
        }
        for path, body in expected.items():
            response = await client.get(path)
            assert response.status == 200, path
            assert body in await response.text()
    finally:
        await client.close()


@pytest.mark.anyio
async def test_websocket_query_token_does_not_authenticate_a_connection(tmp_path):
    from aiohttp.client_exceptions import WSServerHandshakeError

    app, _, _ = _make_lan_app(tmp_path)
    client = await _make_client(app)
    try:
        with pytest.raises(WSServerHandshakeError) as error:
            await client.ws_connect("/ws?token=not-a-session")
        assert error.value.status == 401
    finally:
        await client.close()
