"""Acceptance contracts for the LAN SPA runtime paths."""
import pytest

from tests.lan.test_lan_api import _local_ui_headers, _make_client, _make_lan_app


@pytest.mark.anyio
async def test_spa_page_routes_return_503_when_no_build_exists(tmp_path, monkeypatch):
    from AssetsManager.lan.routes import pages

    monkeypatch.setattr(pages, "_spa_index", lambda: None)
    app, _, _ = _make_lan_app(tmp_path)
    client = await _make_client(app)
    try:
        for path in ("/", "/browse", "/login", "/detail", "/s/missing-share"):
            response = await client.get(path)
            assert response.status == 503, path
            assert "WebUI/build" in await response.text()
    finally:
        await client.close()


@pytest.mark.anyio
async def test_spa_page_routes_share_built_index_and_static_is_unavailable(tmp_path, monkeypatch):
    from AssetsManager.lan.routes import pages

    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<html>React SPA</html>", encoding="utf-8")
    (assets / "app.js").write_text("console.log('spa')", encoding="utf-8")
    monkeypatch.setattr(pages, "SPA_DIR", dist)

    app, _, _ = _make_lan_app(tmp_path)
    client = await _make_client(app)
    try:
        for path in ("/", "/browse", "/login", "/detail", "/s/missing-share"):
            response = await client.get(path)
            assert response.status == 200, path
            assert await response.text() == "<html>React SPA</html>"

        asset = await client.get("/assets/app.js")
        assert asset.status == 200
        assert await asset.text() == "console.log('spa')"

        assert not (tmp_path / "static" / "index.html").exists()
        assert not (tmp_path / "static" / "share.html").exists()
        legacy = await client.get("/static/index.html")
        assert legacy.status == 404
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


@pytest.mark.anyio
async def test_websocket_valid_query_token_does_not_authenticate_a_connection(tmp_path):
    from aiohttp.client_exceptions import WSServerHandshakeError

    app, _, _ = _make_lan_app(tmp_path)
    client = await _make_client(app)
    try:
        registered = await client.post(
            "/api/auth/register",
            json={"username": "query-user", "password": "Test@1234"},
        )
        token = registered.cookies["lan_token"].value
        client.session.cookie_jar.clear()

        with pytest.raises(WSServerHandshakeError) as error:
            await client.ws_connect(f"/ws?token={token}")
        assert error.value.status == 401
    finally:
        await client.close()


@pytest.mark.anyio
async def test_websocket_query_key_does_not_authenticate_a_connection(tmp_path):
    from aiohttp.client_exceptions import WSServerHandshakeError

    app, _, _ = _make_lan_app(tmp_path)
    client = await _make_client(app)
    try:
        with pytest.raises(WSServerHandshakeError) as error:
            await client.ws_connect("/ws?key=not-a-session")
        assert error.value.status == 401
    finally:
        await client.close()


@pytest.mark.anyio
async def test_websocket_valid_query_key_does_not_authenticate_a_connection(tmp_path):
    from aiohttp.client_exceptions import WSServerHandshakeError
    app, _, _ = _make_lan_app(tmp_path)
    client = await _make_client(app)
    try:
        with pytest.raises(WSServerHandshakeError) as error:
            await client.ws_connect("/ws?key=known-valid-key")
        assert error.value.status == 401
    finally:
        await client.close()


@pytest.mark.anyio
async def test_lan_preview_and_download_require_their_explicit_permissions(tmp_path, monkeypatch):
    from AssetsManager.core.settings import AppSettings

    app, library, _ = _make_lan_app(tmp_path)
    (library / "asset.png").write_bytes(b"not-used-after-permission-check")
    class _GuestSettings:
        def get(self, key, default=None):
            return {"lan_guest_preview": False, "lan_guest_download": False}.get(key, default)

    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda cls: _GuestSettings()))
    client = await _make_client(app)
    try:
        preview = await client.get("/api/thumbnails/asset.png")
        download = await client.get("/api/download/asset.png")

        assert preview.status == 403
        assert download.status == 403
    finally:
        await client.close()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("endpoint", "expected_status"),
    (
        ("/api/files?path=../outside", 400),
        ("/api/files?path=%2E%2E%2Foutside", 400),
        ("/api/thumbnails/..%2Foutside.txt", 400),
        ("/api/download/..%2Foutside.txt", 400),
    ),
)
async def test_lan_paths_cannot_escape_the_active_library_root(
    tmp_path, endpoint, expected_status
):
    app, _, _ = _make_lan_app(tmp_path)
    client = await _make_client(app)
    try:
        response = await client.get(endpoint, headers=_local_ui_headers(app))

        assert response.status == expected_status
    finally:
        await client.close()


def test_lan_server_rejects_connection_for_a_different_library_root(tmp_path):
    """The server rejects a connection requested for another root."""
    _, active_library, conn = _make_lan_app(tmp_path)
    wrong_library = tmp_path / "wrong-library"
    wrong_library.mkdir()

    try:
        with pytest.raises(
            ValueError,
            match="^Requested library does not match the active LAN server library$",
        ):
            from tests.lan.test_lan_api import _legacy_server

            _legacy_server(
                library_root=str(active_library),
                thumbnail_dir=str(tmp_path / "thumbs"),
                db_conn=conn,
            ).connection_for(wrong_library)
    finally:
        conn.close()


@pytest.mark.anyio
async def test_auth_cookie_is_httponly(tmp_path):
    app, _, _ = _make_lan_app(tmp_path)
    client = await _make_client(app)
    try:
        response = await client.post(
            "/api/auth/register",
            json={"username": "cookie-user", "password": "Test@1234"},
        )

        assert response.status == 200
        assert response.cookies["lan_token"]["httponly"] is True
    finally:
        await client.close()
