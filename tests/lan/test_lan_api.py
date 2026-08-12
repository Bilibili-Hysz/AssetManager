"""Unit tests for LAN API security and basic functionality."""
import asyncio
from contextlib import nullcontext
import json
import os
import sqlite3
from types import SimpleNamespace
import threading
from pathlib import Path

import pytest
from unittest.mock import Mock

from AssetsManager.lan.principal import principal_for_request
from AssetsManager.lan.routes._helpers import PRINCIPAL_REQUEST_KEY


def set_request_auth_context(request, kind, user=None):
    request[PRINCIPAL_REQUEST_KEY] = principal_for_request(
        kind, user=user if kind == "user" else None
    )


def test_task4_principal_serialization_matrix_and_permissions(monkeypatch):

    class Settings:
        def get(self, key, default=None):
            return {"lan_guest_list": False, "lan_guest_download": True, "lan_guest_preview": False}.get(key, default)

    user = {"id": 7, "username": "alice", "role": "user", "is_active": 1, "created_at": 12.5,
            "password_hash": "must-not-leak"}
    for kind in ("guest", "password", "access_key", "local_ui", "user", "share"):
        principal = principal_for_request(kind, user=user if kind == "user" else None, settings=Settings())
        payload = principal.to_dict()
        assert set(payload["capabilities"]) == {"browse", "preview", "download", "upload", "manage_links", "manage_users", "settings", "realtime"}
        assert all(isinstance(value, bool) for value in payload["capabilities"].values())
        serialized_keys = str(set(payload) | set(payload.get("user_profile", {}))).lower()
        assert not any(secret in serialized_keys for secret in ("token", "password_hash", "access_key"))
        assert ("user_profile" in payload) is (kind == "user")
    guest = principal_for_request("guest", settings=Settings())
    assert guest.capabilities.browse is False
    assert guest.capabilities.download is True
    assert guest.capabilities.preview is False
    assert guest.capabilities.realtime is False
    assert principal_for_request("user", user=user).user_profile["username"] == "alice"


def test_task4_canonical_principal_wins_over_legacy_context():
    from aiohttp.test_utils import make_mocked_request
    from AssetsManager.lan.principal import principal_for_request
    from AssetsManager.lan.routes._helpers import require_permission, require_role

    request = make_mocked_request("GET", "/")
    set_request_auth_context(request, "guest", {"username": "legacy", "role": "admin"})
    request[PRINCIPAL_REQUEST_KEY] = principal_for_request("guest", settings={"lan_guest_list": False})
    assert require_permission(request, "browse") is False
    assert require_role(request, "admin") is None


@pytest.mark.anyio
async def test_task4_auth_me_exposes_unified_principal_for_all_kinds():
    import json

    from aiohttp.test_utils import make_mocked_request

    from AssetsManager.lan.routes.auth import handle_me

    user = {
        "id": 7,
        "username": "alice",
        "role": "user",
        "is_active": 1,
        "created_at": 12.5,
        "password_hash": "must-not-leak",
    }
    for kind in ("guest", "password", "access_key", "local_ui", "user", "share"):
        request = make_mocked_request("GET", "/api/auth/me")
        set_request_auth_context(request, kind, user if kind == "user" else {})

        response = await handle_me(request)
        assert response.status == 200
        payload = json.loads(response.body)
        assert set(payload["principal"]) == {
            "kind", "authenticated", "role", "display_name", "capabilities",
        } | ({"user_profile"} if kind == "user" else set())
        assert set(payload) == {"principal", "user"} if kind == "user" else {"principal"}
        def keys(value):
            if isinstance(value, dict):
                yield from value.keys()
                for child in value.values():
                    yield from keys(child)
            elif isinstance(value, list):
                for child in value:
                    yield from keys(child)

        assert not {str(key).lower() for key in keys(payload)} & {
            "password", "password_hash", "access_key", "token", "secret",
        }


@pytest.mark.anyio
async def test_task4_auth_me_accepts_minimal_user_token_record():
    import json

    from aiohttp.test_utils import make_mocked_request

    from AssetsManager.lan.routes.auth import handle_me

    request = make_mocked_request("GET", "/api/auth/me")
    set_request_auth_context(request, "user", {"id": 7, "username": "alice", "role": "user"})

    response = await handle_me(request)
    assert response.status == 200
    payload = json.loads(response.body)
    assert payload["user"] == {
        "id": 7,
        "username": "alice",
        "role": "user",
        "active": True,
        "created_at": 0.0,
    }


def test_task4_info_public_bypass_preserves_authenticated_principal():
    from AssetsManager.lan.server import _LanServerImpl

    assert "/api/info" not in _LanServerImpl._PUBLIC_PATHS


@pytest.mark.anyio
async def test_task4_auth_me_without_auth_context_remains_unauthorized():
    from aiohttp.test_utils import make_mocked_request

    from AssetsManager.lan.routes.auth import handle_me

    response = await handle_me(make_mocked_request("GET", "/api/auth/me"))
    assert response.status == 401


@pytest.mark.anyio
async def test_task4_share_verify_sets_share_principal_before_response(tmp_path):
    from unittest.mock import AsyncMock

    from aiohttp.test_utils import make_mocked_request

    from AssetsManager.lan.routes._helpers import PRINCIPAL_REQUEST_KEY
    from AssetsManager.lan.routes.shares import handle_verify_share_password

    class Share:
        id = "share-id"
        has_password = False

        def is_expired(self):
            return False

        def to_public_dict(self):
            return {"id": self.id, "has_password": False}

    class ShareService:
        def get_share_record(self, share_id):
            assert share_id == "share-id"
            return Share()

        def generate_token(self, share_id):
            return "share-secret"

    import AssetsManager.lan.routes.shares as shares_routes

    request = make_mocked_request("POST", "/api/shares/share-id/verify")
    request.json = AsyncMock(return_value={})
    request.match_info["id"] = "share-id"
    set_request_auth_context(request, "guest", {})
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(shares_routes, "get_share_service", lambda _request: ShareService())

    try:
        response = await handle_verify_share_password(request)
        assert response.status == 200
        assert request[PRINCIPAL_REQUEST_KEY].kind == "share"
        assert request[PRINCIPAL_REQUEST_KEY].authenticated is True
    finally:
        monkeypatch.undo()



@pytest.mark.anyio
async def test_websocket_heartbeat_checks_clients_concurrently_and_isolates_errors():
    from AssetsManager.lan.ws import WebSocketManager

    manager = WebSocketManager()
    started = asyncio.Event()
    release = asyncio.Event()
    active = 0
    peak_active = 0

    class _Client:
        def __init__(self, fails=False):
            self.fails = fails

        async def ping(self, payload):
            nonlocal active, peak_active
            active += 1
            peak_active = max(peak_active, active)
            started.set()
            await release.wait()
            active -= 1
            if self.fails:
                raise RuntimeError("dead client")
            manager.acknowledge_pong(self, payload)

        async def close(self, **_kwargs):
            pass

    clients = {_Client(), _Client(fails=True), _Client()}
    manager._clients = clients
    cycle = asyncio.create_task(manager._heartbeat_cycle())
    await started.wait()
    assert peak_active == len(clients)
    release.set()
    await cycle
    assert manager._clients == {client for client in clients if not client.fails}


@pytest.mark.anyio
async def test_websocket_heartbeat_removes_and_closes_client_without_pong(monkeypatch):
    from AssetsManager.lan import ws as ws_module

    class _Client:
        async def ping(self, _payload):
            pass

        async def close(self, **_kwargs):
            self.closed = True

    monkeypatch.setattr(ws_module, "HEARTBEAT_PING_TIMEOUT", 0.01)
    client = _Client()
    client.closed = False
    manager = ws_module.WebSocketManager()
    manager._clients = {client}

    await manager._heartbeat_cycle()

    assert client not in manager._clients
    assert client.closed


@pytest.mark.anyio
async def test_websocket_heartbeat_does_not_close_client_removed_while_ping_pending():
    from AssetsManager.lan import ws as ws_module

    ping_started = asyncio.Event()
    release_ping = asyncio.Event()

    class _Client:
        def __init__(self):
            self.close_count = 0

        async def ping(self, _payload):
            ping_started.set()
            await release_ping.wait()
            raise RuntimeError("disconnected")

        async def close(self, **_kwargs):
            self.close_count += 1

    client = _Client()
    manager = ws_module.WebSocketManager()
    manager._clients = {client}
    cycle = asyncio.create_task(manager._heartbeat_cycle())
    await ping_started.wait()

    await manager.remove(client)
    await client.close()
    release_ping.set()
    await cycle

    assert client.close_count == 1
    assert client not in manager._pong_waiters


@pytest.mark.anyio
async def test_websocket_heartbeat_unrelated_pong_does_not_satisfy_waiter(monkeypatch):
    from AssetsManager.lan import ws as ws_module

    class _Client:
        async def ping(self, payload=None):
            self.payload = payload

        async def close(self, **_kwargs):
            pass

    monkeypatch.setattr(ws_module, "HEARTBEAT_PING_TIMEOUT", 0.01)
    client = _Client()
    manager = ws_module.WebSocketManager()
    manager._clients = {client}
    cycle = asyncio.create_task(manager._heartbeat_cycle())
    while not hasattr(client, "payload"):
        await asyncio.sleep(0)
    manager.acknowledge_pong(client, b"unrelated")

    await cycle

    assert client not in manager._clients
    assert client not in manager._pong_waiters


@pytest.mark.anyio
async def test_websocket_heartbeat_matching_pong_keeps_client_and_cleans_waiter():
    from AssetsManager.lan import ws as ws_module

    class _Client:
        async def ping(self, payload=None):
            assert isinstance(payload, bytes)
            manager.acknowledge_pong(self, payload)

        async def close(self, **_kwargs):
            self.closed = True

    client = _Client()
    client.closed = False
    manager = ws_module.WebSocketManager()
    manager._clients = {client}

    await manager._heartbeat_cycle()

    assert client in manager._clients
    assert client not in manager._pong_waiters
    assert not client.closed


@pytest.mark.anyio
async def test_websocket_heartbeat_waiters_are_cleaned_after_ping_failure():
    from AssetsManager.lan import ws as ws_module

    class _Client:
        async def ping(self, _payload):
            raise RuntimeError("write failed")

        async def close(self, **_kwargs):
            pass

    client = _Client()
    manager = ws_module.WebSocketManager()
    manager._clients = {client}

    await manager._heartbeat_cycle()

    assert client not in manager._pong_waiters


@pytest.mark.anyio
async def test_websocket_heartbeat_cycle_is_bounded_with_slow_clients(monkeypatch):
    from AssetsManager.lan import ws as ws_module

    class _Client:
        async def ping(self, _payload):
            await asyncio.sleep(0.05)

        async def close(self, **_kwargs):
            pass

    monkeypatch.setattr(ws_module, "HEARTBEAT_PING_TIMEOUT", 0.01)
    manager = ws_module.WebSocketManager()
    clients = {_Client(), _Client(), _Client()}
    manager._clients = clients

    await asyncio.wait_for(manager._heartbeat_cycle(), timeout=0.1)

    assert manager._clients == set()


@pytest.mark.anyio
async def test_websocket_broadcast_failure_evicts_only_dead_peer_and_updates_lifecycle():
    from AssetsManager.lan.ws import WebSocketManager

    changes = []
    lifecycle = []

    class Client:
        def __init__(self, fails=False):
            self.fails = fails
            self.closed = False
            self.messages = []

        async def send_str(self, message):
            if self.fails:
                raise ConnectionResetError("broadcast peer disconnected")
            self.messages.append(message)

        async def close(self, **_kwargs):
            self.closed = True
            lifecycle.append((self, "close"))

    manager = WebSocketManager(on_connection_change=lambda count: changes.append(count))
    dead = Client(fails=True)
    healthy = Client()
    def presence():
        lifecycle.append((dead, "presence"))
    assert await manager.add(dead, on_remove=presence) is True
    assert await manager.add(healthy) is True
    manager._pong_waiters[dead] = (b"pending", asyncio.Event())

    await manager.broadcast("asset_changed", {"path": "hero.png"})
    await manager._evict(dead)

    assert dead.closed
    assert dead not in manager._clients
    assert dead not in manager._pong_waiters
    assert healthy in manager._clients
    assert healthy.messages == ['{"type": "asset_changed", "path": "hero.png"}']
    assert lifecycle.count((dead, "presence")) == 1
    assert lifecycle.count((dead, "close")) == 1
    assert changes == [1, 2, 1]


@pytest.mark.anyio
async def test_websocket_broadcast_times_out_slow_peer_and_delivers_to_healthy_peer(monkeypatch):
    from AssetsManager.lan import ws as ws_module

    monkeypatch.setattr(ws_module, "WS_OPERATION_TIMEOUT", 0.01)
    changes = []

    class Client:
        def __init__(self, slow=False):
            self.slow = slow
            self.messages = []
            self.closed = False

        async def send_str(self, message):
            if self.slow:
                await asyncio.sleep(1)
            else:
                self.messages.append(message)

        async def close(self, **_kwargs):
            self.closed = True

    slow = Client(slow=True)
    healthy = Client()
    manager = ws_module.WebSocketManager(on_connection_change=changes.append)
    assert await manager.add(slow) is True
    assert await manager.add(healthy) is True

    await asyncio.wait_for(manager.broadcast("asset_changed", {"path": "hero.png"}), timeout=0.1)

    assert healthy.messages == ['{"type": "asset_changed", "path": "hero.png"}']
    assert slow.closed
    assert slow not in manager._clients
    assert healthy in manager._clients
    assert changes == [1, 2, 1]


@pytest.mark.anyio
async def test_websocket_admission_callback_failure_rolls_back_registration_and_presence():
    from AssetsManager.lan.ws import WebSocketManager

    changes = []
    cleanup = []

    class Client:
        def __init__(self):
            self.closed = False

        async def close(self, **_kwargs):
            self.closed = True

    client = Client()

    def on_admission():
        raise RuntimeError("presence publication failed")

    def on_remove():
        cleanup.append("removed")

    manager = WebSocketManager(on_connection_change=changes.append)
    with pytest.raises(RuntimeError, match="presence publication failed"):
        await manager.add(client, on_admission=on_admission, on_remove=on_remove)

    assert client not in manager._clients
    assert client not in manager._leases
    assert client not in manager._on_remove
    assert cleanup == ["removed"]
    assert changes == [0]


@pytest.mark.anyio
async def test_websocket_admission_callback_can_reenter_manager_without_deadlock():
    from AssetsManager.lan.ws import WebSocketManager

    lifecycle = []

    class Client:
        async def close(self, **_kwargs):
            lifecycle.append("close")

    manager = WebSocketManager()
    client = Client()

    async def on_admission():
        lifecycle.append("admission")
        assert await manager.remove(client) is True

    async def on_remove():
        lifecycle.append("remove")

    assert await asyncio.wait_for(
        manager.add(client, on_admission=on_admission, on_remove=on_remove),
        timeout=0.2,
    ) is True
    assert lifecycle == ["admission", "remove"]
    assert client not in manager._clients


@pytest.mark.anyio
async def test_websocket_remove_callback_can_reenter_manager_without_deadlock():
    from AssetsManager.lan.ws import WebSocketManager

    lifecycle = []

    class Client:
        async def close(self, **_kwargs):
            pass

    manager = WebSocketManager()
    client = Client()

    async def on_remove():
        lifecycle.append("remove")
        await manager.start_accepting()

    assert await manager.add(client, on_remove=on_remove) is True
    assert await asyncio.wait_for(manager.remove(client), timeout=0.2) is True
    assert lifecycle == ["remove"]


@pytest.mark.anyio
async def test_websocket_reentrant_authorize_callback_does_not_hold_authority_lock():
    from AssetsManager.lan.ws import WebSocketManager

    class Client:
        async def close(self, **_kwargs):
            pass

    manager = WebSocketManager()
    client = Client()

    async def authorize():
        assert await manager.revoke_authority("user-1", lambda: False) is False
        return True

    assert await asyncio.wait_for(
        manager.add(client, authorize=authorize, authority="user-1"),
        timeout=0.2,
    ) is True
    assert client in manager._clients


@pytest.mark.anyio
async def test_websocket_reentrant_revoke_callback_does_not_hold_authority_lock():
    from AssetsManager.lan.ws import WebSocketManager

    class Client:
        async def close(self, **_kwargs):
            pass

    manager = WebSocketManager()
    client = Client()
    assert await manager.add(client, authority="user-1") is True

    async def revoke():
        assert await manager.remove(client) is True
        return True

    assert await asyncio.wait_for(
        manager.revoke_authority("user-1", revoke),
        timeout=0.2,
    ) is True
    assert client not in manager._clients


@pytest.mark.anyio
async def test_websocket_revoke_transition_blocks_same_authority_admission_and_broadcast():
    from AssetsManager.lan.ws import WebSocketManager

    revoke_started = asyncio.Event()
    release_revoke = asyncio.Event()

    class Client:
        def __init__(self):
            self.messages = []

        async def send_str(self, message):
            self.messages.append(message)

        async def close(self, **_kwargs):
            pass

    manager = WebSocketManager()
    existing = Client()
    admitted = Client()
    authority = "user-1"
    assert await manager.add(existing, authority=authority) is True

    async def revoke():
        revoke_started.set()
        await release_revoke.wait()
        return True

    revoke_task = asyncio.create_task(manager.revoke_authority(authority, revoke))
    await revoke_started.wait()

    admission_task = asyncio.create_task(manager.add(admitted, authority=authority))
    broadcast_task = asyncio.create_task(manager.broadcast("asset_changed"))
    await asyncio.sleep(0)

    assert not admission_task.done()
    assert not broadcast_task.done()
    assert existing.messages == []
    assert admitted.messages == []

    release_revoke.set()
    assert await revoke_task is True
    assert await admission_task is True
    await broadcast_task

    assert existing not in manager._clients
    assert admitted in manager._clients
    assert existing.messages == []
    assert admitted.messages == []

    await manager.broadcast("asset_changed")
    assert admitted.messages == ['{"type": "asset_changed"}']


@pytest.mark.anyio
async def test_websocket_cancelled_revoke_restores_same_authority_admission_and_broadcast():
    from AssetsManager.lan.ws import WebSocketManager

    revoke_started = asyncio.Event()
    suspend_revoke = asyncio.Event()

    class Client:
        def __init__(self):
            self.messages = []

        async def send_str(self, message):
            self.messages.append(message)

        async def close(self, **_kwargs):
            pass

    manager = WebSocketManager()
    existing = Client()
    admitted = Client()
    authority = "user-1"
    assert await manager.add(existing, authority=authority) is True

    async def revoke():
        revoke_started.set()
        await suspend_revoke.wait()
        return True

    revoke_task = asyncio.create_task(manager.revoke_authority(authority, revoke))
    await revoke_started.wait()
    revoke_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await revoke_task

    assert manager._authority_transitions[authority].state == "ready"
    assert await asyncio.wait_for(
        manager.add(admitted, authority=authority),
        timeout=0.2,
    ) is True
    await asyncio.wait_for(manager.broadcast("asset_changed"), timeout=0.2)

    assert existing.messages == ['{"type": "asset_changed"}']
    assert admitted.messages == ['{"type": "asset_changed"}']


@pytest.mark.anyio
async def test_websocket_close_all_isolates_removal_callback_failures():
    from AssetsManager.lan.ws import WebSocketManager

    changes = []
    removed = []

    class Client:
        def __init__(self, name):
            self.name = name
            self.closed = False

        async def close(self, **_kwargs):
            self.closed = True

    def failing_remove():
        removed.append("failing")
        raise RuntimeError("cleanup failed")

    def healthy_remove():
        removed.append("healthy")

    failing = Client("failing")
    healthy = Client("healthy")
    manager = WebSocketManager(on_connection_change=changes.append)
    assert await manager.add(failing, on_remove=failing_remove) is True
    assert await manager.add(healthy, on_remove=healthy_remove) is True

    await manager.close_all()

    assert failing.closed and healthy.closed
    assert manager._clients == set()
    assert manager._leases == {}
    assert set(removed) == {"failing", "healthy"}
    assert changes == [1, 2, 0]


@pytest.mark.anyio
async def test_websocket_close_all_contains_cancelled_removal_callback_and_finishes_cleanup():
    from AssetsManager.lan.ws import WebSocketManager

    lifecycle = []

    class Client:
        def __init__(self, name):
            self.name = name
            self.closed = False

        async def close(self, **_kwargs):
            self.closed = True
            lifecycle.append(f"close:{self.name}")

    def cancelled_remove():
        lifecycle.append("remove:cancelled")
        raise asyncio.CancelledError

    def healthy_remove():
        lifecycle.append("remove:healthy")

    manager = WebSocketManager(
        on_connection_change=lambda count: lifecycle.append(f"count:{count}"),
    )
    cancelled = Client("cancelled")
    healthy = Client("healthy")
    assert await manager.add(cancelled, on_remove=cancelled_remove) is True
    assert await manager.add(healthy, on_remove=healthy_remove) is True

    await asyncio.wait_for(manager.close_all(), timeout=0.2)

    assert cancelled.closed and healthy.closed
    assert manager._clients == set()
    assert manager._leases == {}
    assert {"remove:cancelled", "remove:healthy"}.issubset(lifecycle)
    assert lifecycle.count("count:0") == 1

    marker = asyncio.Event()

    async def after_close():
        marker.set()

    await asyncio.wait_for(manager._invoke_callback(after_close), timeout=0.2)
    assert marker.is_set()


@pytest.mark.anyio
async def test_websocket_close_all_contains_connection_callback_failure_and_closes_all():
    from AssetsManager.lan.ws import WebSocketManager

    removed = []

    class Client:
        def __init__(self):
            self.closed = False

        async def close(self, **_kwargs):
            self.closed = True

    def on_change(count):
        if count == 0:
            raise RuntimeError("status publication failed")

    clients = [Client(), Client()]
    manager = WebSocketManager(on_connection_change=on_change)
    for client in clients:
        assert await manager.add(client, on_remove=lambda: removed.append("removed"))

    await asyncio.wait_for(manager.close_all(), timeout=0.2)

    assert all(client.closed for client in clients)
    assert len(removed) == len(clients)
    assert manager._clients == set()


@pytest.mark.anyio
async def test_websocket_close_all_removal_callback_can_reenter_manager_without_deadlock():
    from AssetsManager.lan.ws import WebSocketManager

    lifecycle = []

    class Client:
        async def close(self, **_kwargs):
            lifecycle.append("close")

    manager = WebSocketManager()
    client = Client()

    async def on_remove():
        lifecycle.append("remove")
        assert await manager.remove(client) is False
        assert await manager.start_accepting() is None

    assert await manager.add(client, on_remove=on_remove) is True
    await asyncio.wait_for(manager.close_all(), timeout=0.2)

    assert lifecycle == ["remove", "close"]
    assert client not in manager._clients


@pytest.mark.anyio
async def test_websocket_heartbeat_failure_cleanup_is_idempotent_and_accounted():
    from AssetsManager.lan import ws as ws_module

    changes = []
    lifecycle = []

    class Client:
        async def ping(self, _payload):
            raise ConnectionResetError("heartbeat peer disconnected")

        async def close(self, **_kwargs):
            lifecycle.append("close")

    manager = ws_module.WebSocketManager(on_connection_change=changes.append)
    client = Client()
    await manager.add(client, on_remove=lambda: lifecycle.append("presence"))
    await manager._heartbeat_cycle()
    await manager._evict(client)

    assert client not in manager._clients
    assert client not in manager._pong_waiters
    assert lifecycle == ["presence", "close"]
    assert changes == [1, 0]

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
        self.local_ui_auth_secret = "test-secret"
        self.endpoint_protocol = "http"
        self.ssl_active = False
        self._ssl_cert = None
        self._ssl_key = None
        self._port = 8080
        self.broadcasts = []
        self.performance_recorder = None
        self.session_token = None
        from AssetsManager.lan.ws import WebSocketManager
        self.ws_manager = WebSocketManager()
        from AssetsManager.lan.scanner import DirectoryScanner
        self.scanner = DirectoryScanner(str(library_root), db_conn)
        from AssetsManager.application import (
            AssetService, MetadataService, ProjectService, SearchService,
            TagService, ThumbnailService,
        )
        from AssetsManager.application.auth_service import AuthService
        from AssetsManager.application.share_service import ShareService
        from AssetsManager.lan.routes._helpers import LanScopedServices
        provider = self.connection_for
        self._auth_service = AuthService(db_conn, self.token_secret)
        self._share_service = ShareService(db_conn, self.token_secret)
        self.services = LanScopedServices(
            auth_service=self._auth_service,
            metadata_service=MetadataService(connection_provider=provider),
            project_service=ProjectService(connection_provider=provider),
            tag_service=TagService(connection_provider=provider),
            search_service=SearchService(connection_provider=provider),
            thumbnail_service=ThumbnailService(connection_provider=provider),
            asset_service=AssetService(),
            share_service=self._share_service,
        )

    def broadcast(self, event_type, data=None):
        self.broadcasts.append((event_type, data or {}))

    def connection_for(self, library_root=None):
        if library_root is not None and Path(library_root).resolve() != self.library_root.resolve():
            raise ValueError("wrong library root")
        return self.db_conn

    def invalidate_user_cache(self):
        pass


def _init_lan_schemas(conn):
    from AssetsManager.repositories.auth_repository import AuthRepository
    from AssetsManager.repositories.share_repository import ShareRepository

    AuthRepository(conn).init_tables()
    ShareRepository(conn).init_table()
    # tag_metadata arrives via DB migration v3; fixture databases start from
    # the baseline _SCHEMA, so mirror the migrated shape for tag routes.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tag_metadata ("
        "tag TEXT PRIMARY KEY, "
        "color TEXT DEFAULT '', "
        "icon TEXT DEFAULT '', "
        "category TEXT DEFAULT '', "
        "created_at REAL DEFAULT (strftime('%s','now'))"
        ")"
    )
    conn.commit()


def _legacy_server(**kwargs):
    """Build a runtime-shaped LAN fixture for low-level route tests."""
    from types import SimpleNamespace

    from AssetsManager.application import (
        AssetService,
        AuthService,
        MetadataService,
        ProjectService,
        RuntimeSharingServices,
        SearchService,
        ShareService,
        TagService,
        ThumbnailService,
    )
    from AssetsManager.core.directory_cache import DirectoryCache
    from AssetsManager.lan.server import _LanServerImpl
    from tests.lan.support.legacy_runtime_adapter import adapt_legacy_runtime

    db_conn = kwargs["db_conn"]

    class Session:
        root = Path(kwargs["library_root"])
        thumb_dir = Path(kwargs["thumbnail_dir"])
        is_closed = False
        event_token = "runtime-test-session"

        def connection_for(self, library_root=None):
            if (
                library_root is not None
                and Path(library_root).resolve() != self.root.resolve()
            ):
                raise ValueError("wrong library")
            return db_conn

    session = Session()
    secret = "runtime-test-secret"
    auth_service = AuthService(db_conn, secret)
    share_service = ShareService(db_conn, secret)
    bundle = SimpleNamespace(
        session=session,
        sharing_services=RuntimeSharingServices(
            token_secret=secret,
            auth_service=auth_service,
            share_service=share_service,
        ),
        auth_service=auth_service,
        metadata_service=MetadataService(connection_provider=session.connection_for),
        project_service=ProjectService(connection_provider=session.connection_for),
        tag_service=TagService(connection_provider=session.connection_for),
        search_service=SearchService(connection_provider=session.connection_for),
        thumbnail_service=ThumbnailService(connection_provider=session.connection_for),
        asset_service=AssetService(directory_cache=DirectoryCache(db_conn)),
        share_service=share_service,
    )

    class EventRouter:
        def subscribe(self, _callback):
            return SimpleNamespace(close=lambda: None)

    runtime = SimpleNamespace(
        session=session,
        services=bundle,
        epoch="runtime-test-epoch",
        revision=0,
        event_router=EventRouter(),
    )
    options = dict(kwargs)
    options.pop("library_root")
    options.pop("thumbnail_dir")
    options.pop("db_conn")
    runtime = adapt_legacy_runtime(runtime)
    return _LanServerImpl(runtime=runtime, **options)


def _make_lan_app(tmp_path, *, authenticated_context_only=False, canonical_context_only=False):
    from aiohttp import web
    from AssetsManager.application.auth_service import AuthService
    from AssetsManager.core import database
    from AssetsManager.lan.api import setup_routes
    from AssetsManager.lan.auth import verify_auth_token
    from AssetsManager.lan.routes._helpers import (
        AUTH_SERVICE_APP_KEY,
        LAN_APP_KEY,
        get_auth_token,
        set_request_principal,
    )
    from AssetsManager.lan.principal import principal_for_request

    library = tmp_path / "library"
    library.mkdir()

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    try:
        conn.executescript(database._SCHEMA)
        conn.commit()
        _init_lan_schemas(conn)

        @web.middleware
        async def _test_auth_middleware(request, handler):
            if authenticated_context_only:
                user = {"username": "middleware-user", "role": "user"}
                set_request_principal(request, principal_for_request("user", user=user))
                return await handler(request)
            token = get_auth_token(request)
            if token:
                lan = request.app[LAN_APP_KEY]
                local_ui_secret = getattr(
                    lan, "local_ui_auth_secret", getattr(lan, "token_secret", None)
                )
                if local_ui_secret and verify_auth_token(token, local_ui_secret):
                    set_request_principal(request, principal_for_request("local_ui"))
                else:
                    user = request.app[AUTH_SERVICE_APP_KEY].verify_user_token(token)
                    if user:
                        set_request_principal(request, principal_for_request("user", user=user))
            if request.get(PRINCIPAL_REQUEST_KEY) is None:
                set_request_principal(request, principal_for_request("guest"))
            return await handler(request)

        app = web.Application(middlewares=[_test_auth_middleware])
        app[LAN_APP_KEY] = _FakeLan(library, conn, tmp_path / "thumbs")
        app[AUTH_SERVICE_APP_KEY] = AuthService(conn, "test-secret")
        async def _close_db(_app):
            from AssetsManager.core.database import close_all_dbs
            close_all_dbs()
            conn.close()
        app.on_cleanup.append(_close_db)
        setup_routes(app)
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


@pytest.mark.anyio
async def test_security_middleware_skips_read_only_browsing_surfaces():
    """Gallery views, thumbnail batches and the other read-only browsing
    endpoints must not consume the rate-limit window (a gallery page fires
    many thumbnail batches plus view requests and shares the loopback
    bucket with the desktop stats poller)."""
    from aiohttp import web
    from AssetsManager.lan.security import IPBlacklist, RateLimiter, create_security_middleware

    async def handler(_request):
        return web.json_response({"ok": True})

    app = web.Application(
        middlewares=[
            create_security_middleware(
                RateLimiter(max_requests=3),
                IPBlacklist(),
            )
        ]
    )
    app.router.add_get("/api/gallery/home", handler)
    app.router.add_get("/api/gallery/collection", handler)
    app.router.add_post("/api/thumbnails/batch", handler)
    app.router.add_get("/api/thumbnails/hero.png", handler)
    app.router.add_get("/api/favorites", handler)
    app.router.add_get("/api/stats", handler)
    app.router.add_get("/api/quicksearch", handler)
    app.router.add_get("/api/tree", handler)
    app.router.add_get("/api/tags", handler)
    app.router.add_get("/api/home", handler)
    app.router.add_get("/api/search", handler)
    app.router.add_get("/api/quota", handler)
    app.router.add_get("/api/activity", handler)
    app.router.add_get("/api/revision", handler)
    app.router.add_post("/api/files/summaries", handler)
    # A non-skipped endpoint still counts toward the window.
    app.router.add_get("/api/shares", handler)
    client = await _make_client(app)
    try:
        # The middleware app has no LAN runtime; plain requests suffice.
        for path in (
            "/api/gallery/home",
            "/api/gallery/collection",
            "/api/thumbnails/hero.png",
            "/api/favorites",
            "/api/stats",
            "/api/quicksearch",
            "/api/tree",
            "/api/tags",
            "/api/home",
            "/api/search",
            "/api/quota",
            "/api/activity",
            "/api/revision",
            "/api/shares",
            "/api/shares",
        ):
            assert (await client.get(path)).status == 200
        # The thumbnail batch and directory summaries are POST routes and
        # must equally skip the window.
        assert (await client.post("/api/thumbnails/batch")).status == 200
        assert (await client.post("/api/files/summaries")).status == 200
        # The window (3) was consumed only by /api/shares calls: the third
        # fits, the fourth is refused.
        assert (await client.get("/api/shares")).status == 200
        assert (await client.get("/api/shares")).status == 429
    finally:
        await client.close()


@pytest.mark.anyio
async def test_security_middleware_rate_limit_asset_prefix_is_segment_bounded():
    from aiohttp import web
    from AssetsManager.lan.security import IPBlacklist, RateLimiter, create_security_middleware

    async def handler(_request):
        return web.json_response({"ok": True})

    app = web.Application(
        middlewares=[
            create_security_middleware(
                RateLimiter(max_requests=1),
                IPBlacklist(),
            )
        ]
    )
    app.router.add_get("/assets", handler)
    app.router.add_get("/assets/app.js", handler)
    app.router.add_get("/assets-admin", handler)
    client = await _make_client(app)
    try:
        assert (await client.get("/assets")).status == 200
        assert (await client.get("/assets/app.js")).status == 200
        assert (await client.get("/assets-admin")).status == 200
        assert (await client.get("/assets-admin")).status == 429
    finally:
        await client.close()


def _local_ui_headers(app):
    from AssetsManager.lan.utils import get_auth_headers
    from AssetsManager.lan.routes._helpers import LAN_APP_KEY

    return get_auth_headers(
        getattr(
            app[LAN_APP_KEY],
            "local_ui_auth_secret",
            app[LAN_APP_KEY].token_secret,
        )
    )


async def _register_user_token(client, username="alice"):
    resp = await client.post(
        "/api/auth/register",
        json={"username": username, "password": "Test@1234"},
    )
    assert resp.status == 200
    return resp.cookies["lan_token"].value


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
        assert all(isinstance(item["is_project"], bool) for item in data["items"])
    finally:
        await client.close()


@pytest.mark.anyio
async def test_files_route_marks_projects_from_sidebar_depth_config(tmp_path):
    from AssetsManager.core.settings import AppSettings

    app, library, _conn = _make_lan_app(tmp_path)
    category = library / "category"
    (category / "project" / "nested_project").mkdir(parents=True)
    (library / "asset.txt").write_text("hello", encoding="utf-8")
    settings = AppSettings.instance()
    original = settings.get("sidebar_depth_cfg")
    settings.set("sidebar_depth_cfg", {"depth": 2, "branch_depths": {"category": 3}})
    client = await _make_client(app)
    try:
        root = await client.get("/api/files")
        nested = await client.get("/api/files?path=category")
        deeply_nested = await client.get("/api/files?path=category/project")
        assert root.status == nested.status == deeply_nested.status == 200
        root_items = {item["name"]: item for item in (await root.json())["items"]}
        nested_items = {item["name"]: item for item in (await nested.json())["items"]}
        deeply_nested_items = {item["name"]: item for item in (await deeply_nested.json())["items"]}
        assert root_items["category"]["is_project"] is False
        assert root_items["asset.txt"]["is_project"] is False
        assert nested_items["project"]["is_project"] is False
        assert deeply_nested_items["nested_project"]["is_project"] is True
    finally:
        if original is None:
            settings.set("sidebar_depth_cfg", None)
        else:
            settings.set("sidebar_depth_cfg", original)
        await client.close()


@pytest.mark.anyio
async def test_files_route_uses_scoped_metadata_service_for_cached_stats(tmp_path, monkeypatch):
    from AssetsManager.lan.routes import files

    app, library, _conn = _make_lan_app(tmp_path)
    asset = library / "visible.txt"
    asset.write_text("hello", encoding="utf-8")
    calls = []

    class _MetadataService:
        def get_cached_stats(self, root, paths):
            calls.append((root, paths))
            return {}

    monkeypatch.setattr(files, "get_metadata_service", lambda _request: _MetadataService())
    client = await _make_client(app)
    try:
        response = await client.get("/api/files")

        assert response.status == 200
        assert calls == [(library, [str(asset)])]
    finally:
        await client.close()


@pytest.mark.anyio
async def test_files_route_honors_explicit_summaries_false(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    (library / "folder").mkdir()
    client = await _make_client(app)
    try:
        response = await client.get("/api/files?summaries=false")
        assert response.status == 200
        assert (await response.json())["items"][0]["size_fmt"] == "0.0 B"
    finally:
        await client.close()


@pytest.mark.anyio
async def test_directory_summaries_route_hydrates_direct_child_directories(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    parent = library / "projects"
    child = parent / "avatar"
    child.mkdir(parents=True)
    (child / "cover.png").write_bytes(b"image")
    client = await _make_client(app)
    try:
        response = await client.post(
            "/api/files/summaries",
            json={"parent_path": "projects", "paths": ["projects/avatar"]},
        )
        assert response.status == 200
        assert (await response.json())["items"] == [{
            "path": "projects/avatar", "item_count": 1, "size_fmt": "1 items",
            "thumbnail_url": "/api/thumbnails/projects/avatar/cover.png",
        }]
    finally:
        await client.close()


@pytest.mark.anyio
async def test_directory_summaries_route_rejects_non_direct_or_invalid_paths(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    parent = library / "projects"
    (parent / "avatar" / "nested").mkdir(parents=True)
    (library / "outside").mkdir()
    (tmp_path / "outside").mkdir()
    client = await _make_client(app)
    try:
        nested = await client.post(
            "/api/files/summaries",
            json={"parent_path": "projects", "paths": ["projects/avatar/nested"]},
        )
        sibling = await client.post(
            "/api/files/summaries",
            json={"parent_path": "projects", "paths": ["outside"]},
        )
        escaped = await client.post(
            "/api/files/summaries",
            json={"parent_path": "projects", "paths": ["../outside"]},
        )
        assert nested.status == 400
        assert await nested.json() == {"error": "paths must be direct child directories"}
        assert sibling.status == 400
        assert await sibling.json() == {"error": "paths must be direct child directories"}
        assert escaped.status == 400
        assert await escaped.json() == {"error": "Invalid directory path"}
    finally:
        await client.close()


@pytest.mark.anyio
async def test_directory_summaries_route_rejects_duplicate_and_over_limit_paths(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    (library / "projects").mkdir()
    client = await _make_client(app)
    try:
        duplicate = await client.post(
            "/api/files/summaries",
            json={"parent_path": "", "paths": ["projects", "projects"]},
        )
        over_limit = await client.post(
            "/api/files/summaries",
            json={"parent_path": "", "paths": ["projects"] * 49},
        )
        assert duplicate.status == 400
        assert await duplicate.json() == {"error": "paths must be unique strings"}
        assert over_limit.status == 400
        assert await over_limit.json() == {
            "error": "parent_path and 1-48 paths are required",
        }
    finally:
        await client.close()


@pytest.mark.anyio
async def test_directory_summaries_route_preserves_validation_error_priority_and_exact_json(tmp_path):

    app, library, _conn = _make_lan_app(tmp_path)
    parent = library / "projects"
    child = parent / "child"
    parent.mkdir()
    child.mkdir()
    (child / "nested").mkdir()
    (library / "parent-file").write_text("file", encoding="utf-8")
    client = await _make_client(app)
    try:
        cases = [
            ("not-json", "Invalid JSON body"),
            ({}, "parent_path and 1-48 paths are required"),
            ({"parent_path": "missing", "paths": []}, "parent_path and 1-48 paths are required"),
            ({"parent_path": "missing", "paths": ["projects/child", []]}, "paths must be unique strings"),
            ({"parent_path": "parent-file", "paths": ["missing"]}, "Parent is not a directory"),
            ({"parent_path": "projects", "paths": ["../outside"]}, "Invalid directory path"),
            ({"parent_path": "projects", "paths": ["projects/child/nested"]}, "paths must be direct child directories"),
        ]
        for payload, expected_error in cases:
            if payload == "not-json":
                response = await client.post(
                    "/api/files/summaries",
                    data="{not-json",
                    headers={"Content-Type": "application/json"},
                )
            else:
                response = await client.post("/api/files/summaries", json=payload)
            assert response.status == 400
            assert await response.json() == {"error": expected_error}
    finally:
        await client.close()


@pytest.mark.anyio
async def test_directory_summaries_route_returns_forbidden_before_body_parsing(tmp_path, monkeypatch):
    from AssetsManager.lan.routes import files

    app, _library, _conn = _make_lan_app(tmp_path)
    monkeypatch.setattr(files, "require_permission", lambda _request, _permission: False)
    client = await _make_client(app)
    try:
        response = await client.post("/api/files/summaries", data="{not-json")
        assert response.status == 403
        assert await response.json() == {"error": "Forbidden"}
    finally:
        await client.close()


@pytest.mark.anyio
async def test_directory_summaries_route_returns_exact_json_for_unhashable_path_element(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    parent = library / "projects"
    parent.mkdir()
    client = await _make_client(app)
    try:
        response = await client.post(
            "/api/files/summaries",
            json={"parent_path": "projects", "paths": ["projects", []]},
        )
        assert response.status == 400
        assert await response.json() == {"error": "paths must be unique strings"}
    finally:
        await client.close()


@pytest.mark.anyio
async def test_directory_summaries_route_keeps_runtime_errors_as_500_and_records_performance(tmp_path, monkeypatch):
    from AssetsManager.core.performance import PerformanceRecorder
    from AssetsManager.lan.routes._helpers import LAN_APP_KEY

    app, library, _conn = _make_lan_app(tmp_path)
    parent = library / "projects"
    child = parent / "child"
    child.mkdir(parents=True)
    recorder = PerformanceRecorder(enabled=True)
    lan = app[LAN_APP_KEY]
    lan.performance_recorder = recorder

    def raise_runtime_error(*_args, **_kwargs):
        raise RuntimeError("summary failed")

    monkeypatch.setattr(lan.services.asset_service, "summarize_directories", raise_runtime_error)
    client = await _make_client(app)
    try:
        response = await client.post(
            "/api/files/summaries",
            json={"parent_path": "projects", "paths": ["projects/child"]},
        )
        assert response.status == 500
        event = next(event for event in recorder.recent() if event.name == "lan.directory_summaries")
        assert event.attributes == {
            "outcome": "error", "status": 500, "requested_count": 1, "result_count": 0,
        }
    finally:
        await client.close()


@pytest.mark.anyio
async def test_files_route_records_session_scoped_performance_event(tmp_path):
    from AssetsManager.core.performance import PerformanceRecorder
    from AssetsManager.lan.routes._helpers import LAN_APP_KEY

    app, library, _conn = _make_lan_app(tmp_path)
    (library / "visible.txt").write_text("hello", encoding="utf-8")
    recorder = PerformanceRecorder(enabled=True)
    lan = app[LAN_APP_KEY]
    assert isinstance(lan, _FakeLan)
    lan.performance_recorder = recorder
    lan.session_token = "session-a"
    client = await _make_client(app)
    try:
        response = await client.get("/api/files")
        assert response.status == 200

        event = next(event for event in recorder.recent() if event.name == "lan.files")
        assert event.elapsed_ms >= 0
        assert event.session_token == "session-a"
        assert event.path == str(library.resolve())
        assert event.attributes == {"outcome": "success", "status": 200, "item_count": 1}
    finally:
        await client.close()


@pytest.mark.anyio
async def test_files_route_records_path_validation_error(tmp_path):
    from AssetsManager.core.performance import PerformanceRecorder
    from AssetsManager.lan.routes._helpers import LAN_APP_KEY

    app, _library, _conn = _make_lan_app(tmp_path)
    recorder = PerformanceRecorder(enabled=True)
    app[LAN_APP_KEY].performance_recorder = recorder
    client = await _make_client(app)
    try:
        response = await client.get("/api/files?path=../../outside")
        assert response.status == 400

        event = next(event for event in recorder.recent() if event.name == "lan.files")
        assert event.attributes == {"outcome": "error", "status": 400, "item_count": -1}
        assert event.path is None
    finally:
        await client.close()


@pytest.mark.anyio
async def test_files_route_records_forbidden_without_request_path(tmp_path, monkeypatch):
    from AssetsManager.core.performance import PerformanceRecorder
    from AssetsManager.lan.routes._helpers import LAN_APP_KEY

    app, _library, _conn = _make_lan_app(tmp_path, authenticated_context_only=True)
    recorder = PerformanceRecorder(enabled=True)
    app[LAN_APP_KEY].performance_recorder = recorder
    from AssetsManager.lan.routes import files
    monkeypatch.setattr(files, "require_permission", lambda _request, _permission: False)
    client = await _make_client(app)
    try:
        response = await client.get("/api/files?path=private")
        assert response.status == 403

        event = next(event for event in recorder.recent() if event.name == "lan.files")
        assert event.path is None
        assert event.attributes == {"outcome": "error", "status": 403, "item_count": -1}
    finally:
        await client.close()


@pytest.mark.anyio
async def test_files_route_ignores_disabled_performance_recorder(tmp_path):
    from AssetsManager.core.performance import PerformanceRecorder
    from AssetsManager.lan.routes._helpers import LAN_APP_KEY

    app, library, _conn = _make_lan_app(tmp_path)
    (library / "visible.txt").write_text("hello", encoding="utf-8")
    recorder = PerformanceRecorder()
    lan = app[LAN_APP_KEY]
    assert isinstance(lan, _FakeLan)
    lan.performance_recorder = recorder
    client = await _make_client(app)
    try:
        response = await client.get("/api/files")
        assert response.status == 200
        assert recorder.recent() == ()
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
        assert "token" not in data
        assert "password_hash" not in data["user"]
        assert resp.cookies["lan_token"]["httponly"] is True
    finally:
        await client.close()


@pytest.mark.anyio
async def test_auth_user_login_route_returns_cookie_only_response(tmp_path):
    app, library, conn = _make_lan_app(tmp_path)

    client = await _make_client(app)
    try:
        registered = await client.post(
            "/api/auth/register",
            json={"username": "login-user", "password": "Test@1234"},
        )
        assert registered.status == 200
        client.session.cookie_jar.clear()

        response = await client.post(
            "/api/auth/login",
            json={"username": "login-user", "password": "Test@1234"},
        )

        assert response.status == 200
        data = await response.json()
        assert "token" not in data
        assert "password_hash" not in data["user"]
        assert response.cookies["lan_token"]["httponly"] is True
    finally:
        await client.close()


@pytest.mark.anyio
async def test_auth_password_login_route_returns_cookie_only_response(tmp_path):
    from AssetsManager.lan.auth import hash_password
    from AssetsManager.lan.routes._helpers import LAN_APP_KEY

    app, library, conn = _make_lan_app(tmp_path)
    app[LAN_APP_KEY].password_hash = hash_password("Test@1234")

    client = await _make_client(app)
    try:
        response = await client.post(
            "/api/auth/login",
            json={"password": "Test@1234"},
        )

        assert response.status == 200
        assert "token" not in await response.json()
        assert response.cookies["lan_token"]["httponly"] is True
    finally:
        await client.close()


@pytest.mark.anyio
async def test_auth_verify_key_route_returns_cookie_only_response(tmp_path):
    from AssetsManager.lan.auth import hash_key
    from AssetsManager.lan.routes._helpers import LAN_APP_KEY

    app, library, conn = _make_lan_app(tmp_path)
    app[LAN_APP_KEY].access_key_hash = hash_key("access-key")

    client = await _make_client(app)
    try:
        response = await client.post(
            "/api/auth/verify_key",
            json={"key": "access-key"},
        )

        assert response.status == 200
        assert "token" not in await response.json()
        assert response.cookies["lan_token"]["httponly"] is True
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
    app, library, conn = _make_lan_app(
        tmp_path, authenticated_context_only=True, canonical_context_only=True
    )

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
    async def test_tunnel_status_rejects_authenticated_non_admin(self, tmp_path):
        app, library, conn = _make_lan_app(tmp_path)

        client = await _make_client(app)
        try:
            token = await _register_user_token(client)
            response = await client.get(
                "/api/tunnel/status",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status == 403
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


@pytest.mark.anyio
async def test_metadata_route_discards_malformed_urls(tmp_path):
    app, library, conn = _make_lan_app(tmp_path)
    target = library / "asset.txt"
    target.write_text("metadata", encoding="utf-8")
    conn.execute(
        "INSERT INTO file_meta(file_path, urls) VALUES (?, ?)",
        (str(target.resolve()), '["http://[", "https://example.com/reference"]'),
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

    runtime = object()
    lan.LanServer(runtime=runtime, ip_whitelist=["127.0.0.1"])

    assert captured["runtime"] is runtime
    assert captured["ip_whitelist"] == ["127.0.0.1"]


def test_public_lan_entrypoints_do_not_expose_legacy_runtime_switch(monkeypatch):
    import AssetsManager.lan as lan
    from AssetsManager.lan.manager import ShareManager

    monkeypatch.setattr(lan, "_HAS_AIOHTTP", True)
    with pytest.raises(TypeError, match="_allow_legacy_runtime"):
        lan.LanServer(runtime=object(), _allow_legacy_runtime=True)
    with pytest.raises(TypeError, match="_allow_legacy_runtime"):
        ShareManager().start(runtime=object(), _allow_legacy_runtime=True)


def test_lan_server_requires_runtime_before_server_startup(monkeypatch):
    import AssetsManager.lan as lan
    with pytest.raises(TypeError, match="runtime"):
        lan.LanServer()


def test_lan_server_facade_separates_desktop_and_runtime_token_secrets(monkeypatch):
    import AssetsManager.lan as lan

    class _Impl:
        token_secret = "local-ui-secret"
        runtime_token_secret = "runtime-secret"
        local_ui_auth_secret = "local-ui-secret"

        def __init__(self, **_kwargs):
            pass

    monkeypatch.setattr(lan, "_HAS_AIOHTTP", True)
    monkeypatch.setattr("AssetsManager.lan.server._LanServerImpl", _Impl)

    server = lan.LanServer(runtime=object())
    assert server.token_secret == "local-ui-secret"
    assert server.local_ui_auth_secret == "local-ui-secret"
    assert server.runtime_token_secret == "runtime-secret"


def test_share_manager_requires_runtime(monkeypatch):
    from AssetsManager.lan.manager import ShareManager

    class _Lan:
        @staticmethod
        def is_available():
            return True

    import AssetsManager as package
    monkeypatch.setattr(package, "lan", _Lan)

    with pytest.raises(TypeError, match="runtime"):
        ShareManager().start()


def test_share_manager_passes_runtime_to_server(monkeypatch):
    from AssetsManager.lan.manager import ShareManager

    captured = {}
    runtime = object()

    class _Server:
        def start(self, **kwargs):
            pass

        def status(self):
            return {}

    class _Lan:
        @staticmethod
        def is_available():
            return True

        class LanServer:
            def __new__(cls, **kwargs):
                captured.update(kwargs)
                return _Server()

    import AssetsManager as package
    monkeypatch.setattr(package, "lan", _Lan)
    from AssetsManager.application.security_preflight import SecurityPreflight
    preflight = SecurityPreflight()
    preflight.confirm_trusted_lan()
    ShareManager().start(runtime=runtime, preflight=preflight)
    assert captured["runtime"] is runtime


def _make_runtime_services_for_fake_session(session, connection):
    if not callable(getattr(session, "operation", None)):
        session.operation = nullcontext

    from AssetsManager.application import (
        AssetService,
        RuntimeSharingServices,
        SearchService,
        TagService,
        ThumbnailService,
    )
    from AssetsManager.core.directory_cache import DirectoryCache

    token_secret = "runtime-test-secret"
    metadata_service = SimpleNamespace(
        _connection_provider=session.connection_for, _session=session
    )
    tag_service = TagService(
        connection_provider=session.connection_for, session=session
    )
    project_service = SimpleNamespace(
        _connection_provider=session.connection_for,
        _session=session,
        _metadata_svc=metadata_service,
        _tag_svc=tag_service,
    )
    return SimpleNamespace(
        session=session,
        sharing_services=RuntimeSharingServices(
            token_secret=token_secret,
            # These LAN injection tests validate snapshot/session wiring rather
            # than Auth/Share persistence.  Use an explicit binding projection
            # instead of pretending an unmanaged object connection is a
            # canonical DatabaseManager-owned service resource.
            auth_service=SimpleNamespace(
                _conn=connection, _secret=token_secret, _session=session
            ),
            share_service=SimpleNamespace(
                _conn=connection, _secret=token_secret, _session=session
            ),
        ),
        metadata_service=metadata_service,
        tag_service=tag_service,
        thumbnail_service=ThumbnailService(
            connection_provider=session.connection_for, session=session
        ),
        lan_services=SimpleNamespace(
            asset_service=AssetService(directory_cache=DirectoryCache(connection)),
            project_service=project_service,
            search_service=SearchService(
                connection_provider=session.connection_for, session=session
            ),
        ),
    )


def test_runtime_injection_uses_canonical_session_resources_and_services(tmp_path):
    from AssetsManager.lan.routes._helpers import LanScopedServices
    from AssetsManager.lan.server import _LanServerImpl

    session = SimpleNamespace(
        root=tmp_path / "canonical",
        thumb_dir=tmp_path / "canonical" / "thumbs",
        event_token="session-token",
        is_closed=False,
    )
    connection = object()
    session.connection_for = Mock(return_value=connection)
    services = _make_runtime_services_for_fake_session(session, connection)
    lan_services = services.lan_services
    runtime = SimpleNamespace(
        session=session,
        services_snapshot=services,
        services=services,
        register_lifecycle_adapter=Mock(),
        unregister_lifecycle_adapter=Mock(),
    )
    server = _LanServerImpl(runtime=runtime)

    assert isinstance(server.services, LanScopedServices)
    assert server.services.search_service is lan_services.search_service
    assert server.services.thumbnail_service is services.thumbnail_service
    assert server.services.auth_service is services.sharing_services.auth_service
    assert server.services.share_service is services.sharing_services.share_service
    assert server.runtime_token_secret == services.sharing_services.token_secret
    assert server.services.search_service._connection_provider is session.connection_for
    assert server.services.thumbnail_service._connection_provider is session.connection_for
    assert server.library_root == session.root
    assert server.thumbnail_dir == session.thumb_dir
    assert server.db_conn is connection
    assert server.session_token == session.event_token
    assert server.services.runtime_services is services
    session.connection_for.reset_mock()
    assert server.connection_for(session.root) is connection
    session.connection_for.assert_called_once_with(session.root)
    runtime.register_lifecycle_adapter.assert_not_called()

    server._register_runtime_adapter()
    runtime.register_lifecycle_adapter.assert_called_once_with(server)
    server.stop()
    server.stop()
    runtime.unregister_lifecycle_adapter.assert_called_once_with(server)


def test_runtime_injection_reuses_runtime_owned_sharing_bundle(tmp_path):
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.lan.server import _LanServerImpl

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)
    sharing = runtime.sharing_services
    assert sharing.auth_service._library_root == session.root_str
    assert sharing.auth_service._session_token == session.event_token
    assert sharing.share_service._library_root == session.root_str
    assert sharing.share_service._session_token == session.event_token

    first = _LanServerImpl(runtime=runtime)
    second = _LanServerImpl(runtime=runtime)

    assert first.services.auth_service is sharing.auth_service
    assert first.services.share_service is sharing.share_service
    assert first._auth_service is sharing.auth_service
    assert first._share_service is sharing.share_service
    assert first.runtime_token_secret == sharing.token_secret
    assert second.services.auth_service is sharing.auth_service
    assert second.services.share_service is sharing.share_service
    assert second.runtime_token_secret == sharing.token_secret


def test_lan_status_does_not_claim_https_before_tls_starts(tmp_path, monkeypatch):
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.lan import server as server_module

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)
    monkeypatch.setattr(server_module, "get_local_ip", lambda: "192.0.2.20")

    server = server_module._LanServerImpl(
        runtime=runtime, ssl_cert="server.crt", ssl_key="server.key"
    )

    assert server.status()["url"] == "http://192.0.2.20:8080"
    assert server.status()["ssl_active"] is False


@pytest.mark.anyio
async def test_lan_startup_publishes_tls_and_fails_closed_on_restart(
    tmp_path, monkeypatch
):
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.lan import server as server_module

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)
    server = server_module._LanServerImpl(
        runtime=runtime, ssl_cert="server.crt", ssl_key="server.key"
    )
    outcomes = iter((True, False))

    class FakeSSLContext:
        def __init__(self, _protocol):
            self.loads = next(outcomes)

        def load_cert_chain(self, _cert, _key):
            if not self.loads:
                raise OSError("bad certificate")

    class FakeRunner:
        def __init__(self, _app, **_kwargs):
            pass

        async def setup(self):
            pass

        async def cleanup(self):
            pass

    class FakeSite:
        def __init__(self, _runner, _bind, _port, *, ssl_context):
            self.ssl_context = ssl_context

        async def start(self):
            pass

        async def stop(self):
            pass

    monkeypatch.setattr(server_module.ssl, "SSLContext", FakeSSLContext)
    monkeypatch.setattr(server_module.web, "AppRunner", FakeRunner)
    monkeypatch.setattr(server_module.web, "TCPSite", FakeSite)
    monkeypatch.setattr(server._scanner, "start_background_scan", lambda: None)
    monkeypatch.setattr(server, "_register_runtime_adapter", lambda: True)

    server._cleanup_complete = True
    server._lifecycle_state = "starting"
    await server._startup()
    assert server.ssl_active is True
    assert server.endpoint_protocol == "https"

    server._running = False
    server._lifecycle_state = "starting"
    with pytest.raises(OSError, match="bad certificate"):
        await server._startup()
    assert server.ssl_active is False
    assert server.endpoint_protocol == "http"
@pytest.mark.anyio
async def test_local_ui_tokens_are_stable_for_same_auth_config_and_revoked_on_change(
    tmp_path,
):
    from aiohttp.test_utils import TestClient, TestServer

    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.lan.server import _LanServerImpl
    from AssetsManager.lan.utils import generate_auth_token

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)
    first = _LanServerImpl(
        runtime=runtime, access_key="admin-key", password="pw", auth_mode="key"
    )
    same = _LanServerImpl(
        runtime=runtime, access_key="admin-key", password="pw", auth_mode="key"
    )
    changed = _LanServerImpl(
        runtime=runtime, access_key="rotated-key", password="pw", auth_mode="key"
    )

    assert first.runtime_token_secret == runtime.sharing_services.token_secret
    assert same.runtime_token_secret == first.runtime_token_secret
    assert changed.runtime_token_secret == first.runtime_token_secret
    assert same.token_secret == first.token_secret == first.local_ui_auth_secret
    assert changed.token_secret != first.token_secret

    token = generate_auth_token(first.local_ui_auth_secret)
    same_client = TestClient(TestServer(same._app))
    changed_client = TestClient(TestServer(changed._app))
    await same_client.start_server()
    await changed_client.start_server()
    try:
        accepted = await same_client.get(
            "/api/shares", headers={"Authorization": f"Bearer {token}"}
        )
        rejected = await changed_client.get(
            "/api/shares", headers={"Authorization": f"Bearer {token}"}
        )
        assert accepted.status == 200
        assert rejected.status == 401
    finally:
        await same_client.close()
        await changed_client.close()
        bootstrap.library_service.close_session(session)


@pytest.mark.parametrize(
    "changed",
    (
        {"access_key": "other-key"},
        {"password": "other-password"},
        {"auth_mode": "password"},
    ),
)
def test_local_ui_auth_secret_is_bound_to_authentication_config(tmp_path, changed):
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.lan.server import _LanServerImpl

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)
    config = {"access_key": "key", "password": "password", "auth_mode": "key"}
    baseline = _LanServerImpl(runtime=runtime, **config)
    modified = _LanServerImpl(runtime=runtime, **(config | changed))

    assert modified.runtime_token_secret == baseline.runtime_token_secret
    assert modified.token_secret != baseline.token_secret
    assert modified.local_ui_auth_secret != baseline.local_ui_auth_secret


@pytest.mark.anyio
async def test_desktop_share_created_before_lan_is_visible_over_http(tmp_path):
    from aiohttp.test_utils import TestClient, TestServer

    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.lan.server import _LanServerImpl
    from AssetsManager.lan.utils import get_auth_headers

    library = tmp_path / "library"
    library.mkdir()
    (library / "asset.txt").write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    runtime = bootstrap.runtime_for(session)

    share = runtime.sharing_services.share_service.create_share(paths=["asset.txt"])
    assert share is not None

    server = _LanServerImpl(runtime=runtime, access_key="test-access-key")
    client = TestClient(TestServer(server._app))
    await client.start_server()
    try:
        response = await client.get(
            "/api/shares", headers=get_auth_headers(server.local_ui_auth_secret)
        )
        assert response.status == 200
        payload = await response.json()
        assert [item["id"] for item in payload["shares"]] == [share.id]
    finally:
        await client.close()
        bootstrap.library_service.close_session(session)


def test_runtime_injection_requires_operation_boundary_even_with_snapshot(tmp_path):
    from AssetsManager.lan.server import _LanServerImpl

    session = SimpleNamespace(
        root=tmp_path / "canonical",
        thumb_dir=tmp_path / "canonical" / "thumbs",
        event_token="session-token",
        is_closed=False,
    )
    connection = object()
    session.connection_for = Mock(return_value=connection)
    services = _make_runtime_services_for_fake_session(session, connection)
    del session.operation
    runtime = SimpleNamespace(session=session, services_snapshot=services)

    with pytest.raises(ValueError, match="operation boundary"):
        _LanServerImpl(runtime=runtime)


def test_runtime_injection_prefers_services_snapshot_over_legacy_services(tmp_path):
    from AssetsManager.lan.server import _LanServerImpl

    session = SimpleNamespace(
        root=tmp_path / "canonical",
        thumb_dir=tmp_path / "canonical" / "thumbs",
        event_token="session-token",
        is_closed=False,
    )
    connection = object()
    session.connection_for = Mock(return_value=connection)
    canonical = _make_runtime_services_for_fake_session(session, connection)

    class Runtime:
        def __init__(self):
            self.session = session
            self.services_snapshot = canonical
            self.register_lifecycle_adapter = Mock()
            self.unregister_lifecycle_adapter = Mock()

        @property
        def services(self):
            raise AssertionError("legacy .services must not be read")

    runtime = Runtime()

    server = _LanServerImpl(runtime=runtime)

    assert server.services.runtime_services is canonical
    assert server.services.metadata_service is canonical.metadata_service
    assert server.services.project_service is canonical.lan_services.project_service
    assert server.services.search_service is canonical.lan_services.search_service
    assert server.services.thumbnail_service is canonical.thumbnail_service
    assert server.services.auth_service is canonical.sharing_services.auth_service
    assert server.services.share_service is canonical.sharing_services.share_service


def test_legacy_adapter_binds_provider_only_search_service(tmp_path):
    from AssetsManager.lan.server import _LanServerImpl
    from tests.lan.support.legacy_runtime_adapter import adapt_legacy_runtime

    session = SimpleNamespace(
        root=tmp_path / "canonical",
        thumb_dir=tmp_path / "canonical" / "thumbs",
        event_token="session-token",
        is_closed=False,
    )
    connection = object()
    session.connection_for = Mock(return_value=connection)
    services = _make_runtime_services_for_fake_session(session, connection)
    services.lan_services.search_service._session = None
    del session.operation
    runtime = SimpleNamespace(session=session, services=services)

    assert services.lan_services.search_service._session is None
    runtime = adapt_legacy_runtime(runtime)
    server = _LanServerImpl(runtime=runtime)

    assert services.lan_services.search_service._session is session
    assert server.services.search_service is services.lan_services.search_service


def test_runtime_injection_rejects_legacy_services_by_default(tmp_path):
    from AssetsManager.lan.server import _LanServerImpl

    session = SimpleNamespace(
        root=tmp_path / "canonical",
        thumb_dir=tmp_path / "canonical" / "thumbs",
        event_token="session-token",
        is_closed=False,
    )
    connection = object()
    session.connection_for = Mock(return_value=connection)
    services = _make_runtime_services_for_fake_session(session, connection)
    services.asset_service = services.lan_services.asset_service
    services.project_service = services.lan_services.project_service
    services.search_service = services.lan_services.search_service
    runtime = SimpleNamespace(
        session=session,
        services=services,
        register_lifecycle_adapter=Mock(),
        unregister_lifecycle_adapter=Mock(),
    )

    with pytest.raises(ValueError, match="services_snapshot"):
        _LanServerImpl(runtime=runtime)


def test_legacy_adapter_upgrades_legacy_services_to_canonical_runtime(tmp_path):
    from AssetsManager.lan.server import _LanServerImpl
    from tests.lan.support.legacy_runtime_adapter import adapt_legacy_runtime

    session = SimpleNamespace(
        root=tmp_path / "canonical",
        thumb_dir=tmp_path / "canonical" / "thumbs",
        event_token="session-token",
        is_closed=False,
    )
    connection = object()
    session.connection_for = Mock(return_value=connection)
    services = _make_runtime_services_for_fake_session(session, connection)
    services.asset_service = services.lan_services.asset_service
    services.project_service = services.lan_services.project_service
    services.search_service = services.lan_services.search_service
    del session.operation
    runtime = SimpleNamespace(session=session, services=services)

    runtime = adapt_legacy_runtime(runtime)
    server = _LanServerImpl(runtime=runtime)
    assert server.services.runtime_services is services
    assert server.services.auth_service is services.sharing_services.auth_service
    assert server.services.share_service is services.sharing_services.share_service


@pytest.mark.parametrize("snapshot", [None], ids=["none"])
def test_runtime_injection_rejects_none_snapshot_without_fallback(tmp_path, snapshot):
    from AssetsManager.lan.server import _LanServerImpl

    session = SimpleNamespace(
        root=tmp_path / "canonical",
        thumb_dir=tmp_path / "canonical" / "thumbs",
        event_token="session-token",
        is_closed=False,
        connection_for=Mock(return_value=object()),
    )
    services = _make_runtime_services_for_fake_session(session, session.connection_for.return_value)
    services.asset_service = services.lan_services.asset_service
    services.project_service = services.lan_services.project_service
    services.search_service = services.lan_services.search_service
    runtime = SimpleNamespace(
        session=session,
        services_snapshot=snapshot,
        services=services,
    )

    with pytest.raises(ValueError, match="runtime"):
        _LanServerImpl(runtime=runtime)


def test_runtime_injection_propagates_snapshot_getter_error_without_fallback(tmp_path):
    from AssetsManager.lan.server import _LanServerImpl

    session = SimpleNamespace(
        root=tmp_path / "canonical",
        thumb_dir=tmp_path / "canonical" / "thumbs",
        event_token="session-token",
        is_closed=False,
        connection_for=Mock(return_value=object()),
    )
    services = _make_runtime_services_for_fake_session(session, session.connection_for.return_value)
    services.asset_service = services.lan_services.asset_service
    services.project_service = services.lan_services.project_service
    services.search_service = services.lan_services.search_service

    class Runtime:
        def __init__(self):
            self.session = session
            self.services = services

        @property
        def services_snapshot(self):
            raise AttributeError("snapshot getter failed")

    with pytest.raises(AttributeError, match="snapshot getter failed"):
        _LanServerImpl(runtime=Runtime())


@pytest.mark.parametrize(
    "service_name",
    ("metadata_service", "project_service", "tag_service", "search_service", "thumbnail_service"),
)
def test_runtime_server_failed_construction_does_not_register_lifecycle_adapter(tmp_path, service_name):
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.lan.server import _LanServerImpl

    bootstrap = ApplicationBootstrap()
    try:
        session = bootstrap.library_service.open_session(tmp_path / "library")
        runtime = bootstrap.runtime_for(session)
        baseline_adapters = list(runtime._lifecycle_adapters)
        getattr(runtime.services, service_name)._connection_provider = lambda _root: object()

        with pytest.raises(ValueError, match=f"{service_name} provider"):
            _LanServerImpl(runtime=runtime)

        assert runtime._lifecycle_adapters == baseline_adapters
    finally:
        bootstrap.library_service.close()



@pytest.mark.parametrize(
    ("binding", "message"),
    (
        ("asset_cache", "asset_service cache"),
        ("project_internal", "project_service internals"),
        ("metadata_session", "metadata_service provider"),
        ("metadata_session_none", "metadata_service provider"),
        ("search_session", "search_service provider"),
        ("search_session_none", "search_service provider"),
    ),
)
def test_runtime_server_rejects_deep_session_binding_mismatches(
    tmp_path, binding, message
):
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.lan.server import _LanServerImpl

    bootstrap = ApplicationBootstrap()
    try:
        session = bootstrap.library_service.open_session(tmp_path / "library")
        runtime = bootstrap.runtime_for(session)
        baseline_adapters = list(runtime._lifecycle_adapters)
        lan_services = runtime.services.lan_services

        if binding == "asset_cache":
            lan_services.asset_service._directory_cache._conn = object()
        elif binding == "project_internal":
            lan_services.project_service._metadata_svc._connection_provider = (
                lambda _root: object()
            )
        elif binding == "metadata_session":
            foreign_session = bootstrap.library_service.open_session(
                tmp_path / "foreign"
            )
            runtime.services.metadata_service._session = foreign_session
        elif binding == "search_session":
            foreign_session = bootstrap.library_service.open_session(
                tmp_path / "foreign"
            )
            lan_services.search_service._session = foreign_session
        elif binding == "search_session_none":
            lan_services.search_service._session = None
        else:
            runtime.services.metadata_service._session = None

        with pytest.raises(ValueError, match=message):
            _LanServerImpl(runtime=runtime)

        assert runtime._lifecycle_adapters == baseline_adapters
    finally:
        bootstrap.library_service.close()


def test_runtime_server_close_race_does_not_publish_partial_binding(
    tmp_path, monkeypatch
):
    from AssetsManager.application import ApplicationBootstrap
    import AssetsManager.lan.server as server_module

    bootstrap = ApplicationBootstrap()
    scanner_entered = threading.Event()
    release_scanner = threading.Event()
    final_publish_attempted = threading.Event()
    closing_started = threading.Event()
    close_done = threading.Event()
    servers = []
    server_errors = []
    close_errors = []

    session = bootstrap.library_service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)
    materialized_lan_services = runtime.services.lan_services
    original_publish = type(session)._publish_while_live

    def blocking_scanner(_library_root, _db_conn):
        scanner_entered.set()
        assert release_scanner.wait(5)
        return object()

    def recording_publish(current_session, publish):
        final_publish_attempted.set()
        return original_publish(current_session, publish)

    monkeypatch.setattr(server_module, "DirectoryScanner", blocking_scanner)
    monkeypatch.setattr(type(session), "_publish_while_live", recording_publish)
    bootstrap.library_service.add_session_closing_listener(
        lambda closing_session: closing_started.set()
    )

    def build_server():
        try:
            servers.append(server_module._LanServerImpl(runtime=runtime))
        except Exception as exc:
            server_errors.append(exc)

    def close_session():
        try:
            session.close()
        except Exception as exc:
            close_errors.append(exc)
        finally:
            close_done.set()

    server_thread = threading.Thread(target=build_server)
    server_thread.start()
    assert scanner_entered.wait(5)
    close_thread = threading.Thread(target=close_session)
    close_thread.start()
    assert closing_started.wait(5)
    assert not close_done.wait(0.05)

    release_scanner.set()
    server_thread.join(5)
    close_thread.join(5)

    assert not server_thread.is_alive()
    assert not close_thread.is_alive()
    assert final_publish_attempted.is_set()
    assert servers == []
    assert len(server_errors) == 1
    assert isinstance(server_errors[0], RuntimeError)
    assert close_errors == []
    assert session.is_closed
    assert materialized_lan_services is not None
    with pytest.raises(RuntimeError, match="retained LAN services"):
        _ = runtime.services.lan_services
    assert runtime._lifecycle_adapters == []

def test_runtime_server_does_not_rebind_runtime_service_providers(tmp_path):
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.lan.server import _LanServerImpl

    bootstrap = ApplicationBootstrap()
    session_a = bootstrap.library_service.open_session(tmp_path / "library-a")
    session_b = bootstrap.library_service.open_session(tmp_path / "library-b")
    runtime_a = bootstrap.runtime_for(session_a)
    runtime_b = bootstrap.runtime_for(session_b)
    provider_a = runtime_a.services.search_service._connection_provider
    thumbnail_provider_a = runtime_a.services.thumbnail_service._connection_provider

    _LanServerImpl(runtime=runtime_a)
    _LanServerImpl(runtime=runtime_b)

    assert runtime_a.services.search_service._connection_provider is provider_a
    assert runtime_a.services.thumbnail_service._connection_provider is thumbnail_provider_a
    assert provider_a.__self__ is session_a
    assert thumbnail_provider_a.__self__ is session_a
    assert runtime_b.services.search_service._connection_provider.__self__ is session_b
    assert runtime_b.services.thumbnail_service._connection_provider.__self__ is session_b


def test_lan_server_rejects_legacy_constructor_arguments(tmp_path):
    import AssetsManager.lan as lan

    session = SimpleNamespace(
        root=tmp_path / "canonical",
        thumb_dir=tmp_path / "canonical" / "thumbs",
        is_closed=False,
        connection_for=Mock(return_value=object()),
    )
    runtime = SimpleNamespace(session=session, services=SimpleNamespace(session=session))

    with pytest.raises(TypeError, match="library_root"):
        lan.LanServer(runtime=runtime, library_root=str(tmp_path / "other"))


def test_lan_service_bundle_is_explicitly_attached_by_fixture():
    app = SimpleNamespace()
    app.services = object()
    assert app.services is not None


def test_lan_service_lookup_requires_eager_runtime_bundle():
    from aiohttp.test_utils import make_mocked_request
    from AssetsManager.lan.routes._helpers import LAN_APP_KEY, get_services

    bundle = object()
    request = make_mocked_request("GET", "/", app={LAN_APP_KEY: SimpleNamespace(services=bundle)})
    assert get_services(request) is bundle

    missing = make_mocked_request("GET", "/", app={LAN_APP_KEY: SimpleNamespace()})
    with pytest.raises(RuntimeError, match="LAN service bundle"):
        get_services(missing)


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
async def test_download_route_serves_filename_with_literal_percent_sequence(tmp_path):
    """A literal %xx sequence in a real filename must survive a single decode.

    aiohttp decodes match_info once (%%2F -> %2F); the old double unquote
    would turn the literal ``%2F`` into ``/`` and serve the wrong file.
    """
    app, library, conn = _make_lan_app(tmp_path)
    (library / "a%2Fb.txt").write_text("literal percent", encoding="utf-8")
    (library / "a").mkdir(exist_ok=True)
    (library / "a" / "b.txt").write_text("wrong file", encoding="utf-8")

    client = await _make_client(app)
    try:
        # Single-encoded %252F -> match_info gets "%2F" (the literal name).
        resp = await client.get("/api/download/a%252Fb.txt", headers=_local_ui_headers(app))
        assert resp.status == 200
        assert await _read_body(resp) == b"literal percent"
    finally:
        await client.close()


@pytest.mark.anyio
async def test_download_route_serves_filename_with_literal_percent_sign(tmp_path):
    """A literal ``%`` followed by non-hex characters is also preserved."""
    app, library, conn = _make_lan_app(tmp_path)
    (library / "100%25.txt").write_text("percent file", encoding="utf-8")

    client = await _make_client(app)
    try:
        resp = await client.get("/api/download/100%2525.txt", headers=_local_ui_headers(app))
        assert resp.status == 200
        assert await _read_body(resp) == b"percent file"
    finally:
        await client.close()


@pytest.mark.anyio
async def test_download_routes_record_response_ready_metrics(tmp_path):
    from AssetsManager.core.performance import PerformanceRecorder
    from AssetsManager.lan.routes._helpers import LAN_APP_KEY

    app, library, _conn = _make_lan_app(tmp_path)
    (library / "asset.txt").write_text("download me", encoding="utf-8")
    recorder = PerformanceRecorder(enabled=True)
    app[LAN_APP_KEY].performance_recorder = recorder
    app[LAN_APP_KEY].session_token = "session-a"
    client = await _make_client(app)
    try:
        single = await client.get("/api/download/asset.txt", headers=_local_ui_headers(app))
        assert single.status == 200
        await _read_body(single)

        single_event = next(event for event in recorder.recent() if event.name == "lan.download")
        assert single_event.session_token == "session-a"
        assert single_event.path == str((library / "asset.txt").resolve())
        assert single_event.attributes == {
            "outcome": "response_ready",
            "status": 200,
            "phase": "response_ready",
            "kind": "file",
        }

        recorder.clear()
        batch = await client.post(
            "/api/download/batch",
            json={"paths": ["asset.txt"]},
            headers=_local_ui_headers(app),
        )
        assert batch.status == 200
        await _read_body(batch)

        batch_event = next(event for event in recorder.recent() if event.name == "lan.download_batch")
        assert batch_event.path is None
        assert batch_event.attributes == {
            "outcome": "response_ready",
            "status": 200,
            "phase": "response_ready",
            "target_count": 1,
        }
    finally:
        await client.close()


@pytest.mark.anyio
async def test_download_routes_record_response_ready_without_delivery_claims(tmp_path):
    from AssetsManager.core.performance import PerformanceRecorder
    from AssetsManager.lan.routes._helpers import LAN_APP_KEY

    app, library, _conn = _make_lan_app(tmp_path)
    (library / "asset.txt").write_text("download me", encoding="utf-8")
    recorder = PerformanceRecorder(enabled=True)
    app[LAN_APP_KEY].performance_recorder = recorder
    app[LAN_APP_KEY].session_token = "session-a"
    client = await _make_client(app)
    try:
        direct = await client.get("/api/download/asset.txt", headers=_local_ui_headers(app))
        assert direct.status == 200
        direct_event = next(event for event in recorder.recent() if event.name == "lan.download")
        assert direct_event.session_token == "session-a"
        assert direct_event.path == str((library / "asset.txt").resolve())
        assert direct_event.attributes == {
            "outcome": "response_ready", "status": 200, "phase": "response_ready", "kind": "file"
        }
        assert not {"bytes_delivered", "completed", "delivery_success"} & set(direct_event.attributes)

        recorder.clear()
        batch = await client.post(
            "/api/download/batch", json={"paths": ["asset.txt"]}, headers=_local_ui_headers(app)
        )
        assert batch.status == 200
        batch_event = next(event for event in recorder.recent() if event.name == "lan.download_batch")
        assert batch_event.path is None
        assert batch_event.attributes == {
            "outcome": "response_ready", "status": 200, "phase": "response_ready", "target_count": 1
        }
    finally:
        await client.close()


@pytest.mark.anyio
async def test_download_route_failure_is_pathless_and_recorder_safe(tmp_path, monkeypatch):
    from AssetsManager.core.performance import PerformanceRecorder
    from AssetsManager.lan.routes._helpers import LAN_APP_KEY

    app, library, _conn = _make_lan_app(tmp_path)
    (library / "asset.txt").write_text("download me", encoding="utf-8")
    recorder = PerformanceRecorder(enabled=True)
    app[LAN_APP_KEY].performance_recorder = recorder
    client = await _make_client(app)
    try:
        escaped = await client.get("/api/download/..%2Fprivate.txt", headers=_local_ui_headers(app))
        assert escaped.status == 400
        escaped_event = next(event for event in recorder.recent() if event.name == "lan.download")
        assert escaped_event.path is None
        assert escaped_event.attributes == {
            "outcome": "error", "status": 400, "phase": "failed", "kind": "none"
        }

        monkeypatch.setattr(recorder, "record", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError()))
        response = await client.get("/api/download/asset.txt", headers=_local_ui_headers(app))
        assert response.status == 200
        assert await _read_body(response) == b"download me"
    finally:
        await client.close()


@pytest.mark.anyio
async def test_directory_download_zip_failure_records_pathless_error(tmp_path, monkeypatch):
    from AssetsManager.core.performance import PerformanceRecorder
    from AssetsManager.lan.routes import downloads
    from AssetsManager.lan.routes._helpers import LAN_APP_KEY

    app, library, _conn = _make_lan_app(tmp_path)
    folder = library / "folder"
    folder.mkdir()
    (folder / "asset.txt").write_text("download me", encoding="utf-8")
    recorder = PerformanceRecorder(enabled=True)
    app[LAN_APP_KEY].performance_recorder = recorder

    async def fail_zip(*_args, **_kwargs):
        return None

    monkeypatch.setattr(downloads, "build_zip_async", fail_zip)
    client = await _make_client(app)
    try:
        response = await client.get("/api/download/folder", headers=_local_ui_headers(app))
        assert response.status == 500
        event = next(event for event in recorder.recent() if event.name == "lan.download")
        assert event.path is None
        assert event.attributes == {
            "outcome": "error", "status": 500, "phase": "failed", "kind": "none"
        }
    finally:
        await client.close()


@pytest.mark.anyio
@pytest.mark.parametrize("batch", [False, True])
async def test_directory_download_size_estimation_does_not_block_event_loop(tmp_path, monkeypatch, batch):
    from AssetsManager.lan.routes import downloads

    app, library, _conn = _make_lan_app(tmp_path)
    folder = library / "folder"
    folder.mkdir()
    (folder / "asset.txt").write_text("download me", encoding="utf-8")
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = threading.Event()

    def block_size(_target):
        loop.call_soon_threadsafe(started.set)
        assert release.wait(timeout=2)
        return 0

    monkeypatch.setattr(downloads, "_estimate_download_size", block_size)
    client = await _make_client(app)
    try:
        if batch:
            download_task = asyncio.create_task(
                client.post("/api/download/batch", json={"paths": ["folder"]}, headers=_local_ui_headers(app))
            )
        else:
            download_task = asyncio.create_task(client.get("/api/download/folder", headers=_local_ui_headers(app)))
        await asyncio.wait_for(started.wait(), timeout=1)

        status = await asyncio.wait_for(client.get("/api/tunnel/status", headers=_local_ui_headers(app)), timeout=0.5)
        assert status.status == 200
        release.set()
        response = await asyncio.wait_for(download_task, timeout=3)
        assert response.status == 200
    finally:
        release.set()
        await client.close()


@pytest.mark.anyio
async def test_file_only_batch_download_does_not_offload_size_estimation(tmp_path, monkeypatch):
    from AssetsManager.lan.routes import downloads

    app, library, _conn = _make_lan_app(tmp_path)
    (library / "asset.txt").write_text("download me", encoding="utf-8")

    async def fail_offload(*_args, **_kwargs):
        raise AssertionError("file-only batch must not use a worker")

    monkeypatch.setattr(downloads.asyncio, "to_thread", fail_offload)
    client = await _make_client(app)
    try:
        response = await client.post(
            "/api/download/batch", json={"paths": ["asset.txt"]}, headers=_local_ui_headers(app)
        )
        assert response.status == 200
    finally:
        await client.close()


@pytest.mark.anyio
async def test_batch_download_recorder_failure_does_not_change_archive_response(tmp_path, monkeypatch):
    from AssetsManager.core.performance import PerformanceRecorder
    from AssetsManager.lan.routes._helpers import LAN_APP_KEY

    app, library, _conn = _make_lan_app(tmp_path)
    (library / "asset.txt").write_text("download me", encoding="utf-8")
    recorder = PerformanceRecorder(enabled=True)
    app[LAN_APP_KEY].performance_recorder = recorder
    monkeypatch.setattr(recorder, "record", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError()))
    client = await _make_client(app)
    try:
        response = await client.post(
            "/api/download/batch", json={"paths": ["asset.txt"]}, headers=_local_ui_headers(app)
        )
        assert response.status == 200
        assert response.headers["Content-Type"].startswith("application/zip")
    finally:
        await client.close()


@pytest.mark.anyio
async def test_anonymous_quota_cookie_session_keeps_one_bucket_per_browser(tmp_path, monkeypatch):
    from AssetsManager.lan.routes import quota
    from AssetsManager.repositories.free_download_quota_repository import FreeDownloadQuotaRepository

    app, library, conn = _make_lan_app(tmp_path)
    (library / "asset.txt").write_text("download me", encoding="utf-8")
    FreeDownloadQuotaRepository(conn).init_tables()
    monkeypatch.setattr(
        quota.AppSettings,
        "instance",
        lambda: SimpleNamespace(get=lambda key, default=None: {
            "lan_quota_enabled": True,
            "lan_quota_period": "daily",
            "lan_quota_limit": 2,
            "lan_quota_min_interval_seconds": 0,
            "lan_guest_list": True,
            "lan_guest_download": True,
            "lan_guest_preview": True,
        }.get(key, default)),
    )

    client = await _make_client(app)
    try:
        # First anonymous request: no cookie yet -> Set-Cookie is issued.
        first = await client.get("/api/quota")
        assert first.status == 200
        set_cookie = first.headers.getall("Set-Cookie", [])
        assert any(value.startswith(f"{quota._QUOTA_ID_COOKIE}=") for value in set_cookie)
        assert any("HttpOnly" in value and "SameSite=Lax" in value for value in set_cookie)
        assert quota._QUOTA_ID_COOKIE in first.cookies

        # The TestClient cookie jar replays the cookie: no reissue, same bucket.
        second = await client.get("/api/quota")
        assert second.status == 200
        assert not any(
            value.startswith(f"{quota._QUOTA_ID_COOKIE}=")
            for value in second.headers.getall("Set-Cookie", [])
        )
        assert quota._QUOTA_ID_COOKIE not in second.cookies

        downloaded = await client.get("/api/download/asset.txt")
        assert downloaded.status == 200
        await _read_body(downloaded)
        status_body = json.loads(await (await client.get("/api/quota")).text())
        assert status_body["used"] == 1

        # Two more downloads exhaust the same browser's bucket; the third 429s.
        assert (await client.get("/api/download/asset.txt")).status == 200
        denied = await client.get("/api/download/asset.txt")
        assert denied.status == 429
        assert denied.headers["X-Quota-Remaining"] == "0"
    finally:
        await client.close()


@pytest.mark.anyio
async def test_anonymous_quota_buckets_are_isolated_per_browser(tmp_path, monkeypatch):
    from AssetsManager.lan.routes import quota
    from AssetsManager.repositories.free_download_quota_repository import FreeDownloadQuotaRepository

    app, library, conn = _make_lan_app(tmp_path)
    (library / "asset.txt").write_text("download me", encoding="utf-8")
    FreeDownloadQuotaRepository(conn).init_tables()
    monkeypatch.setattr(
        quota.AppSettings,
        "instance",
        lambda: SimpleNamespace(get=lambda key, default=None: {
            "lan_quota_enabled": True,
            "lan_quota_period": "daily",
            "lan_quota_limit": 1,
            "lan_quota_min_interval_seconds": 0,
            "lan_guest_list": True,
            "lan_guest_download": True,
            "lan_guest_preview": True,
        }.get(key, default)),
    )

    client_a = await _make_client(app)
    client_b = await _make_client(app)
    try:
        # Both anonymous browsers can download once (limit 1 each).
        first_a = await client_a.get("/api/download/asset.txt")
        assert first_a.status == 200
        await _read_body(first_a)
        first_b = await client_b.get("/api/download/asset.txt")
        assert first_b.status == 200
        await _read_body(first_b)

        # Client A exhausts its own bucket while B still has quota left.
        denied_a = await client_a.get("/api/download/asset.txt")
        assert denied_a.status == 429
        second_b = await client_b.get("/api/download/asset.txt")
        assert second_b.status == 429
        used_a = json.loads(await (await client_a.get("/api/quota")).text())["used"]
        assert used_a == 1
    finally:
        await client_a.close()
        await client_b.close()


@pytest.mark.anyio
async def test_authenticated_quota_request_gets_no_anonymous_cookie(tmp_path, monkeypatch):
    from AssetsManager.lan.routes import quota
    from AssetsManager.repositories.free_download_quota_repository import FreeDownloadQuotaRepository

    app, library, conn = _make_lan_app(tmp_path)
    FreeDownloadQuotaRepository(conn).init_tables()
    monkeypatch.setattr(
        quota.AppSettings,
        "instance",
        lambda: SimpleNamespace(get=lambda key, default=None: {
            "lan_quota_enabled": True,
            "lan_quota_period": "daily",
            "lan_quota_limit": 2,
            "lan_quota_min_interval_seconds": 0,
        }.get(key, default)),
    )

    client = await _make_client(app)
    try:
        response = await client.get("/api/quota", headers=_local_ui_headers(app))
        assert response.status == 200
        assert not any(
            value.startswith(f"{quota._QUOTA_ID_COOKIE}=")
            for value in response.headers.getall("Set-Cookie", [])
        )
        assert quota._QUOTA_ID_COOKIE not in response.cookies
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
async def test_tag_routes_translate_service_validation_to_bad_request(tmp_path):
    app, library, conn = _make_lan_app(tmp_path)
    target = library / "asset.txt"
    target.write_text("tag me", encoding="utf-8")
    headers = _local_ui_headers(app)

    client = await _make_client(app)
    try:
        for invalid_tag in ("", "   ", "x" * 201, None, 42):
            response = await client.post(
                "/api/tags",
                json={"tag": invalid_tag, "file_path": "asset.txt"},
                headers=headers,
            )
            assert response.status == 400
            assert await response.json() == {"error": "Invalid tag name"}

        for invalid_request in (
            {"tag": "   "},
            {"tag": "   ", "file_path": "../outside.txt"},
        ):
            response = await client.post(
                "/api/tags",
                json=invalid_request,
                headers=headers,
            )
            assert response.status == 400
            assert await response.json() == {"error": "Invalid tag name"}

        created = await client.post(
            "/api/tags",
            json={"tag": "  hero  ", "file_path": "asset.txt"},
            headers=headers,
        )
        assert created.status == 200
        assert conn.execute(
            "SELECT tag FROM file_tags WHERE file_path=?", (str(target.resolve()),)
        ).fetchone() == ("hero",)

        accepted_tag = "a" * 200
        accepted = await client.post(
            "/api/tags",
            json={"tag": accepted_tag, "file_path": "asset.txt"},
            headers=headers,
        )
        assert accepted.status == 200

        for invalid_name in ("", "   ", "x" * 201, None, 42):
            response = await client.put(
                "/api/tags/hero",
                json={"new_name": invalid_name},
                headers=headers,
            )
            assert response.status == 400
            assert await response.json() == {"error": "Invalid tag name"}

        renamed = await client.put(
            "/api/tags/hero",
            json={"new_name": "  villain  "},
            headers=headers,
        )
        assert renamed.status == 200
        accepted_rename = "b" * 200
        boundary_rename = await client.put(
            "/api/tags/villain",
            json={"new_name": accepted_rename},
            headers=headers,
        )
        assert boundary_rename.status == 200
        rows = {
            row[0]
            for row in conn.execute(
                "SELECT tag FROM file_tags WHERE file_path=?", (str(target.resolve()),)
            )
        }
        assert rows == {accepted_tag, accepted_rename}
    finally:
        await client.close()


@pytest.mark.anyio
async def test_tag_routes_keep_non_validation_service_errors_as_500(
    tmp_path, monkeypatch
):
    from AssetsManager.lan.routes._helpers import LAN_APP_KEY

    app, library, _conn = _make_lan_app(tmp_path)
    (library / "asset.txt").write_text("tag me", encoding="utf-8")
    headers = _local_ui_headers(app)
    service = app[LAN_APP_KEY].services.tag_service

    def fail(*_args, **_kwargs):
        raise RuntimeError("service failed")

    client = await _make_client(app)
    try:
        monkeypatch.setattr(service, "add_tag", fail)
        created = await client.post(
            "/api/tags",
            json={"tag": "hero", "file_path": "asset.txt"},
            headers=headers,
        )
        assert created.status == 500
        assert await created.json() == {"error": "Failed to create tag"}

        monkeypatch.setattr(service, "rename_tag", fail)
        renamed = await client.put(
            "/api/tags/hero",
            json={"new_name": "villain"},
            headers=headers,
        )
        assert renamed.status == 500
        assert await renamed.json() == {"error": "Failed to rename tag"}
    finally:
        await client.close()


@pytest.mark.anyio
async def test_download_route_uses_safe_rfc5987_filename_for_unicode_file(tmp_path):
    app, library, conn = _make_lan_app(tmp_path)
    (library / "报告.txt").write_text("download me", encoding="utf-8")

    client = await _make_client(app)
    try:
        response = await client.get("/api/download/%E6%8A%A5%E5%91%8A.txt", headers=_local_ui_headers(app))

        assert response.status == 200
        header = response.headers["Content-Disposition"]
        assert header.startswith('attachment; filename=".txt"')
        assert "filename*=UTF-8''%E6%8A%A5%E5%91%8A.txt" in header
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

        # Out-of-scope files are folded into 404 (indistinguishable from a
        # missing share / file).
        blocked = await client.get(f"/api/shares/{share_id}/download/private.txt")
        assert blocked.status == 404
    finally:
        await client.close()


@pytest.mark.anyio
async def test_create_share_validation_contract(tmp_path):
    app, library, conn = _make_lan_app(tmp_path)
    (library / "asset.txt").write_text("shared asset", encoding="utf-8")
    headers = _local_ui_headers(app)

    client = await _make_client(app)
    try:
        invalid_cases = [
            ({"password": 42}, "Invalid password format"),
            ({"password": "abc"}, "Password must be at least 8 characters"),
            ({"password": "1234567"}, "Password must be at least 8 characters"),
            ({"password": "x" * 129}, "Password must be less than 128 characters"),
            ({"expires_hours": "invalid"}, "Invalid expiry format"),
            ({"expires_hours": True}, "Invalid expiry format"),
            ({"expires_hours": False}, "Invalid expiry format"),
            ({"expires_hours": 1.0}, "Invalid expiry format"),
            ({"expires_hours": 1.5}, "Invalid expiry format"),
            ({"expires_hours": float("inf")}, "Invalid expiry format"),
            ({"expires_hours": 0}, "Expiry must be between 1 and 8760 hours"),
            ({"expires_hours": 8761}, "Expiry must be between 1 and 8760 hours"),
            ({"max_downloads": "invalid"}, "Invalid max downloads format"),
            ({"max_downloads": True}, "Invalid max downloads format"),
            ({"max_downloads": False}, "Invalid max downloads format"),
            ({"max_downloads": 1.0}, "Invalid max downloads format"),
            ({"max_downloads": 1.5}, "Invalid max downloads format"),
            ({"max_downloads": float("inf")}, "Invalid max downloads format"),
            ({"max_downloads": 0}, "Max downloads must be between 1 and 10000"),
            ({"max_downloads": 10001}, "Max downloads must be between 1 and 10000"),
        ]
        for options, expected_error in invalid_cases:
            response = await client.post(
                "/api/shares",
                json={"paths": ["asset.txt"], **options},
                headers=headers,
            )
            assert response.status == 400
            assert await response.json() == {"error": expected_error}

        no_paths = await client.post(
            "/api/shares",
            json={"paths": [], "password": "abc"},
            headers=headers,
        )
        assert no_paths.status == 400
        assert await no_paths.json() == {"error": "No paths provided"}

        no_valid_paths = await client.post(
            "/api/shares",
            json={
                "paths": ["missing.txt"],
                "password": "abc",
                "expires_hours": "invalid",
                "max_downloads": "invalid",
            },
            headers=headers,
        )
        assert no_valid_paths.status == 400
        assert await no_valid_paths.json() == {"error": "No valid paths"}

        password_first = await client.post(
            "/api/shares",
            json={"paths": ["asset.txt"], "password": "abc", "expires_hours": "invalid"},
            headers=headers,
        )
        assert password_first.status == 400
        assert await password_first.json() == {"error": "Password must be at least 8 characters"}

        expiry_first = await client.post(
            "/api/shares",
            json={"paths": ["asset.txt"], "expires_hours": 0, "max_downloads": 0},
            headers=headers,
        )
        assert expiry_first.status == 400
        assert await expiry_first.json() == {"error": "Expiry must be between 1 and 8760 hours"}

        valid_cases = [
            {"password": "abcd1234"},
            {"password": "x" * 128},
            {"expires_hours": 1},
            {"expires_hours": 8760},
            {"max_downloads": 1},
            {"max_downloads": 10000},
            {"expires_hours": "3", "max_downloads": "4"},
        ]
        for options in valid_cases:
            response = await client.post(
                "/api/shares",
                json={"paths": ["asset.txt"], **options},
                headers=headers,
            )
            assert response.status == 200

        empty_password = await client.post(
            "/api/shares",
            json={"paths": ["asset.txt"], "password": ""},
            headers=headers,
        )
        assert empty_password.status == 200
        empty_data = await empty_password.json()
        assert empty_data["has_password"] is False
        row = conn.execute(
            "SELECT password_hash FROM share_links WHERE id=?", (empty_data["id"],)
        ).fetchone()
        assert row == (None,)
    finally:
        await client.close()


@pytest.mark.anyio
async def test_create_share_keeps_non_validation_failures_as_500(tmp_path, monkeypatch):
    from AssetsManager.domain.errors import ValidationError
    from AssetsManager.lan.routes._helpers import LAN_APP_KEY

    app, library, _conn = _make_lan_app(tmp_path)
    (library / "asset.txt").write_text("shared asset", encoding="utf-8")
    headers = _local_ui_headers(app)
    service = app[LAN_APP_KEY].services.share_service

    client = await _make_client(app)
    try:
        def raise_validation_error(**_kwargs):
            raise ValidationError("password", "Password must be at least 8 characters")

        monkeypatch.setattr(service, "create_share", raise_validation_error)
        invalid = await client.post(
            "/api/shares", json={"paths": ["asset.txt"]}, headers=headers,
        )
        assert invalid.status == 400
        assert await invalid.json() == {"error": "Password must be at least 8 characters"}

        monkeypatch.setattr(service, "create_share", lambda **_kwargs: None)
        failed = await client.post(
            "/api/shares", json={"paths": ["asset.txt"]}, headers=headers,
        )
        assert failed.status == 500
        assert await failed.json() == {"error": "Failed to create share link"}

        def raise_runtime_error(**_kwargs):
            raise RuntimeError("share creation failed")

        monkeypatch.setattr(service, "create_share", raise_runtime_error)
        errored = await client.post(
            "/api/shares", json={"paths": ["asset.txt"]}, headers=headers,
        )
        assert errored.status == 500
    finally:
        await client.close()


@pytest.mark.anyio
async def test_share_download_records_response_ready_and_pathless_rejection(tmp_path):
    from AssetsManager.core.performance import PerformanceRecorder
    from AssetsManager.lan.routes._helpers import LAN_APP_KEY

    app, library, _conn = _make_lan_app(tmp_path)
    folder = library / "project"
    folder.mkdir()
    asset = folder / "asset.txt"
    asset.write_text("shared asset", encoding="utf-8")
    (library / "private.txt").write_text("private", encoding="utf-8")
    recorder = PerformanceRecorder(enabled=True)
    app[LAN_APP_KEY].performance_recorder = recorder
    client = await _make_client(app)
    try:
        create = await client.post(
            "/api/shares",
            json={"paths": ["project"], "allow_preview": True},
            headers=_local_ui_headers(app),
        )
        assert create.status == 200
        share_id = (await create.json())["id"]

        success = await client.get(f"/api/shares/{share_id}/download/project/asset.txt")
        assert success.status == 200
        await _read_body(success)
        success_event = next(event for event in recorder.recent() if event.name == "lan.share_download")
        assert success_event.path == str(asset.resolve())
        assert success_event.attributes == {
            "outcome": "response_ready",
            "status": 200,
            "phase": "response_ready",
            "kind": "share_file",
        }

        recorder.clear()
        rejected = await client.get(f"/api/shares/{share_id}/download/private.txt")
        assert rejected.status == 404
        rejected_event = next(event for event in recorder.recent() if event.name == "lan.share_download")
        assert rejected_event.path is None
        assert rejected_event.attributes["outcome"] == "error"
        assert rejected_event.attributes["status"] == 404
        assert rejected_event.attributes["phase"] == "failed"
    finally:
        await client.close()


@pytest.mark.anyio
async def test_share_download_records_response_ready_and_scope_failure_is_pathless(tmp_path):
    from AssetsManager.core.performance import PerformanceRecorder
    from AssetsManager.lan.routes._helpers import LAN_APP_KEY

    app, library, _conn = _make_lan_app(tmp_path)
    folder = library / "project"
    folder.mkdir()
    (folder / "asset.txt").write_text("shared asset", encoding="utf-8")
    (library / "private.txt").write_text("private", encoding="utf-8")
    recorder = PerformanceRecorder(enabled=True)
    app[LAN_APP_KEY].performance_recorder = recorder
    client = await _make_client(app)
    try:
        create = await client.post(
            "/api/shares", json={"paths": ["project"], "allow_preview": True}, headers=_local_ui_headers(app)
        )
        share_id = (await create.json())["id"]

        response = await client.get(f"/api/shares/{share_id}/download/project/asset.txt")
        assert response.status == 200
        event = next(event for event in recorder.recent() if event.name == "lan.share_download")
        assert event.path == str((folder / "asset.txt").resolve())
        assert event.attributes == {
            "outcome": "response_ready", "status": 200, "phase": "response_ready", "kind": "share_file"
        }

        recorder.clear()
        denied = await client.get(f"/api/shares/{share_id}/download/private.txt")
        assert denied.status == 404
        denied_event = next(event for event in recorder.recent() if event.name == "lan.share_download")
        assert denied_event.path is None
        assert denied_event.attributes == {
            "outcome": "error", "status": 404, "phase": "failed", "kind": "share_file"
        }
    finally:
        await client.close()


@pytest.mark.anyio
async def test_share_download_recorder_failure_preserves_admission_and_counter(tmp_path, monkeypatch):
    from AssetsManager.core.performance import PerformanceRecorder
    from AssetsManager.lan.routes._helpers import LAN_APP_KEY

    app, library, conn = _make_lan_app(tmp_path)
    (library / "asset.txt").write_text("shared asset", encoding="utf-8")
    recorder = PerformanceRecorder(enabled=True)
    app[LAN_APP_KEY].performance_recorder = recorder
    client = await _make_client(app)
    try:
        create = await client.post(
            "/api/shares", json={"paths": ["asset.txt"], "allow_preview": True}, headers=_local_ui_headers(app)
        )
        share_id = (await create.json())["id"]
        monkeypatch.setattr(recorder, "record", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError()))

        response = await client.get(f"/api/shares/{share_id}/download/asset.txt")
        assert response.status == 200
        assert await _read_body(response) == b"shared asset"
        assert conn.execute("SELECT download_count FROM share_links WHERE id=?", (share_id,)).fetchone() == (1,)
    finally:
        await client.close()


@pytest.mark.anyio
async def test_share_download_uses_safe_rfc5987_filename_for_unicode_file(tmp_path):
    app, library, conn = _make_lan_app(tmp_path)
    (library / "报告.txt").write_text("shared asset", encoding="utf-8")

    client = await _make_client(app)
    try:
        create = await client.post(
            "/api/shares",
            json={"paths": ["报告.txt"], "allow_preview": True},
            headers=_local_ui_headers(app),
        )
        assert create.status == 200
        share_id = (await create.json())["id"]

        response = await client.get(f"/api/shares/{share_id}/download/%E6%8A%A5%E5%91%8A.txt")

        assert response.status == 200
        header = response.headers["Content-Disposition"]
        assert header.startswith('attachment; filename=".txt"')
        assert "filename*=UTF-8''%E6%8A%A5%E5%91%8A.txt" in header
    finally:
        await client.close()


@pytest.mark.anyio
async def test_share_download_limit_reached_is_folded_to_not_found(tmp_path):
    """A share over its download limit is indistinguishable from a missing share."""
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
        assert second.status == 404
        assert (await second.json())["error"] == "Share not found"

        row = conn.execute("SELECT download_count FROM share_links WHERE id=?", (share_id,)).fetchone()
        assert row == (1,)
    finally:
        await client.close()


@pytest.mark.anyio
async def test_share_download_rejected_when_increment_fails(tmp_path, monkeypatch):
    """When increment_download fails (limit race), 429 is returned without a counter bump."""
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
        assert resp.status == 429  # increment failed after response preparation
        body = await resp.json()
        assert body["error"] == "Download limit reached"
        assert "retry_after" in body
        assert resp.headers.get("Retry-After") == "0"

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
        assert second.status == 404
        assert (await second.json())["error"] == "Share not found"

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

    def test_retry_after_returns_seconds_until_oldest_request_expires(self, monkeypatch):
        """retry_after should reflect the oldest request's remaining window."""
        from AssetsManager.lan import security
        from AssetsManager.lan.security import RateLimiter

        fake_now = 1000.0
        monkeypatch.setattr(security.time, "time", lambda: fake_now)
        limiter = RateLimiter(max_requests=2, window_seconds=10)
        assert limiter.is_allowed("127.0.0.1") is True  # t=1000
        fake_now = 1004.0
        assert limiter.is_allowed("127.0.0.1") is True  # t=1004
        fake_now = 1006.0
        assert limiter.is_allowed("127.0.0.1") is False  # window full
        assert limiter.retry_after("127.0.0.1") == 4  # oldest (t=1000) expires at t=1010
        assert limiter.get_remaining("127.0.0.1") == 0
        assert limiter.retry_after("10.0.0.9") == 1  # empty bucket

    def test_get_remaining_prunes_expired_entries(self, monkeypatch):
        """get_remaining should prune expired entries without counting new ones."""
        from AssetsManager.lan import security
        from AssetsManager.lan.security import RateLimiter

        fake_now = 1000.0
        monkeypatch.setattr(security.time, "time", lambda: fake_now)
        limiter = RateLimiter(max_requests=2, window_seconds=10)
        assert limiter.is_allowed("10.0.0.1") is True  # t=1000
        fake_now = 1005.0
        assert limiter.is_allowed("10.0.0.1") is True  # t=1005
        fake_now = 1011.0  # cutoff=1001, t=1000 is expired
        assert limiter.get_remaining("10.0.0.1") == 1  # only t=1005 still active
        assert limiter.is_allowed("10.0.0.1") is True  # expired entry pruned


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
            assert blocked.status == 404
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
    async def test_share_verify_api_client_header_returns_usable_bearer_token(self, tmp_path):
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

            verify = await client.post(
                f"/api/shares/{share_id}/verify",
                json={"password": "secret123"},
                headers={"X-AssetsManager-API-Client": "1"},
            )
            assert verify.status == 200
            data = await verify.json()
            token = data["token"]
            assert data["share"]["id"] == share_id
            assert "Set-Cookie" not in verify.headers

            client.session.cookie_jar.clear()
            auth = {"Authorization": f"Bearer {token}"}
            info = await client.get(f"/api/shares/{share_id}/info", headers=auth)
            assert info.status == 200
            assert (await info.json())["paths"] == ["image.png"]
            preview = await client.get(f"/api/shares/{share_id}/preview/image.png", headers=auth)
            assert preview.status == 200
            download = await client.get(
                f"/api/shares/{share_id}/download/image.png",
                headers=auth,
            )
            assert download.status == 200
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
        parts = token.split(".")
        assert len(parts) == 3  # ts.nonce.sig
        assert len(parts[2]) == 32  # 32 hex chars = 128 bits

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
    async def test_share_create_and_list_serialize_server_share_url_and_key_requirement(self, tmp_path):
        from AssetsManager.lan.routes._helpers import LAN_APP_KEY

        app, library, conn = _make_lan_app(tmp_path)
        (library / "file.txt").write_text("content", encoding="utf-8")
        app[LAN_APP_KEY].access_key_hash = "configured-key-hash"
        app[LAN_APP_KEY].endpoint_protocol = "https"

        client = await _make_client(app)
        try:
            create = await client.post(
                "/api/shares",
                json={"paths": ["file.txt"], "allow_preview": True},
                headers=_local_ui_headers(app),
            )
            assert create.status == 200
            created = await create.json()
            assert created["url"].startswith("https://")
            assert created["url"].endswith(f"/s/{created['id']}")
            assert created["requires_key"] is True

            listed = await client.get("/api/shares", headers=_local_ui_headers(app))
            assert listed.status == 200
            shares = (await listed.json())["shares"]
            assert shares[0]["url"] == created["url"]
            assert shares[0]["requires_key"] is True
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_list_shares_rejects_missing_user_after_permission_check(self, monkeypatch):
        from AssetsManager.lan.routes import shares

        monkeypatch.setattr(shares, "require_permission", lambda request, permission: True)
        monkeypatch.setattr(shares, "get_lan", lambda request: object())
        monkeypatch.setattr(shares, "get_share_service", lambda request: object())
        monkeypatch.setattr(shares, "get_request_principal", lambda request: None)

        response = await shares.handle_list_shares(object())

        assert response.status == 401

    @pytest.mark.anyio
    async def test_access_key_auth_sets_admin_context_for_shares(self, tmp_path):
        import warnings
        from aiohttp.test_utils import TestClient, TestServer
        from aiohttp.web import NotAppKeyWarning
        from AssetsManager.core import database
        from AssetsManager.lan.routes._helpers import AUTH_SERVICE_APP_KEY

        library = tmp_path / "library"
        library.mkdir()
        (library / "file.txt").write_text("content", encoding="utf-8")
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript(database._SCHEMA)
            conn.commit()
            _init_lan_schemas(conn)
            server = _legacy_server(
                library_root=str(library),
                thumbnail_dir=str(tmp_path / "thumbs"),
                db_conn=conn,
                access_key="raw-key",
            )
            server._app[AUTH_SERVICE_APP_KEY] = server._auth_service

            client = TestClient(TestServer(server._app))
            await client.start_server()
            try:
                auth = {"Authorization": "Bearer raw-key"}
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always", NotAppKeyWarning)
                    create = await client.post(
                        "/api/shares",
                        json={"paths": ["file.txt"], "allow_preview": True},
                        headers=auth,
                    )
                    assert create.status == 200
                    share_id = (await create.json())["id"]

                    create_for_delete = await client.post(
                        "/api/shares",
                        json={"paths": ["file.txt"], "allow_preview": True},
                        headers=auth,
                    )
                    assert create_for_delete.status == 200
                    share_id_for_delete = (await create_for_delete.json())["id"]

                    list_resp = await client.get("/api/shares", headers=auth)
                    assert list_resp.status == 200
                    data = await list_resp.json()

                    unauth_delete = await client.delete(f"/api/shares/{share_id}")
                    assert unauth_delete.status == 401

                    delete_resp = await client.delete(f"/api/shares/{share_id_for_delete}", headers=auth)
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
        from AssetsManager.lan.auth import hash_password
        from AssetsManager.core import database

        library = tmp_path / "library"
        library.mkdir()
        (library / "file.txt").write_text("content", encoding="utf-8")

        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript(database._SCHEMA)
            _init_lan_schemas(conn)
            conn.commit()

            server = _legacy_server(
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
        from AssetsManager.lan.auth import hash_password
        from AssetsManager.core import database
        from aiohttp.test_utils import TestClient, TestServer

        library = tmp_path / "library"
        library.mkdir()
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript(database._SCHEMA)
            _init_lan_schemas(conn)
            conn.commit()
            server = _legacy_server(
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
        from AssetsManager.lan.auth import hash_password
        from AssetsManager.lan.routes._helpers import AUTH_SERVICE_APP_KEY

        library = tmp_path / "library"
        library.mkdir()
        (library / "shared.txt").write_text("shared", encoding="utf-8")
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript(database._SCHEMA)
            _init_lan_schemas(conn)
            conn.commit()
            server = _legacy_server(
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
        from AssetsManager.lan.auth import hash_password
        from AssetsManager.core import database

        library = tmp_path / "library"
        library.mkdir()

        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript(database._SCHEMA)
            _init_lan_schemas(conn)
            conn.execute(
                "INSERT INTO users (username, password, role, is_active) VALUES (?, ?, 'admin', 1)",
                ("admin", hash_password("Admin@1234")),
            )
            conn.commit()

            server = _legacy_server(
                library_root=str(library),
                thumbnail_dir=str(tmp_path / "thumbs"),
                db_conn=conn,
                access_key="admin-key",
            )

            from aiohttp.test_utils import TestClient, TestServer
            client = TestClient(TestServer(server._app))
            await client.start_server()
            try:
                resp = await client.get("/api/users", headers={"Authorization": "Bearer admin-key"})
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
    async def test_thumbnail_route_serves_nested_image_for_browser_preview(self, tmp_path):
        pytest.importorskip("PIL")
        from PIL import Image

        app, library, _conn = _make_lan_app(tmp_path)
        target = library / "characters" / "hero image.png"
        target.parent.mkdir()
        Image.new("RGB", (32, 24), color="red").save(target)
        client = await _make_client(app)
        try:
            response = await client.get(
                "/api/thumbnails/characters/hero%20image.png?size=512"
            )
            body = await response.read()
            assert response.status == 200
            assert response.headers["Content-Type"].startswith("image/")
            assert body
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_thumbnail_records_canonical_route_metric(self, tmp_path):
        from AssetsManager.core.performance import PerformanceRecorder
        from AssetsManager.lan.routes._helpers import LAN_APP_KEY

        app, library, _conn = _make_lan_app(tmp_path)
        (library / "image.png").write_bytes(b"\x89PNG" + b"\x00" * 100)
        recorder = PerformanceRecorder(enabled=True)
        app[LAN_APP_KEY].performance_recorder = recorder
        app[LAN_APP_KEY].session_token = "session-a"
        client = await _make_client(app)
        try:
            response = await client.get("/api/thumbnails/image.png")
            assert response.status in (200, 404)

            event = next(event for event in recorder.recent() if event.name == "lan.thumbnail")
            assert event.session_token == "session-a"
            assert event.path == str((library / "image.png").resolve())
            assert event.attributes["status"] == response.status
            assert event.attributes["outcome"] == ("success" if response.status == 200 else "error")
            assert event.attributes["delivery"] in {"original", "processed", "none"}
            assert isinstance(event.attributes["cache_hit"], bool)
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_thumbnail_denial_and_path_escape_are_pathless(self, tmp_path, monkeypatch):
        from AssetsManager.core.performance import PerformanceRecorder
        from AssetsManager.lan.routes import thumbnails
        from AssetsManager.lan.routes._helpers import LAN_APP_KEY

        app, _library, _conn = _make_lan_app(tmp_path, authenticated_context_only=True)
        recorder = PerformanceRecorder(enabled=True)
        app[LAN_APP_KEY].performance_recorder = recorder
        monkeypatch.setattr(thumbnails, "require_permission", lambda _request, _permission: False)
        client = await _make_client(app)
        try:
            denied = await client.get("/api/thumbnails/private.png")
            assert denied.status == 403
            denied_event = next(event for event in recorder.recent() if event.name == "lan.thumbnail")
            assert denied_event.path is None
            assert denied_event.attributes == {
                "outcome": "error", "status": 403, "delivery": "none", "cache_hit": False
            }

            recorder.clear()
            monkeypatch.setattr(thumbnails, "require_permission", lambda _request, _permission: True)
            escaped = await client.get("/api/thumbnails/..%2Fprivate.png")
            assert escaped.status == 400
            escaped_event = next(event for event in recorder.recent() if event.name == "lan.thumbnail")
            assert escaped_event.path is None
            assert escaped_event.attributes["status"] == 400
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_thumbnail_batch_records_aggregate_metric_without_paths(self, tmp_path):
        from AssetsManager.core.performance import PerformanceRecorder
        from AssetsManager.lan.routes._helpers import LAN_APP_KEY

        app, library, _conn = _make_lan_app(tmp_path)
        (library / "image.png").write_bytes(b"\x89PNG" + b"\x00" * 100)
        recorder = PerformanceRecorder(enabled=True)
        app[LAN_APP_KEY].performance_recorder = recorder
        client = await _make_client(app)
        try:
            response = await client.post("/api/thumbnails/batch", json={"paths": ["image.png"]})
            assert response.status == 200

            event = next(event for event in recorder.recent() if event.name == "lan.thumbnail_batch")
            assert event.path is None
            assert event.attributes == {
                "outcome": "success",
                "status": 200,
                "requested_count": 1,
                "result_count": 0,
                "failed_count": 0,
            }
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_thumbnail_batch_records_partial_and_path_escape_outcomes(self, tmp_path, monkeypatch):
        from AssetsManager.core.performance import PerformanceRecorder
        from AssetsManager.lan.routes import thumbnails
        from AssetsManager.lan.routes._helpers import LAN_APP_KEY

        app, library, _conn = _make_lan_app(tmp_path)
        (library / "image.png").write_bytes(b"image")
        recorder = PerformanceRecorder(enabled=True)
        app[LAN_APP_KEY].performance_recorder = recorder

        class _FailingThumbnailService:
            def resolve(self, *_args, **_kwargs):
                raise RuntimeError("resolution failed")

        monkeypatch.setattr(thumbnails, "get_thumbnail_service", lambda _request: _FailingThumbnailService())
        client = await _make_client(app)
        try:
            partial = await client.post("/api/thumbnails/batch", json={"paths": ["image.png"]})
            assert partial.status == 200
            partial_event = next(event for event in recorder.recent() if event.name == "lan.thumbnail_batch")
            assert partial_event.path is None
            assert partial_event.attributes == {
                "outcome": "partial",
                "status": 200,
                "requested_count": 1,
                "result_count": 0,
                "failed_count": 1,
            }

            recorder.clear()
            escaped = await client.post("/api/thumbnails/batch", json={"paths": ["../private.png"]})
            assert escaped.status == 400
            escaped_event = next(event for event in recorder.recent() if event.name == "lan.thumbnail_batch")
            assert escaped_event.path is None
            assert escaped_event.attributes == {
                "outcome": "error",
                "status": 400,
                "requested_count": 1,
                "result_count": 0,
                "failed_count": 0,
            }
        finally:
            await client.close()

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

            server = _legacy_server(
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
        from AssetsManager.lan.auth import hash_password

        library = tmp_path / "library"
        library.mkdir()
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript(database._SCHEMA)
            _init_lan_schemas(conn)
            server = _legacy_server(
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

        library = tmp_path / "library"
        library.mkdir()
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript(database._SCHEMA)
            _init_lan_schemas(conn)
            server = _legacy_server(
                library_root=str(library), thumbnail_dir=str(tmp_path / "thumbs"), db_conn=conn,
            )
            client = TestClient(TestServer(server._app))
            await client.start_server()
            try:
                for path in (
                    "/static/index.html.bak",
                    "/static/style.css.bak2",
                    "/static/nested/old.JS.BAK",
                    "/static/nested/old.css.BAK2",
                ):
                    response = await client.get(path)
                    assert response.status == 404, path
            finally:
                await client.close()
        finally:
            conn.close()

    @pytest.mark.anyio
    async def test_static_route_blocks_path_escape(self, tmp_path):
        from aiohttp.test_utils import TestClient, TestServer
        from AssetsManager.core import database

        library = tmp_path / "library"
        library.mkdir()
        (tmp_path / "private.txt").write_text("private", encoding="utf-8")
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript(database._SCHEMA)
            _init_lan_schemas(conn)
            server = _legacy_server(
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
        from AssetsManager.lan.auth import hash_password
        from AssetsManager.lan.routes._helpers import AUTH_SERVICE_APP_KEY

        library = tmp_path / "library"
        library.mkdir()
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript(database._SCHEMA)
            _init_lan_schemas(conn)
            server = _legacy_server(
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
                assert static.status == 401

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
            assert int(cookie["max-age"]) == 3600
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
    async def test_browser_share_verify_returns_cookie_only(self, tmp_path):
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
            )
            assert verify.status == 200
            data = await verify.json()
            assert "token" not in data
            assert verify.cookies["share_token"]["httponly"]

            client.session.cookie_jar.clear()
            download = await client.get(
                f"/api/shares/{share_id}/download/file.txt",
                headers={"Authorization": "Bearer not-a-share-cookie"},
            )
            assert download.status == 401
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
            # The download endpoint folds expired state into 404 (L2), while
            # verify and preview still surface 410.
            assert download.status == 404

            preview = await client.get(f"/api/shares/{share_id}/preview/image.png")
            assert preview.status == 410
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_share_verify_returns_429_after_five_failed_attempts(self, tmp_path):
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

            # Four failures are still allowed.
            for _ in range(4):
                wrong = await client.post(
                    f"/api/shares/{share_id}/verify", json={"password": "wrong-pass"}
                )
                assert wrong.status == 401

            # The fifth failure is recorded (still 401)...
            fifth = await client.post(
                f"/api/shares/{share_id}/verify", json={"password": "wrong-pass"}
            )
            assert fifth.status == 401

            # ...and every later attempt — even with the correct password —
            # is refused with 429 until the cooldown window elapses.
            blocked = await client.post(
                f"/api/shares/{share_id}/verify", json={"password": "secret123"}
            )
            assert blocked.status == 429
            assert blocked.headers.get("Retry-After") is not None
            body = await blocked.json()
            assert body["error"] == "Too many failed password attempts. Please try again later."
            assert body["retry_after"] > 0

            still_blocked = await client.post(
                f"/api/shares/{share_id}/verify", json={"password": "wrong-pass"}
            )
            assert still_blocked.status == 429
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_share_verify_success_resets_failure_counter(self, tmp_path):
        from AssetsManager.lan.routes._helpers import LAN_APP_KEY

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
            share_svc = app[LAN_APP_KEY].services.share_service

            for _ in range(4):
                wrong = await client.post(
                    f"/api/shares/{share_id}/verify", json={"password": "wrong-pass"}
                )
                assert wrong.status == 401

            # A successful verification clears the counter.
            ok = await client.post(
                f"/api/shares/{share_id}/verify", json={"password": "secret123"}
            )
            assert ok.status == 200
            assert share_svc.password_attempt_blocked(share_id) == 0

            # Without the reset, the next two failures would already trip the
            # lockout; with it, they stay plain 401s.
            for _ in range(3):
                wrong = await client.post(
                    f"/api/shares/{share_id}/verify", json={"password": "wrong-pass"}
                )
                assert wrong.status == 401
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_share_verify_lockout_is_per_share(self, tmp_path):
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
            other = await client.post(
                "/api/shares",
                json={"paths": ["file.txt"], "password": "secret123", "allow_preview": True},
                headers=_local_ui_headers(app),
            )
            assert other.status == 200
            other_id = (await other.json())["id"]

            for _ in range(5):
                await client.post(
                    f"/api/shares/{share_id}/verify", json={"password": "wrong-pass"}
                )

            locked = await client.post(
                f"/api/shares/{share_id}/verify", json={"password": "secret123"}
            )
            assert locked.status == 429

            unaffected = await client.post(
                f"/api/shares/{other_id}/verify", json={"password": "secret123"}
            )
            assert unaffected.status == 200
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_middleware_rejects_invalid_token_when_password_set(self, tmp_path):
        """When password auth is enabled, invalid tokens get 401."""

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
            server = _legacy_server(
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
    async def test_middleware_rejects_access_key_via_query_param(self, tmp_path):
        """Verify that query-parameter auth (?key= / ?token=) is rejected."""

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
            server = _legacy_server(
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
                # ?key= is rejected — query-parameter auth is disabled
                resp = await client.get(f"/api/files?key={raw_key}")
                assert resp.status == 401

                # ?token= is rejected too
                resp2 = await client.get(f"/api/files?token={raw_key}")
                assert resp2.status == 401

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
            server = _legacy_server(
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
    async def test_search_records_session_scoped_route_metric(self, tmp_path):
        from AssetsManager.core.performance import PerformanceRecorder
        from AssetsManager.lan.routes._helpers import LAN_APP_KEY

        app, library, _conn = _make_lan_app(tmp_path)
        (library / "hero.png").write_bytes(b"image")
        recorder = PerformanceRecorder(enabled=True)
        lan = app[LAN_APP_KEY]
        assert isinstance(lan, _FakeLan)
        lan.performance_recorder = recorder
        lan.session_token = "session-a"
        client = await _make_client(app)
        try:
            response = await client.get("/api/search?q=hero")
            assert response.status == 200

            event = next(event for event in recorder.recent() if event.name == "lan.search")
            assert event.session_token == "session-a"
            assert event.path is None
            assert event.attributes["outcome"] == "success"
            assert event.attributes["status"] == 200
            assert event.attributes["result_count"] >= 0
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_search_denial_records_no_sensitive_request_data(self, tmp_path, monkeypatch):
        from AssetsManager.core.performance import PerformanceRecorder
        from AssetsManager.lan.routes import metadata
        from AssetsManager.lan.routes._helpers import LAN_APP_KEY

        app, _library, _conn = _make_lan_app(tmp_path, authenticated_context_only=True)
        recorder = PerformanceRecorder(enabled=True)
        app[LAN_APP_KEY].performance_recorder = recorder
        monkeypatch.setattr(metadata, "require_permission", lambda _request, _permission: False)
        client = await _make_client(app)
        try:
            response = await client.get("/api/search?q=secret&tags=private&category=images")
            assert response.status == 403

            events = recorder.recent()
            assert [(event.name, event.path, event.attributes) for event in events] == [
                ("lan.search", None, {"outcome": "error", "status": 403, "result_count": -1})
            ]
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_search_failure_records_error_route_metric(self, tmp_path, monkeypatch):
        from AssetsManager.core.performance import PerformanceRecorder
        from AssetsManager.lan.routes import metadata
        from AssetsManager.lan.routes._helpers import LAN_APP_KEY

        app, _library, _conn = _make_lan_app(tmp_path)
        recorder = PerformanceRecorder(enabled=True)
        app[LAN_APP_KEY].performance_recorder = recorder

        def fail_service(_request):
            raise RuntimeError("search service failed")

        monkeypatch.setattr(metadata, "get_search_service", fail_service)
        client = await _make_client(app)
        try:
            response = await client.get("/api/search?q=secret")
            assert response.status == 500

            event = next(event for event in recorder.recent() if event.name == "lan.search")
            assert event.path is None
            assert event.attributes == {"outcome": "error", "status": 500, "result_count": -1}
        finally:
            await client.close()

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

    @pytest.mark.anyio
    async def test_explicit_none_auth_mode_ignores_active_users(self, tmp_path):
        from AssetsManager.application.auth_service import AuthService
        from AssetsManager.core import database

        library = tmp_path / "library"
        library.mkdir()
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript(database._SCHEMA)
            _init_lan_schemas(conn)
            user_id, error = AuthService(conn, "test-secret").register_user(
                "existing-user", "Test@1234"
            )
            assert user_id is not None, error

            server = _legacy_server(
                library_root=str(library),
                thumbnail_dir=str(tmp_path / "thumbs"),
                db_conn=conn,
                auth_mode="none",
            )
            client = await _make_client(server._app)
            try:
                info_response = await client.get("/api/info")
                info = await info_response.json()
                assert info_response.status == 200
                assert info["auth_enabled"] is False
                assert info["auth_mode"] == "none"
                assert server.status()["auth_enabled"] is False

                user = server._auth_service.list_users()[0]
                stale_user_token = server._auth_service.generate_user_token(
                    user_id, user["username"], user["role"]
                )
                stale_info_response = await client.get(
                    "/api/info",
                    headers={"Authorization": f"Bearer {stale_user_token}"},
                )
                stale_info = await stale_info_response.json()
                assert stale_info["principal"]["kind"] == "guest"

                me_response = await client.get("/api/auth/me")
                me = await me_response.json()
                assert me_response.status == 200
                assert me["principal"]["kind"] == "guest"
                assert me["principal"]["authenticated"] is False
            finally:
                await client.close()
        finally:
            conn.close()


def test_activity_log_and_online_users_expose_normalized_records():
    from AssetsManager.lan.routes._helpers import ActivityLog, OnlineUsers

    activity = ActivityLog()
    activity.add("alice", "login", "signed in", ip="10.0.0.4")
    record = activity.recent(1)[0]
    assert set(record) == {"id", "username", "action", "details", "ip", "timestamp"}
    assert record["username"] == "alice"
    assert record["details"] == "signed in"
    assert record["ip"] == "10.0.0.4"

    online = OnlineUsers()
    online.connect("user:1", "alice", "10.0.0.4")
    online.connect("user:1", "alice", "10.0.0.4")
    assert online.list_all()[0]["user_id"] == "user:1"
    online.disconnect("user:1")
    assert online.list_all()[0]["user_id"] == "user:1"
    online.disconnect("user:1")
    assert online.list_all() == []


@pytest.mark.anyio
async def test_server_stats_count_requests_and_report_uptime(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    _init_lan_schemas(conn)
    server = _legacy_server(
        library_root=str(library), thumbnail_dir=str(tmp_path / "thumbs"), db_conn=conn
    )
    client = await _make_client(server._app)
    try:
        before = server.status()
        await client.get("/api/info")
        after = server.status()
        assert after["requests"] > before["requests"]
        assert after["uptime"] >= 0
    finally:
        await client.close()
        conn.close()


@pytest.mark.anyio
async def test_websocket_manager_reports_live_connection_count():
    from AssetsManager.lan.ws import WebSocketManager

    changes = []
    manager = WebSocketManager(on_connection_change=lambda count: changes.append(count))

    class Client:
        async def close(self, **_kwargs):
            pass

    ws = Client()
    assert await manager.add(ws) is True
    await manager.remove(ws)
    assert changes == [1, 0]


@pytest.mark.anyio
async def test_websocket_connection_counts_stay_ordered_during_async_removal():
    from AssetsManager.lan.ws import WebSocketManager

    changes = []
    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()

    async def pause_cleanup():
        cleanup_started.set()
        await release_cleanup.wait()

    manager = WebSocketManager(on_connection_change=changes.append)

    class Client:
        async def close(self, **_kwargs):
            pass

    removed_client = Client()
    added_client = Client()
    assert await manager.add(removed_client, on_remove=pause_cleanup) is True

    remove_task = asyncio.create_task(manager.remove(removed_client))
    await cleanup_started.wait()
    add_task = asyncio.create_task(manager.add(added_client))
    await asyncio.sleep(0)

    assert changes == [1]
    assert not add_task.done()

    release_cleanup.set()
    assert await remove_task is True
    assert await add_task is True

    assert changes == [1, 0, 1]
    assert changes[-1] == len(manager._clients)


@pytest.mark.anyio
async def test_websocket_cancelled_admission_reservation_rolls_back_and_unblocks_callbacks(
    monkeypatch,
):
    from AssetsManager.lan.ws import WebSocketManager

    lifecycle = []

    class Client:
        async def close(self, **_kwargs):
            lifecycle.append("close")

    manager = WebSocketManager(on_connection_change=lambda count: lifecycle.append(count))
    original_run_reserved = manager._run_reserved
    first_run = True

    async def run_reserved(reservation):
        nonlocal first_run
        if first_run:
            first_run = False
            asyncio.current_task().cancel()
            await asyncio.sleep(0)
        await original_run_reserved(reservation)

    monkeypatch.setattr(manager, "_run_reserved", run_reserved)
    cancelled = Client()
    admission = asyncio.create_task(manager.add(
        cancelled,
        on_admission=lambda: lifecycle.append("admission"),
        on_remove=lambda: lifecycle.append("remove"),
    ))
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(admission, timeout=0.2)
    await asyncio.sleep(0)

    assert cancelled not in manager._clients
    assert manager._leases == {}
    assert lifecycle == ["remove", 0, "close"]

    healthy = Client()
    assert await asyncio.wait_for(manager.add(healthy), timeout=0.2) is True
    assert healthy in manager._clients


@pytest.mark.anyio
async def test_websocket_cancelled_removal_reservation_unblocks_following_callback(
    monkeypatch,
):
    from AssetsManager.lan.ws import WebSocketManager

    lifecycle = []

    class Client:
        async def close(self, **_kwargs):
            lifecycle.append("close")

    manager = WebSocketManager()
    client = Client()
    assert await manager.add(client) is True
    def run_reserved(_reservation):
        asyncio.current_task().cancel()
        return asyncio.sleep(0)

    monkeypatch.setattr(manager, "_run_reserved", run_reserved)
    removal = asyncio.create_task(manager.remove(client))
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(removal, timeout=0.2)

    assert client not in manager._clients
    assert manager._on_remove == {}

    callback = asyncio.create_task(manager._notify_connection_change(0))
    await asyncio.wait_for(callback, timeout=0.2)


@pytest.mark.anyio
async def test_websocket_cancelled_admission_behind_blocked_callback_unblocks_queue():
    from AssetsManager.lan.ws import WebSocketManager

    predecessor_started = asyncio.Event()
    release_predecessor = asyncio.Event()
    lifecycle = []

    async def predecessor(_value):
        predecessor_started.set()
        await release_predecessor.wait()

    class Client:
        async def close(self, **_kwargs):
            lifecycle.append("close")

    manager = WebSocketManager(
        on_connection_change=lambda count: lifecycle.append(("count", count)),
    )
    predecessor_task = asyncio.create_task(
        manager._invoke_callback(predecessor, "predecessor")
    )
    await predecessor_started.wait()

    client = Client()
    admission = asyncio.create_task(manager.add(client))
    await asyncio.sleep(0)
    admission.cancel()
    with pytest.raises(asyncio.CancelledError):
        await admission

    release_predecessor.set()
    await asyncio.wait_for(predecessor_task, timeout=0.2)
    third = asyncio.create_task(manager._notify_connection_change(0))
    await asyncio.wait_for(third, timeout=0.2)

    assert client not in manager._clients
    assert client not in manager._leases
    assert manager._leases == {}
    assert lifecycle == [("count", 0), "close", ("count", 0)]


@pytest.mark.anyio
async def test_websocket_cancelled_reserved_follower_preserves_predecessor_future():
    from AssetsManager.lan.ws import WebSocketManager

    predecessor_started = asyncio.Event()
    release_predecessor = asyncio.Event()
    lifecycle = []

    async def predecessor(_count):
        predecessor_started.set()
        await release_predecessor.wait()
        lifecycle.append("predecessor")

    manager = WebSocketManager(on_connection_change=predecessor)
    predecessor_task = asyncio.create_task(manager._invoke_callback(predecessor, 0))
    await predecessor_started.wait()
    predecessor_future = manager._callback_tail
    assert predecessor_future is not None

    reservation = manager._reserve_callback(manager._admission_callbacks, None, 1)
    follower_task = asyncio.create_task(manager._run_reserved(reservation))
    await asyncio.sleep(0)
    follower_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await follower_task

    assert not predecessor_future.cancelled()
    assert not predecessor_future.done()

    release_predecessor.set()
    await asyncio.wait_for(predecessor_task, timeout=0.2)
    assert not predecessor_future.cancelled()
    assert predecessor_future.done()

    await asyncio.wait_for(manager._invoke_callback(lambda: lifecycle.append("later")), timeout=0.2)
    assert lifecycle == ["predecessor", "later"]


@pytest.mark.anyio
async def test_websocket_direct_callback_cancelled_behind_blocked_callback_unblocks_queue():
    from AssetsManager.lan.ws import WebSocketManager

    first_started = asyncio.Event()
    release_first = asyncio.Event()
    lifecycle = []
    predecessor_completions = 0
    predecessor_future_completions = []

    async def first_callback():
        nonlocal predecessor_completions
        first_started.set()
        await release_first.wait()
        predecessor_completions += 1
        lifecycle.append("first")

    async def third_callback():
        lifecycle.append("third")

    manager = WebSocketManager()
    first = asyncio.create_task(manager._invoke_callback(first_callback))
    await first_started.wait()
    predecessor = manager._callback_tail
    assert predecessor is not None
    predecessor.add_done_callback(
        lambda _future: predecessor_future_completions.append(None)
    )
    second = asyncio.create_task(manager._invoke_callback(lambda: lifecycle.append("second")))
    await asyncio.sleep(0)
    second.cancel()
    with pytest.raises(asyncio.CancelledError):
        await second

    release_first.set()
    await asyncio.wait_for(first, timeout=0.2)
    await asyncio.sleep(0)
    assert not predecessor.cancelled()
    assert predecessor.done()
    assert predecessor_completions == 1
    assert len(predecessor_future_completions) == 1
    await asyncio.wait_for(manager._invoke_callback(third_callback), timeout=0.2)

    assert lifecycle == ["first", "third"]
    assert manager._callback_tail is not None
    assert manager._callback_tail.done()


@pytest.mark.anyio
async def test_websocket_cancelled_removal_behind_blocked_callback_unblocks_queue():
    from AssetsManager.lan.ws import WebSocketManager

    predecessor_started = asyncio.Event()
    release_predecessor = asyncio.Event()
    lifecycle = []

    async def predecessor(_value):
        predecessor_started.set()
        await release_predecessor.wait()

    class Client:
        async def close(self, **_kwargs):
            pass

    manager = WebSocketManager()
    client = Client()
    assert await manager.add(client) is True

    predecessor_task = asyncio.create_task(
        manager._invoke_callback(predecessor, "predecessor")
    )
    await predecessor_started.wait()
    removal = asyncio.create_task(
        manager.remove(client)
    )
    await asyncio.sleep(0)
    removal.cancel()
    with pytest.raises(asyncio.CancelledError):
        await removal

    release_predecessor.set()
    await asyncio.wait_for(predecessor_task, timeout=0.2)

    async def third_callback():
        lifecycle.append("third")

    third = asyncio.create_task(manager._invoke_callback(third_callback))
    await asyncio.wait_for(third, timeout=0.2)

    assert client not in manager._clients
    assert manager._leases == {}
    assert manager._on_remove == {}
    assert lifecycle == ["third"]


def test_server_status_tracks_websocket_manager_connections(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    _init_lan_schemas(conn)
    server = _legacy_server(
        library_root=str(library), thumbnail_dir=str(tmp_path / "thumbs"), db_conn=conn
    )
    try:
        server.ws_manager._on_connection_change(3)
        assert server.status()["connections"] == 3
    finally:
        conn.close()


class TestUserCacheInvalidation:

    def test_active_user_cache_delegates_to_auth_service(self, tmp_path, monkeypatch):
        from AssetsManager.core import database

        library = tmp_path / "library"
        library.mkdir()
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript(database._SCHEMA)
            _init_lan_schemas(conn)
            server = _legacy_server(
                library_root=str(library),
                thumbnail_dir=str(tmp_path / "thumbs"),
                db_conn=conn,
            )
            calls = []
            monkeypatch.setattr(
                server._auth_service,
                "has_active_users",
                lambda *, raise_on_error: calls.append(raise_on_error) or True,
            )

            assert server._has_active_users() is True
            assert calls == [True]
            assert server._has_users_cache is True
        finally:
            conn.close()

    def test_active_user_failure_fails_closed_once_per_ttl(self, tmp_path, monkeypatch, caplog):
        """A failing auth probe is cached fail-closed and logged once per TTL."""
        import logging
        import time as _time
        from AssetsManager.core import database

        library = tmp_path / "library"
        library.mkdir()
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript(database._SCHEMA)
            _init_lan_schemas(conn)
            server = _legacy_server(
                library_root=str(library),
                thumbnail_dir=str(tmp_path / "thumbs"),
                db_conn=conn,
            )
            calls = []

            def _boom(*, raise_on_error):
                calls.append(raise_on_error)
                raise RuntimeError("auth db down")

            monkeypatch.setattr(server._auth_service, "has_active_users", _boom)
            fake_now = {"value": 1000.0}
            monkeypatch.setattr(_time, "time", lambda: fake_now["value"])

            logger = "AssetsManager.lan.server"
            with caplog.at_level(logging.WARNING, logger=logger):
                assert server._has_active_users() is True  # fails closed
                assert server._has_active_users() is True  # negative cache hit
                assert server._has_active_users() is True  # still no new probe
            assert calls == [True]
            assert server._has_users_cache is True
            assert server._has_users_cache_time == 1000.0

            # After the TTL elapses the probe is retried (and logged again).
            fake_now["value"] += 31.0
            with caplog.at_level(logging.WARNING, logger=logger):
                assert server._has_active_users() is True
            assert calls == [True, True]

            warnings = [
                record
                for record in caplog.records
                if "Unable to inspect active LAN users" in record.getMessage()
            ]
            assert len(warnings) == 2
            assert all(record.levelno == logging.WARNING for record in warnings)
            assert all(record.exc_info is None for record in warnings)
        finally:
            conn.close()

    def test_toggle_user_invalidates_active_users_cache(self, tmp_path):
        from AssetsManager.core import database

        library = tmp_path / "library"
        library.mkdir()
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript(database._SCHEMA)
            _init_lan_schemas(conn)
            conn.execute(
                "INSERT INTO users (username, password, role, is_active) VALUES ('target', 'x', 'viewer', 1)"
            )
            conn.commit()

            server = _legacy_server(
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

        library = tmp_path / "library"
        library.mkdir()
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript(database._SCHEMA)
            _init_lan_schemas(conn)
            conn.execute(
                "INSERT INTO users (username, password, role, is_active) VALUES (?, ?, 'viewer', 1)",
                ("target", hash_password("Target@1234")),
            )
            conn.commit()

            server = _legacy_server(
                library_root=str(library),
                thumbnail_dir=str(tmp_path / "thumbs"),
                db_conn=conn,
                access_key="admin-key",
            )

            client = TestClient(TestServer(server._app))
            await client.start_server()
            try:
                class UserSocket:
                    def __init__(self):
                        self.closed = False

                    async def close(self, **_kwargs):
                        self.closed = True

                user_socket = UserSocket()
                await server.ws_manager.add(
                    user_socket,
                    authorize=lambda: bool(conn.execute(
                        "SELECT is_active FROM users WHERE id=1",
                    ).fetchone()[0]),
                    authority=("user", 1),
                )
                assert server._has_active_users() is True
                server._has_users_cache = True
                server._has_users_cache_time = 9999999999

                resp = await client.post(
                    "/api/users/1/toggle",
                    json={"active": False},
                    headers={"Authorization": "Bearer admin-key"},
                )
                assert resp.status == 200
                assert (await resp.json())["ok"] is True

                assert server._has_users_cache is None
                assert server._has_active_users() is False

                row = conn.execute("SELECT is_active FROM users WHERE id=1").fetchone()
                assert row[0] == 0
                assert user_socket.closed
                assert user_socket not in server.ws_manager._clients
            finally:
                await client.close()
        finally:
            conn.close()
