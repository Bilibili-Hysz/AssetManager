"""Unit tests for LAN API security and basic functionality."""
import asyncio
import os
import sqlite3
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _FakeLan:
    def __init__(self, library_root, db_conn, thumbnail_dir):
        self.library_root = library_root
        self.db_conn = db_conn
        self.thumbnail_dir = thumbnail_dir
        self.current_settings = {
            "show_hidden": False,
            "include_types": None,
            "exclude_patterns": [],
            "max_depth": 0,
        }
        self.blur_tags = set()
        self.access_key_hash = None
        self.password_hash = None
        self.share_name = "Test Share"
        self.token_secret = "test-secret"
        self._ssl_cert = None
        self._ssl_key = None
        self._port = 8080
        self.broadcasts = []
        from AssetsManager.lan.ws import WebSocketManager
        self.ws_manager = WebSocketManager()
        from AssetsManager.lan.scanner import DirectoryScanner
        self.scanner = DirectoryScanner(str(library_root), db_conn)

    def broadcast(self, event_type, data=None):
        self.broadcasts.append((event_type, data or {}))

    def connection_for(self, library_root=None):
        if library_root is not None and Path(library_root).resolve() != self.library_root.resolve():
            raise ValueError("wrong library root")
        return self.db_conn

    def invalidate_user_cache(self):
        pass


def _make_lan_app(tmp_path, *, authenticated_context_only=False):
    from aiohttp import web
    from AssetsManager.application.auth_service import AuthService
    from AssetsManager.core import database
    from AssetsManager.lan.api import setup_routes
    from AssetsManager.lan.auth import init_users_table, verify_auth_token
    from AssetsManager.lan.routes._helpers import (
        AUTH_SERVICE_APP_KEY,
        LAN_APP_KEY,
        get_auth_token,
        set_request_auth_context,
    )

    library = tmp_path / "library"
    library.mkdir()
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html></html>", encoding="utf-8")
    (static_dir / "share.html").write_text("<html>share</html>", encoding="utf-8")

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    try:
        conn.executescript(database._SCHEMA)
        conn.commit()
        init_users_table(conn)

        @web.middleware
        async def _test_auth_middleware(request, handler):
            if authenticated_context_only:
                set_request_auth_context(request, "user", {"username": "middleware-user", "role": "user"})
                return await handler(request)
            token = get_auth_token(request)
            if token:
                lan = request.app[LAN_APP_KEY]
                if verify_auth_token(token, lan.token_secret):
                    set_request_auth_context(request, "local_ui", {"username": "local_ui", "role": "admin"})
                else:
                    user = request.app[AUTH_SERVICE_APP_KEY].verify_user_token(token)
                    if user:
                        set_request_auth_context(request, "user", user)
            return await handler(request)

        app = web.Application(middlewares=[_test_auth_middleware])
        app[LAN_APP_KEY] = _FakeLan(library, conn, tmp_path / "thumbs")
        app[AUTH_SERVICE_APP_KEY] = AuthService(conn, "test-secret")
        async def _close_db(_app):
            from AssetsManager.core.database import close_all_dbs
            close_all_dbs()
            conn.close()
        app.on_cleanup.append(_close_db)
        setup_routes(app, static_dir)
        return app, library, conn
    except Exception:
        conn.close()
        raise


async def _read_body(resp):
    return await resp.read()


def pytest_configure(config):
    config.addinivalue_line("markers", "anyio: run test using anyio")


def pytest_generate_tests(metafunc):
    if "anyio_backend" in metafunc.fixturenames:
        metafunc.parametrize("anyio_backend", ["asyncio"])


async def _make_client(app):
    from aiohttp.test_utils import TestClient, TestServer

    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    return client


@pytest.mark.anyio
async def test_security_middleware_enforces_ip_whitelist():
    from aiohttp import web
    from AssetsManager.lan.security import IPBlacklist, RateLimiter, create_security_middleware

    async def handler(_request):
        return web.json_response({"ok": True})

    allowed_app = web.Application(
        middlewares=[
            create_security_middleware(
                RateLimiter(),
                IPBlacklist(),
                ip_whitelist=["127.0.0.1"],
            )
        ]
    )
    allowed_app.router.add_get("/", handler)

    denied_app = web.Application(
        middlewares=[
            create_security_middleware(
                RateLimiter(),
                IPBlacklist(),
                ip_whitelist=["10.0.0.1"],
            )
        ]
    )
    denied_app.router.add_get("/", handler)

    allowed_client = await _make_client(allowed_app)
    denied_client = await _make_client(denied_app)
    try:
        allowed = await allowed_client.get("/")
        denied = await denied_client.get("/")

        assert allowed.status == 200
        assert denied.status == 403
    finally:
        await allowed_client.close()
        await denied_client.close()


def _local_ui_headers(app):
    from AssetsManager.lan.utils import get_auth_headers
    from AssetsManager.lan.routes._helpers import LAN_APP_KEY

    return get_auth_headers(app[LAN_APP_KEY].token_secret)


async def _register_user_token(client, username="alice"):
    resp = await client.post(
        "/api/auth/register",
        json={"username": username, "password": "Test@1234"},
    )
    assert resp.status == 200
    return (await resp.json())["token"]


@pytest.mark.anyio
async def test_files_route_lists_library_items(tmp_path):
    app, library, conn = _make_lan_app(tmp_path)
    (library / "visible.txt").write_text("hello", encoding="utf-8")
    (library / ".hidden.txt").write_text("secret", encoding="utf-8")
    (library / "folder").mkdir()

    client = await _make_client(app)
    try:
        resp = await client.get("/api/files")
        assert resp.status == 200
        data = await resp.json()
        names = {item["name"] for item in data["items"]}
        assert "visible.txt" in names
        assert "folder" in names
        assert ".hidden.txt" not in names
    finally:
        await client.close()


@pytest.mark.anyio
async def test_auth_register_route_returns_user_token(tmp_path):
    app, library, conn = _make_lan_app(tmp_path)

    client = await _make_client(app)
    try:
        resp = await client.post(
            "/api/auth/register",
            json={"username": "newuser", "password": "Test@1234"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["user"]["username"] == "newuser"
        assert data["token"]
    finally:
        await client.close()


@pytest.mark.anyio
async def test_websocket_accepts_middleware_authenticated_cookie_context(tmp_path):
    """The WebSocket route must trust the auth context established by middleware."""
    app, library, conn = _make_lan_app(tmp_path)

    client = await _make_client(app)
    try:
        registered = await client.post(
            "/api/auth/register",
            json={"username": "socket-user", "password": "Test@1234"},
        )
        assert registered.status == 200
        cookie = registered.cookies["lan_token"].value

        websocket = await client.ws_connect("/ws", headers={"Cookie": f"lan_token={cookie}"})
        assert not websocket.closed
        await websocket.close()
    finally:
        await client.close()


@pytest.mark.anyio
async def test_websocket_accepts_existing_middleware_context_without_raw_token(tmp_path):
    """The route must not re-parse credentials after middleware authenticates a request."""
    app, library, conn = _make_lan_app(tmp_path, authenticated_context_only=True)

    client = await _make_client(app)
    try:
        websocket = await client.ws_connect("/ws")
        assert not websocket.closed
        await websocket.close()
    finally:
        await client.close()


@pytest.mark.anyio
async def test_websocket_rejects_request_without_auth_context(tmp_path):
    from aiohttp.client_exceptions import WSServerHandshakeError

    app, library, conn = _make_lan_app(tmp_path)
    client = await _make_client(app)
    try:
        with pytest.raises(WSServerHandshakeError) as exc_info:
            await client.ws_connect("/ws")
        assert exc_info.value.status == 401
    finally:
        await client.close()


@pytest.mark.anyio
async def test_websocket_manager_rejects_connections_over_limit(monkeypatch):
    from AssetsManager.lan import ws as ws_module

    class _Socket:
        async def close(self, **_kwargs):
            pass

    manager = ws_module.WebSocketManager()
    monkeypatch.setattr(ws_module, "MAX_WS_CONNECTIONS", 1)
    first = _Socket()
    second = _Socket()

    assert await manager.add(first) is True
    assert await manager.add(second) is False
    assert manager._clients == {first}
    await manager.close_all()


@pytest.mark.anyio
async def test_websocket_heartbeat_removes_client_when_ping_times_out(monkeypatch):
    from AssetsManager.lan import ws as ws_module

    release = asyncio.Event()

    class _Socket:
        closed = False

        async def ping(self):
            await release.wait()

        async def close(self, **_kwargs):
            self.closed = True

    manager = ws_module.WebSocketManager()
    socket = _Socket()
    manager._clients.add(socket)
    monkeypatch.setattr(ws_module, "WS_HEARTBEAT_INTERVAL", 0)
    monkeypatch.setattr(ws_module, "WS_OPERATION_TIMEOUT", 0.01)

    await manager._heartbeat()

    assert socket not in manager._clients
    assert socket.closed
class TestLanPermissionRegression:
    @staticmethod
    def _deny_guest_setting(monkeypatch, key):
        from AssetsManager.core.settings import AppSettings

        class _Settings:
            def get(self, name, default=None):
                if name == key:
                    return False
                return default

        monkeypatch.setattr(AppSettings, "instance", classmethod(lambda cls: _Settings()))

    @pytest.mark.anyio
    async def test_registered_user_cannot_create_share(self, tmp_path):
        app, library, conn = _make_lan_app(tmp_path)
        (library / "file.txt").write_text("content", encoding="utf-8")

        client = await _make_client(app)
        try:
            token = await _register_user_token(client)
            resp = await client.post(
                "/api/shares",
                json={"paths": ["file.txt"], "allow_preview": True},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status == 403
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_guest_files_route_requires_browse_permission(self, tmp_path, monkeypatch):
        self._deny_guest_setting(monkeypatch, "lan_guest_list")
        app, library, conn = _make_lan_app(tmp_path)
        (library / "file.txt").write_text("content", encoding="utf-8")

        client = await _make_client(app)
        try:
            resp = await client.get("/api/files")
            assert resp.status == 403
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_guest_metadata_routes_require_browse_permission(self, tmp_path, monkeypatch):
        self._deny_guest_setting(monkeypatch, "lan_guest_list")
        app, library, conn = _make_lan_app(tmp_path)
        (library / "asset.txt").write_text("content", encoding="utf-8")
        (library / "project").mkdir()

        client = await _make_client(app)
        try:
            for path in (
                "/api/meta/asset.txt",
                "/api/search",
                "/api/home",
                "/api/tree",
                "/api/projects",
                "/api/projects/project",
            ):
                resp = await client.get(path)
                assert resp.status == 403, path
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_guest_download_routes_require_download_permission(self, tmp_path, monkeypatch):
        self._deny_guest_setting(monkeypatch, "lan_guest_download")
        app, library, conn = _make_lan_app(tmp_path)
        (library / "file.txt").write_text("content", encoding="utf-8")

        client = await _make_client(app)
        try:
            single = await client.get("/api/download/file.txt")
            assert single.status == 403

            batch = await client.post("/api/download/batch", json={"paths": ["file.txt"]})
            assert batch.status == 403
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_guest_thumbnail_routes_require_preview_permission(self, tmp_path, monkeypatch):
        self._deny_guest_setting(monkeypatch, "lan_guest_preview")
        app, library, conn = _make_lan_app(tmp_path)
        (library / "file.png").write_bytes(b"not a real image")

        client = await _make_client(app)
        try:
            single = await client.get("/api/thumbnails/file.png")
            assert single.status == 403

            batch = await client.post("/api/thumbnails/batch", json={"paths": ["file.png"]})
            assert batch.status == 403
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_local_ui_token_can_create_share(self, tmp_path):
        app, library, conn = _make_lan_app(tmp_path)
        (library / "file.txt").write_text("content", encoding="utf-8")

        client = await _make_client(app)
        try:
            resp = await client.post(
                "/api/shares",
                json={"paths": ["file.txt"], "allow_preview": True},
                headers=_local_ui_headers(app),
            )
            assert resp.status == 200
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_admin_activity_routes_use_service_bundle(self, tmp_path):
        app, library, conn = _make_lan_app(tmp_path)

        client = await _make_client(app)
        try:
            activity = await client.get("/api/activity", headers=_local_ui_headers(app))
            assert activity.status == 200

            online = await client.get("/api/online-users", headers=_local_ui_headers(app))
            assert online.status == 200
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_tunnel_status_requires_authenticated_admin(self, tmp_path):
        app, library, conn = _make_lan_app(tmp_path)

        client = await _make_client(app)
        try:
            anonymous = await client.get("/api/tunnel/status")
            assert anonymous.status == 403

            admin = await client.get("/api/tunnel/status", headers=_local_ui_headers(app))
            assert admin.status == 200
        finally:
            await client.close()


@pytest.mark.anyio
async def test_metadata_route_returns_only_safe_http_urls(tmp_path):
    app, library, conn = _make_lan_app(tmp_path)
    target = library / "asset.txt"
    target.write_text("metadata", encoding="utf-8")
    conn.execute(
        "INSERT INTO file_meta(file_path, urls) VALUES (?, ?)",
        (str(target.resolve()), '["https://example.com/reference", "https:", "http:/missing-host", "javascript:alert(1)", "file:///private/path"]'),
    )
    conn.commit()

    client = await _make_client(app)
    try:
        response = await client.get("/api/meta/asset.txt")
        assert response.status == 200
        assert (await response.json())["urls"] == ["https://example.com/reference"]
    finally:
        await client.close()


def test_api_exports_auth_token_helper():
    from AssetsManager.lan.api import _get_auth_token

    class _Request:
        cookies = {"lan_token": "cookie-token"}
        headers = {}
        query = {}

    assert _get_auth_token(_Request()) == "cookie-token"


def test_auth_token_prefers_bearer_header_over_cookie():
    from AssetsManager.lan.api import _get_auth_token

    class _Request:
        cookies = {"lan_token": "cookie-token"}
        headers = {"Authorization": "Bearer header-token"}
        query = {}

    assert _get_auth_token(_Request()) == "header-token"


def test_lan_server_facade_accepts_ip_whitelist(monkeypatch):
    import AssetsManager.lan as lan

    captured = {}

    class _Impl:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(lan, "_HAS_AIOHTTP", True)
    monkeypatch.setattr("AssetsManager.lan.server._LanServerImpl", _Impl)

    lan.LanServer(
        library_root="library",
        thumbnail_dir="thumbs",
        db_conn=object(),
        ip_whitelist=["127.0.0.1"],
    )

    assert captured["ip_whitelist"] == ["127.0.0.1"]


@pytest.mark.anyio
async def test_download_route_serves_file(tmp_path):
    app, library, conn = _make_lan_app(tmp_path)
    (library / "asset.txt").write_text("download me", encoding="utf-8")

    client = await _make_client(app)
    try:
        resp = await client.get("/api/download/asset.txt", headers=_local_ui_headers(app))
        assert resp.status == 200
        assert await _read_body(resp) == b"download me"
    finally:
        await client.close()


@pytest.mark.anyio
async def test_meta_route_uses_lan_connection(tmp_path):
    app, library, conn = _make_lan_app(tmp_path)
    target = library / "asset.txt"
    target.write_text("tag me", encoding="utf-8")
    conn.execute(
        "INSERT INTO file_tags(file_path, tag) VALUES (?, ?)",
        (str(target.resolve()), "hero"),
    )
    conn.commit()

    client = await _make_client(app)
    try:
        resp = await client.get("/api/meta/asset.txt")
        assert resp.status == 200
        data = await resp.json()
        assert data["tags"] == ["hero"]
    finally:
        await client.close()


@pytest.mark.anyio
async def test_tags_route_writes_only_library_paths(tmp_path):
    app, library, conn = _make_lan_app(tmp_path)
    target = library / "asset.txt"
    target.write_text("tag me", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")

    client = await _make_client(app)
    try:
        unauth = await client.post("/api/tags", json={"tag": "hero", "file_path": "asset.txt"})
        assert unauth.status == 403

        resp = await client.post(
            "/api/tags",
            json={"tag": "hero", "file_path": "asset.txt"},
            headers=_local_ui_headers(app),
        )
        assert resp.status == 200
        row = conn.execute(
            "SELECT tag FROM file_tags WHERE file_path=?", (str(target.resolve()),)
        ).fetchone()
        assert row == ("hero",)

        escape_resp = await client.post(
            "/api/tags",
            json={"tag": "bad", "file_path": "../outside.txt"},
            headers=_local_ui_headers(app),
        )
        assert escape_resp.status == 400

        absolute_resp = await client.post(
            "/api/tags",
            json={"tag": "bad", "file_path": str(outside)},
            headers=_local_ui_headers(app),
        )
        assert absolute_resp.status == 400

        missing_path = await client.post(
            "/api/tags",
            json={"tag": "bad"},
            headers=_local_ui_headers(app),
        )
        assert missing_path.status == 400
    finally:
        await client.close()


@pytest.mark.anyio
async def test_share_routes_create_and_download_scoped_file(tmp_path):
    app, library, conn = _make_lan_app(tmp_path)
    folder = library / "project"
    folder.mkdir()
    asset = folder / "asset.txt"
    asset.write_text("shared asset", encoding="utf-8")
    (library / "private.txt").write_text("private", encoding="utf-8")

    client = await _make_client(app)
    try:
        create = await client.post(
            "/api/shares",
            json={"paths": ["project"], "allow_preview": True},
            headers=_local_ui_headers(app),
        )
        assert create.status == 200
        share = await create.json()
        share_id = share["id"]

        download = await client.get(f"/api/shares/{share_id}/download/project/asset.txt")
        assert download.status == 200
        assert await _read_body(download) == b"shared asset"

        blocked = await client.get(f"/api/shares/{share_id}/download/private.txt")
        assert blocked.status == 403
    finally:
        await client.close()


@pytest.mark.anyio
async def test_share_download_limit_returns_forbidden(tmp_path):
    app, library, conn = _make_lan_app(tmp_path)
    target = library / "asset.txt"
    target.write_text("shared asset", encoding="utf-8")

    client = await _make_client(app)
    try:
        create = await client.post(
            "/api/shares",
            json={"paths": ["asset.txt"], "max_downloads": 1, "allow_preview": True},
            headers=_local_ui_headers(app),
        )
        assert create.status == 200
        share_id = (await create.json())["id"]

        first = await client.get(f"/api/shares/{share_id}/download/asset.txt")
        assert first.status == 200
        assert await _read_body(first) == b"shared asset"

        second = await client.get(f"/api/shares/{share_id}/download/asset.txt")
        assert second.status == 403
        assert (await second.json())["error"] == "Download limit reached"

        row = conn.execute("SELECT download_count FROM share_links WHERE id=?", (share_id,)).fetchone()
        assert row == (1,)
    finally:
        await client.close()


@pytest.mark.anyio
async def test_share_download_rejected_when_increment_fails(tmp_path, monkeypatch):
    """When increment_download fails (limit reached / not found), 403 is returned."""
    from AssetsManager.application.share_service import ShareService

    app, library, conn = _make_lan_app(tmp_path)
    target = library / "asset.txt"
    target.write_text("shared asset", encoding="utf-8")

    client = await _make_client(app)
    try:
        create = await client.post(
            "/api/shares",
            json={"paths": ["asset.txt"], "allow_preview": True},
            headers=_local_ui_headers(app),
        )
        assert create.status == 200
        share_id = (await create.json())["id"]

        monkeypatch.setattr(ShareService, "increment_download", lambda _self, _share_id: False)

        resp = await client.get(f"/api/shares/{share_id}/download/asset.txt")
        assert resp.status == 403  # limit reached / increment failed

        row = conn.execute("SELECT download_count FROM share_links WHERE id=?", (share_id,)).fetchone()
        assert row == (0,)
    finally:
        await client.close()


@pytest.mark.anyio
async def test_share_download_increments_counter_after_successful_response(tmp_path):
    app, library, conn = _make_lan_app(tmp_path)
    target = library / "asset.txt"
    target.write_text("shared asset", encoding="utf-8")

    client = await _make_client(app)
    try:
        create = await client.post(
            "/api/shares",
            json={"paths": ["asset.txt"], "max_downloads": 5, "allow_preview": True},
            headers=_local_ui_headers(app),
        )
        assert create.status == 200
        share_id = (await create.json())["id"]

        row_before = conn.execute("SELECT download_count FROM share_links WHERE id=?", (share_id,)).fetchone()
        assert row_before == (0,)

        resp = await client.get(f"/api/shares/{share_id}/download/asset.txt")
        assert resp.status == 200
        assert await _read_body(resp) == b"shared asset"

        row_after = conn.execute("SELECT download_count FROM share_links WHERE id=?", (share_id,)).fetchone()
        assert row_after == (1,)
    finally:
        await client.close()


@pytest.mark.anyio
async def test_share_download_limit_prevents_download_when_reached(tmp_path):
    app, library, conn = _make_lan_app(tmp_path)
    target = library / "asset.txt"
    target.write_text("shared asset", encoding="utf-8")

    client = await _make_client(app)
    try:
        create = await client.post(
            "/api/shares",
            json={"paths": ["asset.txt"], "max_downloads": 1, "allow_preview": True},
            headers=_local_ui_headers(app),
        )
        assert create.status == 200
        share_id = (await create.json())["id"]

        first = await client.get(f"/api/shares/{share_id}/download/asset.txt")
        assert first.status == 200

        second = await client.get(f"/api/shares/{share_id}/download/asset.txt")
        assert second.status == 403
        assert (await second.json())["error"] == "Download limit reached"

        row = conn.execute("SELECT download_count FROM share_links WHERE id=?", (share_id,)).fetchone()
        assert row == (1,)
    finally:
        await client.close()


class TestPathTraversal:
    """Test that path traversal attacks are blocked."""

    def test_path_validation_basic(self):
        """Paths outside the library root should be rejected."""
        from pathlib import Path
        library_root = Path("/data/library")
        target = Path("/data/library/../../../etc/passwd")
        # The resolved path should be checked
        resolved = target.resolve()
        root_resolved = library_root.resolve()
        assert not str(resolved).startswith(str(root_resolved) + os.sep)

    def test_path_prefix_not_partial_match(self):
        """String prefix check can be fooled by similar names."""
        from pathlib import Path
        root = Path("/data/proj")
        # /data/project should NOT be under /data/proj
        candidate = Path("/data/project/secret.txt")
        # Correct check: is_relative_to
        try:
            assert not candidate.is_relative_to(root)
        except AttributeError:
            # Python < 3.9 fallback
            assert not str(candidate.resolve()).startswith(str(root.resolve()) + os.sep)

    def test_validate_path_blocks_escape(self, tmp_path):
        from types import SimpleNamespace
        from aiohttp import web
        from AssetsManager.lan.api import _validate_path

        root = tmp_path / "library"
        root.mkdir()
        lan = SimpleNamespace(library_root=root)

        try:
            _validate_path(lan, "../outside.txt")
        except web.HTTPBadRequest:
            pass
        else:
            raise AssertionError("path traversal was not blocked")

    def test_validated_existing_key_requires_library_path(self, tmp_path):
        from types import SimpleNamespace
        from aiohttp import web
        from AssetsManager.lan.api import _validated_existing_key

        root = tmp_path / "library"
        root.mkdir()
        inside = root / "file.txt"
        inside.write_text("ok", encoding="utf-8")
        outside = tmp_path / "outside.txt"
        outside.write_text("no", encoding="utf-8")
        lan = SimpleNamespace(library_root=root)

        assert _validated_existing_key(lan, "file.txt") == str(inside.resolve())
        try:
            _validated_existing_key(lan, str(outside))
        except web.HTTPBadRequest:
            pass
        else:
            raise AssertionError("absolute path outside the library was accepted")

    def test_validated_existing_key_requires_existing_file(self, tmp_path):
        from types import SimpleNamespace
        from aiohttp import web
        from AssetsManager.lan.api import _validated_existing_key

        root = tmp_path / "library"
        root.mkdir()
        lan = SimpleNamespace(library_root=root)

        try:
            _validated_existing_key(lan, "missing.txt")
        except web.HTTPNotFound:
            pass
        else:
            raise AssertionError("missing path was accepted")


class TestRateLimiter:
    """Test rate limiter behavior."""

    def test_basic_limit(self):
        """Requests within limit should be allowed."""
        from AssetsManager.lan.security import RateLimiter
        limiter = RateLimiter(max_requests=5, window_seconds=1)
        for _ in range(5):
            assert limiter.is_allowed("127.0.0.1") is True
        assert limiter.is_allowed("127.0.0.1") is False

    def test_different_ips_independent(self):
        """Different IPs should have independent limits."""
        from AssetsManager.lan.security import RateLimiter
        limiter = RateLimiter(max_requests=2, window_seconds=1)
        assert limiter.is_allowed("10.0.0.1") is True
        assert limiter.is_allowed("10.0.0.2") is True
        assert limiter.is_allowed("10.0.0.1") is True
        assert limiter.is_allowed("10.0.0.2") is True
        assert limiter.is_allowed("10.0.0.1") is False
        assert limiter.is_allowed("10.0.0.2") is False

    def test_lru_eviction_updates_on_access(self):
        """Recent IPs should survive max-IP eviction."""
        from AssetsManager.lan.security import RateLimiter
        limiter = RateLimiter(max_requests=10, window_seconds=60, max_ips=2)

        assert limiter.is_allowed("10.0.0.1") is True
        assert limiter.is_allowed("10.0.0.2") is True
        assert limiter.is_allowed("10.0.0.1") is True
        assert limiter.is_allowed("10.0.0.3") is True

        assert "10.0.0.1" in limiter._requests
        assert "10.0.0.2" not in limiter._requests
        assert "10.0.0.3" in limiter._requests


class TestAuth:
    """Test authentication utilities."""

    def test_password_hashing(self):
        """Password should be hashed, not stored in plaintext."""
        import hashlib
        import secrets
        password = "test_password"
        salt = secrets.token_hex(8)
        hashed = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
        assert hashed != password
        assert len(hashed) == 64  # SHA-256 hex

    def test_different_passwords_different_hashes(self):
        """Different passwords should produce different hashes."""
        import hashlib
        salt = "fixed_salt"
        h1 = hashlib.sha256(f"{salt}:pass1".encode()).hexdigest()
        h2 = hashlib.sha256(f"{salt}:pass2".encode()).hexdigest()
        assert h1 != h2

    def test_token_generation(self):
        """Generated tokens should be unique and non-empty."""
        import secrets
        t1 = secrets.token_urlsafe(6)
        t2 = secrets.token_urlsafe(6)
        assert t1 != t2
        assert len(t1) > 0


class TestCache:
    """Test unified cache framework."""

    def test_lru_eviction(self):
        from AssetsManager.core.cache import LRUCache
        c = LRUCache(3)
        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)
        assert len(c) == 3
        c.set("d", 4)  # evicts "a"
        assert c.get("a") is None
        assert c.get("d") == 4

    def test_lru_access_refreshes(self):
        from AssetsManager.core.cache import LRUCache
        c = LRUCache(3)
        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)
        c.get("a")  # refresh "a"
        c.set("d", 4)  # evicts "b" (least recently used)
        assert c.get("a") == 1
        assert c.get("b") is None

    def test_ttl_expiry(self):
        import time
        from AssetsManager.core.cache import TTLCache
        c = TTLCache(ttl_seconds=0.1, max_size=10)
        c.set("x", 42)
        assert "x" in c
        assert c.get("x") == 42
        time.sleep(0.15)
        assert "x" not in c
        assert c.get("x") is None

    def test_dict_cache_basic(self):
        from AssetsManager.core.cache import DictCache
        c = DictCache()
        c.set("key", "value")
        assert c.get("key") == "value"
        assert "key" in c
        c.invalidate("key")
        assert "key" not in c


class TestSingleton:
    """Test thread-safe singleton pattern."""

    def test_singleton_returns_same_instance(self):
        from AssetsManager.core.singleton import ThreadSafeSingleton
        class Dummy:
            _singleton_instance = None
        inst1 = ThreadSafeSingleton.get(Dummy)
        inst2 = ThreadSafeSingleton.get(Dummy)
        assert inst1 is inst2

    def test_singleton_reset(self):
        from AssetsManager.core.singleton import ThreadSafeSingleton
        class Dummy2:
            _singleton_instance = None
        inst1 = ThreadSafeSingleton.get(Dummy2)
        ThreadSafeSingleton.reset(Dummy2)
        inst2 = ThreadSafeSingleton.get(Dummy2)
        assert inst1 is not inst2


class TestJsonStore:
    """Test JsonStore base class."""

    def test_atomic_write(self, tmp_path):
        from AssetsManager.core.json_store import JsonStore
        import json

        class SimpleStore(JsonStore):
            def __init__(self, path):
                super().__init__(path)
                self._data = {}
            def _default_data(self):
                return {}
            def _on_loaded(self, data):
                self._data = data if isinstance(data, dict) else {}
            def _on_before_save(self):
                return self._data

        path = tmp_path / "test.json"
        store = SimpleStore(path)
        store._data = {"key": "value"}
        store._save()

        assert path.exists()
        loaded = json.loads(path.read_text())
        assert loaded == {"key": "value"}

    def test_lazy_loading(self, tmp_path):
        from AssetsManager.core.json_store import JsonStore
        import json

        class SimpleStore(JsonStore):
            def __init__(self, path):
                super().__init__(path)
                self._data = {}
            def _default_data(self):
                return {"default": True}
            def _on_loaded(self, data):
                self._data = data if isinstance(data, dict) else {}
            def _on_before_save(self):
                return self._data

        path = tmp_path / "test.json"
        path.write_text(json.dumps({"loaded": True}))

        store = SimpleStore(path)
        assert not store._loaded
        store._ensure_loaded()
        assert store._loaded
        assert store._data == {"loaded": True}

    def test_default_data_on_missing_file(self, tmp_path):
        from AssetsManager.core.json_store import JsonStore

        class SimpleStore(JsonStore):
            def __init__(self, path):
                super().__init__(path)
                self._data = {}
            def _default_data(self):
                return {"default": True}
            def _on_loaded(self, data):
                self._data = data if isinstance(data, dict) else {}
            def _on_before_save(self):
                return self._data

        path = tmp_path / "nonexistent.json"
        store = SimpleStore(path)
        store._ensure_loaded()
        assert store._data == {"default": True}


class TestShareSecurity:
    """Security regression tests for share endpoints."""

    @pytest.mark.anyio
    async def test_share_download_blocks_path_traversal(self, tmp_path):
        app, library, conn = _make_lan_app(tmp_path)
        folder = library / "secret"
        folder.mkdir()
        (folder / "data.txt").write_text("secret data", encoding="utf-8")
        (library / "public.txt").write_text("public", encoding="utf-8")

        client = await _make_client(app)
        try:
            create = await client.post(
                "/api/shares",
                json={"paths": ["public.txt"], "allow_preview": True},
                headers=_local_ui_headers(app),
            )
            assert create.status == 200
            share_id = (await create.json())["id"]

            traversal = await client.get(f"/api/shares/{share_id}/download/../../../secret/data.txt")
            assert traversal.status in (403, 404)
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_share_download_blocks_dotdot_within_share_prefix(self, tmp_path):
        """A rel_path like project/../public.txt must not escape share scope."""
        app, library, conn = _make_lan_app(tmp_path)
        folder = library / "project"
        folder.mkdir()
        (folder / "data.txt").write_text("project data", encoding="utf-8")
        (library / "public.txt").write_text("public data", encoding="utf-8")

        client = await _make_client(app)
        try:
            create = await client.post(
                "/api/shares",
                json={"paths": ["project"], "allow_preview": True},
                headers=_local_ui_headers(app),
            )
            assert create.status == 200
            share_id = (await create.json())["id"]

            # Legitimate access works
            ok = await client.get(f"/api/shares/{share_id}/download/project/data.txt")
            assert ok.status == 200

            # dot-dot escapes the share scope even though it starts with "project/"
            blocked = await client.get(f"/api/shares/{share_id}/download/project/../public.txt")
            assert blocked.status == 403
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_share_verify_does_not_leak_password_hash(self, tmp_path):
        app, library, conn = _make_lan_app(tmp_path)
        (library / "file.txt").write_text("content", encoding="utf-8")

        client = await _make_client(app)
        try:
            create = await client.post(
                "/api/shares",
                json={"paths": ["file.txt"], "password": "secret123", "allow_preview": True},
                headers=_local_ui_headers(app),
            )
            assert create.status == 200
            share_id = (await create.json())["id"]

            verify = await client.post(f"/api/shares/{share_id}/verify", json={"password": "secret123"})
            assert verify.status == 200
            data = await verify.json()
            assert "password_hash" not in data.get("share", {})
            assert data.get("share", {}).get("has_password") is not True or "password_hash" not in str(data)
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_share_verify_sets_scoped_http_only_cookie_without_token(self, tmp_path):
        app, library, conn = _make_lan_app(tmp_path)
        (library / "file.txt").write_text("content", encoding="utf-8")

        client = await _make_client(app)
        try:
            create = await client.post(
                "/api/shares",
                json={"paths": ["file.txt"], "password": "secret123", "allow_preview": True},
                headers=_local_ui_headers(app),
            )
            assert create.status == 200
            share_id = (await create.json())["id"]

            verify = await client.post(f"/api/shares/{share_id}/verify", json={"password": "secret123"})
            assert verify.status == 200
            data = await verify.json()
            assert "token" not in data
            cookie = verify.headers["Set-Cookie"]
            assert "HttpOnly" in cookie
            assert f"Path=/api/shares/{share_id}" in cookie

            info = await client.get(f"/api/shares/{share_id}/info")
            assert info.status == 200
            assert (await info.json())["paths"] == ["file.txt"]

            download = await client.get(f"/api/shares/{share_id}/download/file.txt")
            assert download.status == 200
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_share_verify_api_client_returns_bearer_token_and_keeps_cookie(self, tmp_path):
        app, library, conn = _make_lan_app(tmp_path)
        (library / "file.txt").write_text("content", encoding="utf-8")

        client = await _make_client(app)
        try:
            create = await client.post(
                "/api/shares",
                json={"paths": ["file.txt"], "password": "secret123", "allow_preview": True},
                headers=_local_ui_headers(app),
            )
            assert create.status == 200
            share_id = (await create.json())["id"]

            verify = await client.post(
                f"/api/shares/{share_id}/verify",
                json={"password": "secret123"},
                headers={"X-AssetsManager-API-Client": "1"},
            )
            assert verify.status == 200
            data = await verify.json()
            token = data["token"]
            assert token
            assert "share_token" not in verify.cookies

            client.session.cookie_jar.clear()
            download = await client.get(
                f"/api/shares/{share_id}/download/file.txt",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert download.status == 200
            assert await _read_body(download) == b"content"
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_share_preview_requires_token_when_password_protected(self, tmp_path):
        app, library, conn = _make_lan_app(tmp_path)
        (library / "image.png").write_bytes(b"\x89PNG")

        client = await _make_client(app)
        try:
            create = await client.post(
                "/api/shares",
                json={"paths": ["image.png"], "password": "secret123", "allow_preview": True},
                headers=_local_ui_headers(app),
            )
            assert create.status == 200
            share_id = (await create.json())["id"]

            preview_no_token = await client.get(f"/api/shares/{share_id}/preview/image.png")
            assert preview_no_token.status == 401

            verify = await client.post(f"/api/shares/{share_id}/verify", json={"password": "secret123"})
            assert verify.status == 200
            preview = await client.get(f"/api/shares/{share_id}/preview/image.png")
            assert preview.status == 200
        finally:
            await client.close()

    def test_share_token_signature_is_128_bit(self):
        from AssetsManager.lan.auth import generate_share_token
        token = generate_share_token("test-share", "test-secret")
        _, sig = token.split(".", 1)
        assert len(sig) == 32  # 32 hex chars = 128 bits

    @pytest.mark.anyio
    async def test_share_endpoints_accessible_through_auth_middleware(self, tmp_path):
        app, library, conn = _make_lan_app(tmp_path)
        (library / "file.txt").write_text("content", encoding="utf-8")

        client = await _make_client(app)
        try:
            create = await client.post(
                "/api/shares",
                json={"paths": ["file.txt"], "allow_preview": True},
                headers=_local_ui_headers(app),
            )
            assert create.status == 200
            share_id = (await create.json())["id"]

            info = await client.get(f"/api/shares/{share_id}/info")
            assert info.status == 200
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_list_shares_requires_authenticated_user_context(self, tmp_path):
        app, library, conn = _make_lan_app(tmp_path)
        (library / "file.txt").write_text("content", encoding="utf-8")

        client = await _make_client(app)
        try:
            create = await client.post(
                "/api/shares",
                json={"paths": ["file.txt"], "allow_preview": True},
                headers=_local_ui_headers(app),
            )
            assert create.status == 200

            list_resp = await client.get("/api/shares")
            assert list_resp.status == 403
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_list_shares_rejects_missing_user_after_permission_check(self, monkeypatch):
        from AssetsManager.lan.routes import shares

        monkeypatch.setattr(shares, "require_permission", lambda request, permission: True)
        monkeypatch.setattr(shares, "get_lan", lambda request: object())
        monkeypatch.setattr(shares, "get_share_service", lambda request: object())
        monkeypatch.setattr(shares, "get_request_user", lambda request: None)

        response = await shares.handle_list_shares(object())

        assert response.status == 401

    @pytest.mark.anyio
    async def test_access_key_auth_sets_admin_context_for_shares(self, tmp_path):
        import warnings
        from aiohttp.test_utils import TestClient, TestServer
        from aiohttp.web import NotAppKeyWarning
        from AssetsManager.core import database
        from AssetsManager.lan.auth import init_users_table
        from AssetsManager.lan.routes._helpers import AUTH_SERVICE_APP_KEY
        from AssetsManager.lan.server import _LanServerImpl

        library = tmp_path / "library"
        library.mkdir()
        (library / "file.txt").write_text("content", encoding="utf-8")
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript(database._SCHEMA)
            conn.commit()
            init_users_table(conn)
            server = _LanServerImpl(
                library_root=str(library),
                thumbnail_dir=str(tmp_path / "thumbs"),
                db_conn=conn,
                access_key="raw-key",
            )
            server._app[AUTH_SERVICE_APP_KEY] = server._auth_service

            client = TestClient(TestServer(server._app))
            await client.start_server()
            try:
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always", NotAppKeyWarning)
                    create = await client.post(
                        "/api/shares?key=raw-key",
                        json={"paths": ["file.txt"], "allow_preview": True},
                    )
                    assert create.status == 200
                    share_id = (await create.json())["id"]

                    create_for_delete = await client.post(
                        "/api/shares?key=raw-key",
                        json={"paths": ["file.txt"], "allow_preview": True},
                    )
                    assert create_for_delete.status == 200
                    share_id_for_delete = (await create_for_delete.json())["id"]

                    list_resp = await client.get("/api/shares?key=raw-key")
                    assert list_resp.status == 200
                    data = await list_resp.json()

                    unauth_delete = await client.delete(f"/api/shares/{share_id}")
                    assert unauth_delete.status == 401

                    delete_resp = await client.delete(f"/api/shares/{share_id_for_delete}?key=raw-key")
                    assert delete_resp.status == 200
                assert not [w for w in caught if issubclass(w.category, NotAppKeyWarning)]
                assert len(data["shares"]) == 2
            finally:
                await client.close()
        finally:
            conn.close()


class TestMiddlewarePrecedenceRegression:
    """Regression: operator precedence in auth middleware skip list."""

    @pytest.mark.anyio
    async def test_share_info_get_accessible_without_auth(self, tmp_path):
        """GET /api/shares/{id}/info must be accessible without auth (public endpoint)."""
        app, library, conn = _make_lan_app(tmp_path)
        (library / "file.txt").write_text("content", encoding="utf-8")

        client = await _make_client(app)
        try:
            create = await client.post(
                "/api/shares",
                json={"paths": ["file.txt"], "allow_preview": True},
                headers=_local_ui_headers(app),
            )
            assert create.status == 200
            share_id = (await create.json())["id"]

            info = await client.get(f"/api/shares/{share_id}/info")
            assert info.status == 200
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_non_get_share_endpoints_require_auth(self, tmp_path):
        """POST /api/shares/{id}/verify is now public (share links must be accessible)."""
        from AssetsManager.lan.server import _LanServerImpl
        from AssetsManager.lan.auth import hash_password, init_users_table
        from AssetsManager.core import database

        library = tmp_path / "library"
        library.mkdir()
        (library / "file.txt").write_text("content", encoding="utf-8")

        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript(database._SCHEMA)
            init_users_table(conn)
            conn.commit()

            server = _LanServerImpl(
                library_root=str(library),
                thumbnail_dir=str(tmp_path / "thumbs"),
                db_conn=conn,
                password=hash_password("Test@1234"),
                access_key=None,
            )

            from aiohttp.test_utils import TestClient, TestServer
            client = TestClient(TestServer(server._app))
            await client.start_server()
            try:
                resp = await client.get("/api/shares/nonexistent/info")
                assert resp.status != 401  # bypasses auth middleware (public)

                resp2 = await client.post("/api/shares/nonexistent/verify", json={"password": "x"})
                assert resp2.status != 401  # also bypasses auth middleware (public — share links accessible without server auth)
            finally:
                await client.close()
        finally:
            conn.close()

    @pytest.mark.anyio
    async def test_spa_assets_are_public_when_server_auth_is_enabled(self, tmp_path):
        """The SPA must load its hashed bundles before a user can log in."""
        from AssetsManager.lan.server import _LanServerImpl
        from AssetsManager.lan.auth import hash_password, init_users_table
        from AssetsManager.core import database
        from aiohttp.test_utils import TestClient, TestServer

        library = tmp_path / "library"
        library.mkdir()
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript(database._SCHEMA)
            init_users_table(conn)
            conn.commit()
            server = _LanServerImpl(
                library_root=str(library),
                thumbnail_dir=str(tmp_path / "thumbs"),
                db_conn=conn,
                password=hash_password("Test@1234"),
            )
            spa_assets = Path(__file__).parent.parent.parent / "webui" / "dist" / "assets"
            asset = next(spa_assets.glob("*.js"))
            client = TestClient(TestServer(server._app))
            await client.start_server()
            try:
                response = await client.get(f"/assets/{asset.name}")
                assert response.status == 200
            finally:
                await client.close()
        finally:
            conn.close()

    @pytest.mark.anyio
    async def test_password_share_cookie_authenticates_scoped_routes_with_server_auth(self, tmp_path):
        """A public password-share flow must work while server auth protects APIs."""
        from aiohttp.test_utils import TestClient, TestServer
        from AssetsManager.core import database
        from AssetsManager.lan.auth import hash_password, init_users_table
        from AssetsManager.lan.routes._helpers import AUTH_SERVICE_APP_KEY
        from AssetsManager.lan.server import _LanServerImpl

        library = tmp_path / "library"
        library.mkdir()
        (library / "shared.txt").write_text("shared", encoding="utf-8")
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript(database._SCHEMA)
            init_users_table(conn)
            conn.commit()
            server = _LanServerImpl(
                library_root=str(library),
                thumbnail_dir=str(tmp_path / "thumbs"),
                db_conn=conn,
                password=hash_password("Server@1234"),
            )
            server._app[AUTH_SERVICE_APP_KEY] = server._auth_service
            client = TestClient(TestServer(server._app))
            await client.start_server()
            try:
                created = await client.post(
                    "/api/shares",
                    json={"paths": ["shared.txt"], "password": "share123", "allow_preview": True},
                    headers=_local_ui_headers(server._app),
                )
                assert created.status == 200
                share_id = (await created.json())["id"]

                verified = await client.post(
                    f"/api/shares/{share_id}/verify", json={"password": "share123"}
                )
                assert verified.status == 200
                assert "token" not in await verified.json()
                cookie = verified.headers["Set-Cookie"]
                assert "HttpOnly" in cookie
                assert f"Path=/api/shares/{share_id}" in cookie

                downloaded = await client.get(f"/api/shares/{share_id}/download/shared.txt")
                assert downloaded.status == 200
                assert await downloaded.read() == b"shared"
            finally:
                await client.close()
        finally:
            conn.close()


class TestPasswordHashLeakRegression:
    """Regression: password_hash must not appear in API responses."""

    @pytest.mark.anyio
    async def test_users_endpoint_strips_password_hash(self, tmp_path):
        from AssetsManager.lan.server import _LanServerImpl
        from AssetsManager.lan.auth import hash_password, init_users_table
        from AssetsManager.core import database

        library = tmp_path / "library"
        library.mkdir()

        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript(database._SCHEMA)
            init_users_table(conn)
            conn.execute(
                "INSERT INTO users (username, password, role, is_active) VALUES (?, ?, 'admin', 1)",
                ("admin", hash_password("Admin@1234")),
            )
            conn.commit()

            server = _LanServerImpl(
                library_root=str(library),
                thumbnail_dir=str(tmp_path / "thumbs"),
                db_conn=conn,
                access_key="admin-key",
            )

            from aiohttp.test_utils import TestClient, TestServer
            client = TestClient(TestServer(server._app))
            await client.start_server()
            try:
                resp = await client.get("/api/users?key=admin-key")
                assert resp.status == 200
                data = await resp.json()
                for u in data["users"]:
                    assert "password_hash" not in u
            finally:
                await client.close()
        finally:
            conn.close()

    @pytest.mark.anyio
    async def test_share_info_does_not_leak_password_protected_paths(self, tmp_path):
        app, library, conn = _make_lan_app(tmp_path)
        (library / "secret.txt").write_text("secret", encoding="utf-8")

        client = await _make_client(app)
        try:
            create = await client.post(
                "/api/shares",
                json={"paths": ["secret.txt"], "password": "secret123", "allow_preview": True},
                headers=_local_ui_headers(app),
            )
            assert create.status == 200
            share_id = (await create.json())["id"]

            info = await client.get(f"/api/shares/{share_id}/info")
            assert info.status == 200
            data = await info.json()
            assert data["has_password"] is True
            assert "paths" not in data
            assert "created_by" not in data
            assert "download_count" not in data

            verify = await client.post(f"/api/shares/{share_id}/verify", json={"password": "secret123"})
            assert verify.status == 200
            authed_info = await client.get(f"/api/shares/{share_id}/info")
            assert authed_info.status == 200
            authed_data = await authed_info.json()
            assert authed_data["paths"] == ["secret.txt"]
            assert authed_data["created_by"] == "local_ui"
            assert "download_count" in authed_data
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_batch_download_rejects_too_many_paths(self, tmp_path):
        app, library, conn = _make_lan_app(tmp_path)
        (library / "file.txt").write_text("content", encoding="utf-8")

        client = await _make_client(app)
        try:
            resp = await client.post(
                "/api/download/batch",
                json={"paths": ["file.txt"] * 101},
                headers=_local_ui_headers(app),
            )
            assert resp.status == 400
            data = await resp.json()
            assert "Too many paths" in data["error"]
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_batch_download_requires_json_paths_contract(self, tmp_path):
        app, library, conn = _make_lan_app(tmp_path)
        (library / "file.txt").write_text("content", encoding="utf-8")

        client = await _make_client(app)
        try:
            form = await client.post(
                "/api/download/batch",
                data={"paths": '["file.txt"]'},
                headers=_local_ui_headers(app),
            )
            assert form.status == 400

            json_response = await client.post(
                "/api/download/batch",
                json={"paths": ["file.txt"]},
                headers=_local_ui_headers(app),
            )
            assert json_response.status == 200
            assert json_response.headers["Content-Type"].startswith("application/zip")
        finally:
            await client.close()


def test_file_response_cleanup_runs_when_write_fails(tmp_path):
    import os
    import pytest
    from AssetsManager.lan.routes.downloads import _file_response_with_cleanup

    zip_path = tmp_path / "download.zip"
    zip_path.write_bytes(b"zip")

    async def _fail(_data=b""):
        raise RuntimeError("client disconnected")

    response = _file_response_with_cleanup(str(zip_path), filename="download.zip", write_eof=_fail)

    async def _run():
        with pytest.raises(RuntimeError):
            await response.write_eof()

    import anyio
    anyio.run(_run)
    assert not os.path.exists(zip_path)


def test_legacy_viewer_css_matches_script_visibility_class():
    static_dir = Path(__file__).parents[2] / "AssetsManager" / "lan" / "static"
    script = (static_dir / "app.js").read_text(encoding="utf-8")
    stylesheet = (static_dir / "style.css").read_text(encoding="utf-8")

    assert 'overlay.classList.add("visible")' in script
    assert ".image-viewer.visible" in stylesheet


def test_legacy_index_avoids_mandatory_external_assets():
    index = (Path(__file__).parents[2] / "AssetsManager" / "lan" / "static" / "index.html").read_text(
        encoding="utf-8"
    )

    assert "fonts.googleapis.com" not in index
    assert "unpkg.com" not in index


def test_legacy_pages_use_local_icon_fallback_without_cdn():
    static_dir = Path(__file__).parents[2] / "AssetsManager" / "lan" / "static"
    fallback = (static_dir / "icons.js").read_text(encoding="utf-8")

    assert "data-lucide" in fallback
    assert "lucide" in fallback
    for page in ("index.html", "detail.html", "share.html", "login.html"):
        html = (static_dir / page).read_text(encoding="utf-8")
        assert "unpkg.com" not in html
        assert "fonts.googleapis.com" not in html
        assert "/static/icons.js" in html


@pytest.mark.anyio
async def test_batch_download_rejects_over_size_limit(tmp_path):
    app, library, conn = _make_lan_app(tmp_path)
    from AssetsManager.lan.routes.downloads import MAX_BATCH_DOWNLOAD_BYTES
    # Create a file larger than the limit
    big = library / "big.bin"
    big.write_bytes(b"x" * (MAX_BATCH_DOWNLOAD_BYTES + 1))
    small = library / "small.txt"
    small.write_text("ok", encoding="utf-8")

    client = await _make_client(app)
    try:
        resp = await client.post(
            "/api/download/batch",
            json={"paths": ["big.bin", "small.txt"]},
            headers=_local_ui_headers(app),
        )
        assert resp.status == 413
        data = await resp.json()
        assert "Total size exceeds" in data["error"]
        assert data["total_bytes"] > MAX_BATCH_DOWNLOAD_BYTES
    finally:
        await client.close()


@pytest.mark.anyio
async def test_directory_download_rejects_over_size_limit(tmp_path, monkeypatch):
    from AssetsManager.lan.routes import downloads

    app, library, conn = _make_lan_app(tmp_path)
    folder = library / "folder"
    folder.mkdir()
    (folder / "one.txt").write_bytes(b"123456")
    (folder / "two.txt").write_bytes(b"abcdef")
    monkeypatch.setattr(downloads, "MAX_BATCH_DOWNLOAD_BYTES", 10)

    client = await _make_client(app)
    try:
        resp = await client.get("/api/download/folder", headers=_local_ui_headers(app))
        assert resp.status == 413
    finally:
        await client.close()


@pytest.mark.anyio
async def test_batch_directory_download_rejects_over_size_limit(tmp_path, monkeypatch):
    from AssetsManager.lan.routes import downloads

    app, library, conn = _make_lan_app(tmp_path)
    folder = library / "folder"
    folder.mkdir()
    (folder / "one.txt").write_bytes(b"123456")
    (folder / "two.txt").write_bytes(b"abcdef")
    monkeypatch.setattr(downloads, "MAX_BATCH_DOWNLOAD_BYTES", 10)

    client = await _make_client(app)
    try:
        resp = await client.post(
            "/api/download/batch",
            json={"paths": ["folder"]},
            headers=_local_ui_headers(app),
        )
        assert resp.status == 413
        data = await resp.json()
        assert data["total_bytes"] > downloads.MAX_BATCH_DOWNLOAD_BYTES
    finally:
        await client.close()


class TestThumbnailSecurity:
    """Security regression tests for thumbnail endpoints."""

    @pytest.mark.anyio
    async def test_thumbnail_max_size_capped_at_2048(self, tmp_path):
        app, library, conn = _make_lan_app(tmp_path)
        (library / "image.png").write_bytes(b"\x89PNG" + b"\x00" * 100)

        client = await _make_client(app)
        try:
            resp = await client.get("/api/thumbnails/image.png?size=999999999")
            assert resp.status in (200, 404)
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_thumbnail_invalid_size_falls_back_to_default(self, tmp_path):
        app, library, conn = _make_lan_app(tmp_path)
        (library / "image.png").write_bytes(b"\x89PNG" + b"\x00" * 100)

        client = await _make_client(app)
        try:
            resp = await client.get("/api/thumbnails/image.png?size=notanumber")
            assert resp.status in (200, 404)
        finally:
            await client.close()


class TestAuthTokenVerification:
    """Unit tests for verify_auth_token and middleware integration."""

    def test_verify_auth_token_valid(self):
        from AssetsManager.lan.auth import verify_auth_token
        from AssetsManager.lan.utils import generate_auth_token

        secret = "test-secret-key"
        token = generate_auth_token(secret)
        assert verify_auth_token(token, secret) is True

    def test_verify_auth_token_wrong_secret(self):
        from AssetsManager.lan.auth import verify_auth_token
        from AssetsManager.lan.utils import generate_auth_token

        token = generate_auth_token("secret-a")
        assert verify_auth_token(token, "secret-b") is False

    def test_verify_auth_token_expired(self):
        import time
        import hashlib
        from AssetsManager.lan.auth import verify_auth_token

        secret = "test-secret"
        ts = str(int(time.time()) - 90000)  # 25 hours ago
        sig = hashlib.sha256(f"{ts}:{secret}".encode()).hexdigest()[:32]
        token = f"{ts}.{sig}"
        assert verify_auth_token(token, secret) is False

    def test_verify_auth_token_malformed(self):
        from AssetsManager.lan.auth import verify_auth_token

        assert verify_auth_token("not-a-token", "secret") is False
        assert verify_auth_token("", "secret") is False

    @pytest.mark.anyio
    async def test_middleware_accepts_local_ui_token(self, tmp_path):
        """Verify that a token generated by get_auth_token() passes the real middleware."""
        from AssetsManager.lan.server import _LanServerImpl
        from AssetsManager.lan.utils import get_auth_headers

        library = tmp_path / "library"
        library.mkdir()
        (library / "file.txt").write_text("hello", encoding="utf-8")

        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS file_tags (file_path TEXT, tag TEXT);
                CREATE TABLE IF NOT EXISTS file_meta (file_path TEXT PRIMARY KEY, notes TEXT, urls TEXT,
                    cached_size INTEGER, cached_mtime REAL, cached_file_count INTEGER);
                CREATE TABLE IF NOT EXISTS library_stats (library_path TEXT PRIMARY KEY, total_size INTEGER);
            """)
            conn.commit()

            server = _LanServerImpl(
                library_root=str(library),
                thumbnail_dir=str(tmp_path / "thumbs"),
                db_conn=conn,
                password=None,
                access_key=None,
            )

            from aiohttp.test_utils import TestClient, TestServer
            srv = TestServer(server._app)
            client = TestClient(srv)
            await client.start_server()
            try:
                headers = get_auth_headers(server.token_secret)
                resp = await client.get("/api/files", headers=headers)
                assert resp.status == 200
            finally:
                await client.close()
        finally:
            conn.close()


class TestP0ShareCookieAuthentication:
    @pytest.mark.anyio
    async def test_tunnel_status_requires_auth_when_server_auth_is_enabled(self, tmp_path):
        from aiohttp.test_utils import TestClient, TestServer
        from AssetsManager.core import database
        from AssetsManager.lan.auth import hash_password, init_users_table
        from AssetsManager.lan.server import _LanServerImpl

        library = tmp_path / "library"
        library.mkdir()
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript(database._SCHEMA)
            init_users_table(conn)
            server = _LanServerImpl(
                library_root=str(library), thumbnail_dir=str(tmp_path / "thumbs"),
                db_conn=conn, password=hash_password("Test@1234"),
            )
            client = TestClient(TestServer(server._app))
            await client.start_server()
            try:
                response = await client.get("/api/tunnel/status")
                assert response.status == 401
            finally:
                await client.close()
        finally:
            conn.close()

    @pytest.mark.anyio
    async def test_static_backup_artifacts_are_not_served(self, tmp_path):
        from aiohttp.test_utils import TestClient, TestServer
        from AssetsManager.core import database
        from AssetsManager.lan.auth import init_users_table
        from AssetsManager.lan.server import _LanServerImpl

        library = tmp_path / "library"
        library.mkdir()
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript(database._SCHEMA)
            init_users_table(conn)
            server = _LanServerImpl(
                library_root=str(library), thumbnail_dir=str(tmp_path / "thumbs"), db_conn=conn,
            )
            client = TestClient(TestServer(server._app))
            await client.start_server()
            try:
                for path in ("/static/index.html.bak", "/static/style.css.bak2"):
                    response = await client.get(path)
                    assert response.status == 404, path
            finally:
                await client.close()
        finally:
            conn.close()

    def test_legacy_static_viewer_uses_local_icons_and_mobile_info_access(self):
        static_dir = Path(__file__).parents[2] / "AssetsManager" / "lan" / "static"
        index = (static_dir / "index.html").read_text(encoding="utf-8")
        app_js = (static_dir / "app.js").read_text(encoding="utf-8")
        i18n = (static_dir / "i18n.js").read_text(encoding="utf-8")

        assert "/static/icons.js" in index
        assert 'id="mobileInfoBtn"' in index
        assert 'aria-label="Open information panel"' in index
        assert 'mobileInfoBtn.addEventListener("click", toggleInfoPanel)' in app_js
        assert "document.documentElement.lang = this._lang" in i18n
        assert "location.reload()" not in i18n
        assert "await this.load(lang)" in i18n

    @pytest.mark.anyio
    async def test_static_route_blocks_path_escape(self, tmp_path):
        from aiohttp.test_utils import TestClient, TestServer
        from AssetsManager.core import database
        from AssetsManager.lan.auth import init_users_table
        from AssetsManager.lan.server import _LanServerImpl

        library = tmp_path / "library"
        library.mkdir()
        (tmp_path / "private.txt").write_text("private", encoding="utf-8")
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript(database._SCHEMA)
            init_users_table(conn)
            server = _LanServerImpl(
                library_root=str(library), thumbnail_dir=str(tmp_path / "thumbs"), db_conn=conn,
            )
            client = TestClient(TestServer(server._app))
            await client.start_server()
            try:
                response = await client.get("/static/%2e%2e/private.txt")
                assert response.status == 404
            finally:
                await client.close()
        finally:
            conn.close()

    @pytest.mark.anyio
    async def test_public_asset_prefixes_are_segment_bounded_when_server_auth_is_enabled(self, tmp_path):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
        from AssetsManager.core import database
        from AssetsManager.lan.auth import hash_password, init_users_table
        from AssetsManager.lan.routes._helpers import AUTH_SERVICE_APP_KEY
        from AssetsManager.lan.server import _LanServerImpl

        library = tmp_path / "library"
        library.mkdir()
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript(database._SCHEMA)
            init_users_table(conn)
            server = _LanServerImpl(
                library_root=str(library), thumbnail_dir=str(tmp_path / "thumbs"),
                db_conn=conn, password=hash_password("Test@1234"),
            )
            server._app[AUTH_SERVICE_APP_KEY] = server._auth_service
            async def handle_asset(_request):
                return web.Response(text="app")

            async def handle_assets_admin(_request):
                return web.Response(text="admin")

            server._app.router.add_get("/assets/app.js", handle_asset)
            server._app.router.add_get("/assets-admin", handle_assets_admin)
            client = TestClient(TestServer(server._app))
            await client.start_server()
            try:
                response = await client.get("/assets/app.js")
                assert response.status == 200
                assert await response.text() == "app"

                static = await client.get("/static/foo")
                assert static.status != 401

                protected = await client.get("/assets-admin")
                assert protected.status == 401

                share_page = await client.get("/s/share-id")
                assert share_page.status == 200

                share_lookalike = await client.get("/sneak")
                assert share_lookalike.status == 401
            finally:
                await client.close()
        finally:
            conn.close()

    @pytest.mark.anyio
    async def test_password_share_cookie_is_scoped_and_share_bound(self, tmp_path):
        app, library, conn = _make_lan_app(tmp_path)
        (library / "image.png").write_bytes(b"\x89PNG")

        client = await _make_client(app)
        try:
            create = await client.post(
                "/api/shares",
                json={"paths": ["image.png"], "password": "secret123", "allow_preview": True},
                headers=_local_ui_headers(app),
            )
            assert create.status == 200
            share_id = (await create.json())["id"]

            absent = await client.get(f"/api/shares/{share_id}/preview/image.png")
            assert absent.status == 401

            verify = await client.post(f"/api/shares/{share_id}/verify", json={"password": "secret123"})
            assert verify.status == 200
            cookie = verify.cookies["share_token"]
            assert cookie["httponly"]
            assert cookie["samesite"] == "Lax"
            assert cookie["path"] == f"/api/shares/{share_id}"
            token = cookie.value

            info = await client.get(f"/api/shares/{share_id}/info", headers={"Cookie": f"share_token={token}"})
            assert info.status == 200
            assert (await info.json())["paths"] == ["image.png"]
            preview = await client.get(f"/api/shares/{share_id}/preview/image.png", headers={"Cookie": f"share_token={token}"})
            assert preview.status == 200
            download = await client.get(f"/api/shares/{share_id}/download/image.png", headers={"Cookie": f"share_token={token}"})
            assert download.status == 200

            other_create = await client.post(
                "/api/shares",
                json={"paths": ["image.png"], "password": "secret123", "allow_preview": True},
                headers=_local_ui_headers(app),
            )
            assert other_create.status == 200
            other_id = (await other_create.json())["id"]
            mismatched = await client.get(
                f"/api/shares/{other_id}/preview/image.png",
                headers={"Cookie": f"share_token={token}"},
            )
            assert mismatched.status == 401
        finally:
            await client.close()

    @pytest.mark.anyio
    @pytest.mark.parametrize("password", [None, "secret123"])
    async def test_successful_share_verify_returns_share_and_http_only_cookie(self, tmp_path, password):
        app, library, conn = _make_lan_app(tmp_path)
        (library / "file.txt").write_text("content", encoding="utf-8")

        client = await _make_client(app)
        try:
            payload = {"paths": ["file.txt"], "allow_preview": True}
            if password is not None:
                payload["password"] = password
            create = await client.post("/api/shares", json=payload, headers=_local_ui_headers(app))
            assert create.status == 200
            share_id = (await create.json())["id"]

            verify = await client.post(
                f"/api/shares/{share_id}/verify", json={"password": password or ""}
            )
            assert verify.status == 200
            data = await verify.json()
            assert "token" not in data
            assert data["share"]["id"] == share_id
            assert verify.cookies["share_token"]["httponly"]
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_non_browser_share_verify_preserves_bearer_api_flow(self, tmp_path):
        app, library, conn = _make_lan_app(tmp_path)
        (library / "file.txt").write_text("content", encoding="utf-8")

        client = await _make_client(app)
        try:
            create = await client.post(
                "/api/shares",
                json={"paths": ["file.txt"], "password": "secret123"},
                headers=_local_ui_headers(app),
            )
            assert create.status == 200
            share_id = (await create.json())["id"]

            verify = await client.post(
                f"/api/shares/{share_id}/verify",
                json={"password": "secret123"},
                headers={"X-AssetsManager-API-Client": "1"},
            )
            assert verify.status == 200
            data = await verify.json()
            assert data["token"]
            assert "share_token" not in verify.cookies

            download = await client.get(
                f"/api/shares/{share_id}/download/file.txt",
                headers={"Authorization": f"Bearer {data['token']}"},
            )
            assert download.status == 200
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_password_share_download_requires_matching_share_cookie(self, tmp_path):
        app, library, conn = _make_lan_app(tmp_path)
        (library / "file.txt").write_text("protected", encoding="utf-8")

        client = await _make_client(app)
        try:
            create = await client.post(
                "/api/shares",
                json={"paths": ["file.txt"], "password": "secret123", "allow_preview": True},
                headers=_local_ui_headers(app),
            )
            assert create.status == 200
            share_id = (await create.json())["id"]

            absent = await client.get(f"/api/shares/{share_id}/download/file.txt")
            assert absent.status == 401

            other_create = await client.post(
                "/api/shares",
                json={"paths": ["file.txt"], "password": "secret123", "allow_preview": True},
                headers=_local_ui_headers(app),
            )
            assert other_create.status == 200
            other_id = (await other_create.json())["id"]
            verify_other = await client.post(
                f"/api/shares/{other_id}/verify", json={"password": "secret123"}
            )
            assert verify_other.status == 200
            other_token = verify_other.cookies["share_token"].value

            mismatched = await client.get(
                f"/api/shares/{share_id}/download/file.txt",
                headers={"Cookie": f"share_token={other_token}"},
            )
            assert mismatched.status == 401
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_expired_password_share_rejects_verify_download_and_preview(self, tmp_path):
        import time

        app, library, conn = _make_lan_app(tmp_path)
        (library / "image.png").write_bytes(b"\x89PNG")

        client = await _make_client(app)
        try:
            create = await client.post(
                "/api/shares",
                json={"paths": ["image.png"], "password": "secret123", "allow_preview": True},
                headers=_local_ui_headers(app),
            )
            assert create.status == 200
            share_id = (await create.json())["id"]

            verified = await client.post(
                f"/api/shares/{share_id}/verify", json={"password": "secret123"}
            )
            assert verified.status == 200
            token = verified.cookies["share_token"].value
            conn.execute("UPDATE share_links SET expires_at=? WHERE id=?", (time.time() - 1, share_id))
            conn.commit()

            verify = await client.post(
                f"/api/shares/{share_id}/verify", json={"password": "secret123"}
            )
            assert verify.status == 410

            download = await client.get(
                f"/api/shares/{share_id}/download/image.png",
                headers={"Cookie": f"share_token={token}"},
            )
            assert download.status == 410

            preview = await client.get(f"/api/shares/{share_id}/preview/image.png")
            assert preview.status == 410
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_middleware_rejects_invalid_token_when_password_set(self, tmp_path):
        """When password auth is enabled, invalid tokens get 401."""
        from AssetsManager.lan.server import _LanServerImpl

        library = tmp_path / "library"
        library.mkdir()

        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS file_tags (file_path TEXT, tag TEXT);
                CREATE TABLE IF NOT EXISTS file_meta (file_path TEXT PRIMARY KEY, notes TEXT, urls TEXT,
                    cached_size INTEGER, cached_mtime REAL, cached_file_count INTEGER);
                CREATE TABLE IF NOT EXISTS library_stats (library_path TEXT PRIMARY KEY, total_size INTEGER);
            """)
            conn.commit()

            from AssetsManager.lan.auth import hash_password
            server = _LanServerImpl(
                library_root=str(library),
                thumbnail_dir=str(tmp_path / "thumbs"),
                db_conn=conn,
                password=hash_password("mypassword"),
                access_key=None,
            )

            from aiohttp.test_utils import TestClient, TestServer
            srv = TestServer(server._app)
            client = TestClient(srv)
            await client.start_server()
            try:
                resp = await client.get("/api/files")
                assert resp.status == 401

                resp2 = await client.get("/api/files", headers={"Authorization": "Bearer bad.token.here"})
                assert resp2.status == 401
            finally:
                await client.close()
        finally:
            conn.close()

    @pytest.mark.anyio
    async def test_middleware_accepts_access_key_via_query_param(self, tmp_path):
        """Verify that access key works via ?key= query parameter."""
        from AssetsManager.lan.server import _LanServerImpl

        library = tmp_path / "library"
        library.mkdir()
        (library / "file.txt").write_text("hello", encoding="utf-8")

        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS file_tags (file_path TEXT, tag TEXT);
                CREATE TABLE IF NOT EXISTS file_meta (file_path TEXT PRIMARY KEY, notes TEXT, urls TEXT,
                    cached_size INTEGER, cached_mtime REAL, cached_file_count INTEGER);
                CREATE TABLE IF NOT EXISTS library_stats (library_path TEXT PRIMARY KEY, total_size INTEGER);
            """)
            conn.commit()

            raw_key = "my-access-key"
            server = _LanServerImpl(
                library_root=str(library),
                thumbnail_dir=str(tmp_path / "thumbs"),
                db_conn=conn,
                access_key=raw_key,
            )

            from aiohttp.test_utils import TestClient, TestServer
            srv = TestServer(server._app)
            client = TestClient(srv)
            await client.start_server()
            try:
                # ?key= should work
                resp = await client.get(f"/api/files?key={raw_key}")
                assert resp.status == 200

                # ?token= should also work
                resp2 = await client.get(f"/api/files?token={raw_key}")
                assert resp2.status == 200

                # wrong key should fail
                resp3 = await client.get("/api/files?key=wrong-key")
                assert resp3.status == 401
            finally:
                await client.close()
        finally:
            conn.close()

    @pytest.mark.anyio
    async def test_middleware_accepts_plaintext_password(self, tmp_path):
        """Verify that plaintext password from old settings still works."""
        from AssetsManager.lan.server import _LanServerImpl
        from AssetsManager.lan.auth import generate_token

        library = tmp_path / "library"
        library.mkdir()

        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS file_tags (file_path TEXT, tag TEXT);
                CREATE TABLE IF NOT EXISTS file_meta (file_path TEXT PRIMARY KEY, notes TEXT, urls TEXT,
                    cached_size INTEGER, cached_mtime REAL, cached_file_count INTEGER);
                CREATE TABLE IF NOT EXISTS library_stats (library_path TEXT PRIMARY KEY, total_size INTEGER);
            """)
            conn.commit()

            # Pass plaintext password (simulating old settings)
            plaintext_pw = "myplainpassword"
            server = _LanServerImpl(
                library_root=str(library),
                thumbnail_dir=str(tmp_path / "thumbs"),
                db_conn=conn,
                password=plaintext_pw,
            )

            from aiohttp.test_utils import TestClient, TestServer
            srv = TestServer(server._app)
            client = TestClient(srv)
            await client.start_server()
            try:
                # Generate token using the server's password_hash
                assert server.password_hash is not None
                token = generate_token(server.password_hash)
                resp = await client.get("/api/files", headers={"Authorization": f"Bearer {token}"})
                assert resp.status == 200
            finally:
                await client.close()
        finally:
            conn.close()


class TestPasswordHashDetection:
    """Unit tests for is_password_hash."""

    def test_is_password_hash_valid(self):
        from AssetsManager.lan.auth import is_password_hash, hash_password
        h = hash_password("test")
        assert is_password_hash(h) is True

    def test_is_password_hash_plaintext(self):
        from AssetsManager.lan.auth import is_password_hash
        assert is_password_hash("mypassword") is False
        assert is_password_hash("") is False
        assert is_password_hash("short:short") is False

    def test_is_password_hash_wrong_format(self):
        from AssetsManager.lan.auth import is_password_hash
        assert is_password_hash("not_a_hash") is False
        assert is_password_hash("abc:123") is False


class TestSearchEndpoint:

    @pytest.mark.anyio
    async def test_search_returns_empty_for_no_query(self, tmp_path):
        app, library, conn = _make_lan_app(tmp_path)
        client = await _make_client(app)
        try:
            resp = await client.get("/api/search")
            assert resp.status == 200
            data = await resp.json()
            assert data["results"] == []
            assert data["count"] == 0
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_search_by_tags_returns_matching_files(self, tmp_path):
        app, library, conn = _make_lan_app(tmp_path)
        target = library / "hero.png"
        target.write_bytes(b"\x89PNG")
        conn.execute(
            "INSERT INTO file_tags(file_path, tag) VALUES (?, ?)",
            (str(target.resolve()), "hero"),
        )
        conn.commit()
        client = await _make_client(app)
        try:
            resp = await client.get("/api/search?tags=hero")
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] >= 1
            names = [r["name"] for r in data["results"]]
            assert "hero.png" in names
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_search_returns_empty_for_no_match(self, tmp_path):
        app, library, conn = _make_lan_app(tmp_path)
        client = await _make_client(app)
        try:
            resp = await client.get("/api/search?q=nonexistent")
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 0
        finally:
            await client.close()


class TestProjectsEndpoint:

    @pytest.mark.anyio
    async def test_projects_returns_listing(self, tmp_path):
        app, library, conn = _make_lan_app(tmp_path)
        (library / "file.txt").write_text("content")
        client = await _make_client(app)
        try:
            resp = await client.get("/api/projects")
            assert resp.status == 200
            data = await resp.json()
            assert "current_path" in data or "projects" in data
        finally:
            await client.close()


class TestInfoEndpoint:

    @pytest.mark.anyio
    async def test_info_returns_server_info(self, tmp_path):
        app, library, conn = _make_lan_app(tmp_path)
        client = await _make_client(app)
        try:
            resp = await client.get("/api/info")
            assert resp.status == 200
            data = await resp.json()
            assert "library_root" in data or "share_name" in data
        finally:
            await client.close()


class TestUserCacheInvalidation:

    def test_toggle_user_invalidates_active_users_cache(self, tmp_path):
        from AssetsManager.core import database
        from AssetsManager.lan.auth import init_users_table
        from AssetsManager.lan.server import _LanServerImpl

        library = tmp_path / "library"
        library.mkdir()
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript(database._SCHEMA)
            init_users_table(conn)
            conn.execute(
                "INSERT INTO users (username, password, role, is_active) VALUES ('target', 'x', 'viewer', 1)"
            )
            conn.commit()

            server = _LanServerImpl(
                library_root=str(library),
                thumbnail_dir=str(tmp_path / "thumbs"),
                db_conn=conn,
                access_key="k",
            )

            assert server._has_active_users() is True
            server._has_users_cache = True
            server._has_users_cache_time = 9999999999

            server.invalidate_user_cache()
            assert server._has_users_cache is None
            assert server._has_active_users() is True

            conn.execute("UPDATE users SET is_active=0 WHERE id=1")
            conn.commit()
            server.invalidate_user_cache()
            assert server._has_active_users() is False
        finally:
            conn.close()

    @pytest.mark.anyio
    async def test_toggle_route_clears_server_cache_via_http(self, tmp_path):
        """POST /api/users/{id}/toggle must invalidate the active-user cache."""
        from aiohttp.test_utils import TestClient, TestServer
        from AssetsManager.core import database
        from AssetsManager.lan.auth import hash_password
        from AssetsManager.lan.auth import init_users_table
        from AssetsManager.lan.server import _LanServerImpl

        library = tmp_path / "library"
        library.mkdir()
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript(database._SCHEMA)
            init_users_table(conn)
            conn.execute(
                "INSERT INTO users (username, password, role, is_active) VALUES (?, ?, 'viewer', 1)",
                ("target", hash_password("Target@1234")),
            )
            conn.commit()

            server = _LanServerImpl(
                library_root=str(library),
                thumbnail_dir=str(tmp_path / "thumbs"),
                db_conn=conn,
                access_key="admin-key",
            )

            client = TestClient(TestServer(server._app))
            await client.start_server()
            try:
                assert server._has_active_users() is True
                server._has_users_cache = True
                server._has_users_cache_time = 9999999999

                resp = await client.post(
                    "/api/users/1/toggle?key=admin-key",
                    json={"active": False},
                )
                assert resp.status == 200
                assert (await resp.json())["ok"] is True

                assert server._has_users_cache is None
                assert server._has_active_users() is False

                row = conn.execute("SELECT is_active FROM users WHERE id=1").fetchone()
                assert row[0] == 0
            finally:
                await client.close()
        finally:
            conn.close()
