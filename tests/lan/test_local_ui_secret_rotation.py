"""Auth-config rotation on a live server must evict local_ui WebSockets.

The ``local_ui_auth_secret`` is derived from the authentication config
(password/access_key/auth_mode), so changing that config rotates the secret.
The local_ui WebSocket authorizer captures the secret once at admission, so
an established socket would otherwise keep authenticating with the
pre-rotation credential until it disconnects.  These tests pin the rotation
boundary: applying an auth-config change through ``reload_settings`` evicts
every local_ui-authority socket via ``WebSocketManager.revoke_authority``.
"""
import asyncio
import sqlite3

import pytest
from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer

from AssetsManager.core import database
from AssetsManager.lan.auth import verify_key, verify_password
from AssetsManager.lan.runtime_validation import _derive_local_ui_auth_secret
from AssetsManager.lan.utils import generate_auth_token
from tests.lan.support.api_helpers import _init_lan_schemas, _legacy_server

AUTH_CONFIG = {"access_key": "key-a", "password": "password-a", "auth_mode": "key"}


def _rotation_server(tmp_path, **auth_overrides):
    """Build a real _LanServerImpl fixture with the baseline auth config."""
    library = tmp_path / "library"
    library.mkdir()
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    try:
        conn.executescript(database._SCHEMA)
        conn.commit()
        _init_lan_schemas(conn)
        server = _legacy_server(
            library_root=str(library),
            thumbnail_dir=str(tmp_path / "thumbs"),
            db_conn=conn,
            **(AUTH_CONFIG | auth_overrides),
        )
    except BaseException:
        conn.close()
        raise
    return server, conn


def _bearer(secret):
    return {"Authorization": f"Bearer {generate_auth_token(secret)}"}


async def _wait_for_clients(server, count, timeout=2.0):
    """Wait until the manager registers ``count`` sockets.

    The ``runtime_ready`` greeting is sent before ws_manager admission
    completes, so the tests must not treat it as an admission barrier.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while len(server.ws_manager._clients) != count:
        if loop.time() > deadline:
            pytest.fail(f"expected {count} admitted sockets, saw {len(server.ws_manager._clients)}")
        await asyncio.sleep(0.01)


@pytest.mark.anyio
async def test_auth_config_rotation_evicts_established_local_ui_websocket(
        tmp_path):
    server, conn = _rotation_server(tmp_path)
    loop = asyncio.get_running_loop()
    # Simulate the live-server loop handle: reload_settings runs on the
    # caller's thread and bridges WebSocket work onto this loop through
    # run_coroutine_threadsafe (the same injection pattern used by the
    # server-lifecycle tests).
    server._loop = loop
    server._running = True
    client = TestClient(TestServer(server._app))
    await client.start_server()
    try:
        old_secret = server.local_ui_auth_secret
        ws = await client.ws_connect("/ws", headers=_bearer(old_secret))
        ready = await asyncio.wait_for(ws.receive_json(), timeout=2)
        assert ready["type"] == "runtime_ready"
        await _wait_for_clients(server, 1)

        server.reload_settings({"password": "password-b"})

        # The established socket is evicted with the revocation close code.
        message = await asyncio.wait_for(ws.receive(), timeout=2)
        assert message.type is WSMsgType.CLOSE
        assert message.data == 1008
        assert not server.ws_manager._clients

        # The rotation published a new secret: the old credential is stale,
        # a token signed with the rotated secret connects again.
        assert server.local_ui_auth_secret != old_secret
        new_ws = await client.ws_connect(
            "/ws", headers=_bearer(server.local_ui_auth_secret),
        )
        ready = await asyncio.wait_for(new_ws.receive_json(), timeout=2)
        assert ready["type"] == "runtime_ready"
        await _wait_for_clients(server, 1)
        await new_ws.close()
    finally:
        await client.close()
        conn.close()


@pytest.mark.anyio
async def test_reload_without_secret_change_keeps_local_ui_websocket(tmp_path):
    server, conn = _rotation_server(tmp_path)
    loop = asyncio.get_running_loop()
    server._loop = loop
    server._running = True
    client = TestClient(TestServer(server._app))
    await client.start_server()
    try:
        ws = await client.ws_connect(
            "/ws", headers=_bearer(server.local_ui_auth_secret),
        )
        ready = await asyncio.wait_for(ws.receive_json(), timeout=2)
        assert ready["type"] == "runtime_ready"
        await _wait_for_clients(server, 1)

        # Cosmetic keys apply hot; an auth key that derives the same secret
        # (unchanged value) must not evict anything.
        server.reload_settings({"share_name": "renamed"})
        server.reload_settings({"password": AUTH_CONFIG["password"]})

        await asyncio.sleep(0.1)
        assert server.share_name == "renamed"
        assert len(server.ws_manager._clients) == 1
        await ws.close()
    finally:
        await client.close()
        conn.close()


def test_auth_config_rotation_updates_secret_cache_and_hashes(tmp_path):
    server, conn = _rotation_server(tmp_path)
    try:
        baseline = server.local_ui_auth_secret
        # Cached: repeated reads of an unchanged config stay stable.
        assert server.local_ui_auth_secret == server.token_secret == baseline

        server.reload_settings({"access_key": "key-b", "password": "password-b"})

        rotated = server.local_ui_auth_secret
        assert rotated != baseline
        assert rotated == _derive_local_ui_auth_secret(
            server.runtime_token_secret,
            password="password-b",
            access_key="key-b",
            auth_mode=AUTH_CONFIG["auth_mode"],
        )
        # The HTTP credential chain follows the rotated config.
        assert verify_key("key-b", server.access_key_hash)
        assert verify_password("password-b", server.password_hash)
        assert not verify_password("password-a", server.password_hash)
    finally:
        conn.close()
