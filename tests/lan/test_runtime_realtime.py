import asyncio
import concurrent.futures
import gc
import json
import logging
import threading
import warnings
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from aiohttp import ClientSession, WSMsgType, web
from aiohttp.test_utils import TestClient, TestServer
from aiohttp.client_exceptions import WSServerHandshakeError

from AssetsManager.lan.api import setup_routes
from AssetsManager.lan.principal import principal_for_request
from AssetsManager.lan.routes._helpers import (
    LAN_APP_KEY,
    OnlineUsers,
    set_request_principal,
)
from AssetsManager.lan.routes.websocket import (
    _authorization_authority,
    _authorization_validator,
)
from AssetsManager.lan.ws import WebSocketManager
from AssetsManager.domain.event_bus import get_event_bus


@dataclass(frozen=True)
class _Event:
    epoch: str
    revision: int
    domains: tuple[str, ...]
    paths: tuple[str, ...]


class _Subscription:
    def __init__(self, router, callback):
        self.router = router
        self.callback = callback
        self.closed = False

    def close(self):
        self.closed = True
        self.router.subscriptions.remove(self)


class _Router:
    def __init__(self, runtime):
        self.runtime = runtime
        self.subscriptions = []

    def subscribe(self, callback):
        subscription = _Subscription(self, callback)
        self.subscriptions.append(subscription)
        return subscription

    def emit(self, event):
        for subscription in tuple(self.subscriptions):
            if event.epoch == self.runtime.epoch:
                subscription.callback(event)


class _Runtime:
    def __init__(self):
        self.epoch = "epoch-a"
        self.revision = 7
        self.event_router = _Router(self)


class _Lan:
    def __init__(self, runtime):
        self.runtime = runtime
        self.ws_manager = WebSocketManager()
        self.access_key_hash = None
        self.password_hash = None
        self.token_secret = "test-secret"
        self._auth_service = _AuthService()
        self.services = SimpleNamespace(online_users=OnlineUsers())


class _AuthService:
    def __init__(self):
        self.active = True
        self.user = {
            "id": 41, "username": "socket-user", "role": "user",
            "is_active": True, "created_at": 0,
        }

    def has_active_users(self):
        return False

    def verify_user_token(self, token):
        if token != "user-token" or not self.active:
            return None
        return dict(self.user)


def _app(*, guest=False):
    runtime = _Runtime()
    lan = _Lan(runtime)

    @web.middleware
    async def auth(request, handler):
        kind = "guest" if guest else "local_ui"
        set_request_principal(request, principal_for_request(kind), {})
        return await handler(request)

    app = web.Application(middlewares=[auth])
    app[LAN_APP_KEY] = lan
    setup_routes(app)
    return app, runtime, lan


def _user_cookie_app():
    runtime = _Runtime()
    lan = _Lan(runtime)

    @web.middleware
    async def auth(request, handler):
        token = request.cookies.get("lan_token")
        user = lan._auth_service.verify_user_token(token) if token else None
        if user is not None:
            set_request_principal(request, principal_for_request("user", user=user), {})
        return await handler(request)

    app = web.Application(middlewares=[auth])
    app[LAN_APP_KEY] = lan
    setup_routes(app)
    return app, runtime, lan


async def _client(app):
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


@pytest.mark.anyio
async def test_revision_returns_exact_runtime_cursor_for_authenticated_principal():
    app, runtime, _lan = _app()
    client = await _client(app)
    try:
        response = await client.get("/api/revision")
        assert response.status == 200
        assert await response.json() == {"epoch": runtime.epoch, "revision": runtime.revision}
    finally:
        await client.close()


@pytest.mark.anyio
async def test_websocket_sends_ready_then_exact_projection_invalidation_dto():
    app, runtime, _lan = _app()
    client = await _client(app)
    try:
        ws = await client.ws_connect("/ws")
        assert await ws.receive_json() == {
            "type": "runtime_ready", "epoch": "epoch-a", "revision": 7,
        }
        runtime.event_router.emit(_Event("epoch-a", 8, ("files", "tree"), ("a.txt",)))
        assert await ws.receive_json() == {
            "type": "projection_invalidated", "epoch": "epoch-a", "revision": 8,
            "domains": ["files", "tree"], "paths": ["a.txt"],
        }
        await ws.close()
    finally:
        await client.close()


@pytest.mark.anyio
async def test_websocket_preserves_tags_projection_domain():
    app, runtime, _lan = _app()
    client = await _client(app)
    try:
        ws = await client.ws_connect("/ws")
        assert await ws.receive_json() == {
            "type": "runtime_ready",
            "epoch": "epoch-a",
            "revision": 7,
        }
        runtime.event_router.emit(_Event("epoch-a", 8, ("tags",), ()))
        assert await ws.receive_json() == {
            "type": "projection_invalidated",
            "epoch": "epoch-a",
            "revision": 8,
            "domains": ["tags"],
            "paths": [],
        }
        await ws.close()
    finally:
        await client.close()


@pytest.mark.anyio
async def test_revoked_user_websocket_is_closed_before_runtime_invalidation_delivery():
    app, runtime, lan = _user_cookie_app()
    client = await _client(app)
    try:
        ws = await client.ws_connect(
            "/ws", headers={"Cookie": "lan_token=user-token"},
        )
        assert await ws.receive_json() == {
            "type": "runtime_ready", "epoch": "epoch-a", "revision": 7,
        }
        assert len(lan.ws_manager._clients) == 1
        assert [entry["user_id"] for entry in lan.services.online_users.list_all()] == ["41"]

        lan._auth_service.active = False
        runtime.event_router.emit(
            _Event("epoch-a", 8, ("files",), ("revoked-secret.txt",)),
        )

        message = await asyncio.wait_for(ws.receive(), timeout=1)
        assert message.type in {web.WSMsgType.CLOSE, web.WSMsgType.CLOSED}
        await asyncio.sleep(0)
        assert not lan.ws_manager._clients
        assert lan.services.online_users.list_all() == []
    finally:
        await client.close()


@pytest.mark.anyio
async def test_user_revocation_before_lease_add_rejects_websocket_admission(
        monkeypatch):
    original_send_json = web.WebSocketResponse.send_json
    ready_send_started = asyncio.Event()
    release_ready_send = asyncio.Event()

    async def pause_runtime_ready(self, payload, *args, **kwargs):
        if payload.get("type") == "runtime_ready":
            ready_send_started.set()
            await release_ready_send.wait()
        return await original_send_json(self, payload, *args, **kwargs)

    monkeypatch.setattr(web.WebSocketResponse, "send_json", pause_runtime_ready)
    app, runtime, lan = _user_cookie_app()
    original_add = lan.ws_manager.add
    add_results = []
    add_completed = asyncio.Event()

    async def observe_add(*args, **kwargs):
        result = await original_add(*args, **kwargs)
        add_results.append(result)
        add_completed.set()
        return result

    monkeypatch.setattr(lan.ws_manager, "add", observe_add)
    client = await _client(app)
    try:
        connect = asyncio.create_task(client.ws_connect(
            "/ws", headers={"Cookie": "lan_token=user-token"},
        ))
        await asyncio.wait_for(ready_send_started.wait(), timeout=1)
        assert not lan.ws_manager._clients

        def revoke_user():
            lan._auth_service.active = False
            return True

        assert await lan.ws_manager.revoke_authority(
            ("user", 41), revoke_user,
        ) is True
        release_ready_send.set()

        ws = await connect
        assert await ws.receive_json() == {
            "type": "runtime_ready", "epoch": "epoch-a", "revision": 7,
        }
        message = await asyncio.wait_for(ws.receive(), timeout=1)
        assert message.type in {web.WSMsgType.CLOSE, web.WSMsgType.CLOSED}
        await asyncio.wait_for(add_completed.wait(), timeout=1)
        assert add_results == [False]
        assert not lan.ws_manager._clients
        assert lan.services.online_users.list_all() == []

        runtime.event_router.emit(
            _Event("epoch-a", 8, ("files",), ("revoked-admission.txt",)),
        )
        assert not lan.ws_manager._clients
    finally:
        release_ready_send.set()
        await client.close()


@pytest.mark.anyio
@pytest.mark.parametrize("outcome", ["accepted", "revoked", "over_limit"])
async def test_websocket_presence_is_published_only_after_admission_transition(
        monkeypatch, outcome):
    app, _runtime, lan = _user_cookie_app()
    authority = ("user", 41)
    authority_lock = lan.ws_manager._authority_locks.setdefault(
        authority, asyncio.Lock(),
    )
    await authority_lock.acquire()
    original_add = lan.ws_manager.add
    add_completed = asyncio.Event()
    add_results = []

    async def observe_add(*args, **kwargs):
        result = await original_add(*args, **kwargs)
        add_results.append(result)
        add_completed.set()
        return result

    monkeypatch.setattr(lan.ws_manager, "add", observe_add)
    client = await _client(app)
    ws = None
    try:
        ws = await client.ws_connect(
            "/ws", headers={"Cookie": "lan_token=user-token"},
        )
        assert await ws.receive_json() == {
            "type": "runtime_ready", "epoch": "epoch-a", "revision": 7,
        }
        await asyncio.sleep(0)
        assert not add_completed.is_set()
        assert not lan.ws_manager._clients
        assert lan.services.online_users.list_all() == []

        if outcome == "revoked":
            lan._auth_service.active = False
        elif outcome == "over_limit":
            monkeypatch.setattr("AssetsManager.lan.ws.MAX_WS_CONNECTIONS", 0)
        authority_lock.release()

        if outcome != "accepted":
            message = await asyncio.wait_for(ws.receive(), timeout=1)
            assert message.type in {web.WSMsgType.CLOSE, web.WSMsgType.CLOSED}
            await asyncio.wait_for(add_completed.wait(), timeout=1)
            assert add_results == [False]
            assert lan.services.online_users.list_all() == []
        else:
            await asyncio.wait_for(add_completed.wait(), timeout=1)
            assert add_results == [True]
            assert [
                entry["user_id"]
                for entry in lan.services.online_users.list_all()
            ] == ["41"]
            await ws.close()
            for _ in range(10):
                if not lan.services.online_users.list_all():
                    break
                await asyncio.sleep(0)
            assert not lan.ws_manager._clients
            assert lan.services.online_users.list_all() == []
    finally:
        if authority_lock.locked():
            authority_lock.release()
        if ws is not None and not ws.closed:
            await ws.close()
        await client.close()


@pytest.mark.anyio
async def test_server_lifetime_revocation_before_lease_add_rejects_admission(
        monkeypatch):
    from AssetsManager.lan.auth import hash_key

    original_send_json = web.WebSocketResponse.send_json
    ready_send_started = asyncio.Event()
    release_ready_send = asyncio.Event()

    async def pause_runtime_ready(self, payload, *args, **kwargs):
        if payload.get("type") == "runtime_ready":
            ready_send_started.set()
            await release_ready_send.wait()
        return await original_send_json(self, payload, *args, **kwargs)

    monkeypatch.setattr(web.WebSocketResponse, "send_json", pause_runtime_ready)
    runtime = _Runtime()
    lan = _Lan(runtime)
    lan.access_key_hash = hash_key("access-secret")

    @web.middleware
    async def auth(request, handler):
        set_request_principal(request, principal_for_request("access_key"), {})
        return await handler(request)

    app = web.Application(middlewares=[auth])
    app[LAN_APP_KEY] = lan
    setup_routes(app)
    original_add = lan.ws_manager.add
    add_results = []
    add_completed = asyncio.Event()

    async def observe_add(*args, **kwargs):
        result = await original_add(*args, **kwargs)
        add_results.append(result)
        add_completed.set()
        return result

    monkeypatch.setattr(lan.ws_manager, "add", observe_add)
    client = await _client(app)
    try:
        connect = asyncio.create_task(client.ws_connect(
            "/ws", headers={"Authorization": "Bearer access-secret"},
        ))
        await asyncio.wait_for(ready_send_started.wait(), timeout=1)
        assert not lan.ws_manager._clients

        await lan.ws_manager.close_all()
        release_ready_send.set()

        ws = await connect
        assert await ws.receive_json() == {
            "type": "runtime_ready", "epoch": "epoch-a", "revision": 7,
        }
        message = await asyncio.wait_for(ws.receive(), timeout=1)
        assert message.type in {web.WSMsgType.CLOSE, web.WSMsgType.CLOSED}
        await asyncio.wait_for(add_completed.wait(), timeout=1)
        assert add_results == [False]
        assert not lan.ws_manager._clients

        runtime.event_router.emit(
            _Event("epoch-a", 8, ("files",), ("stale-server-secret.txt",)),
        )
        assert not lan.ws_manager._clients
    finally:
        release_ready_send.set()
        await client.close()


@pytest.mark.anyio
async def test_user_revocation_wins_after_broadcast_authorization_before_send(
        monkeypatch):
    manager = WebSocketManager()
    authorization_succeeded = asyncio.Event()
    release_broadcast = asyncio.Event()
    authority = ("user", 41)
    active = True

    class Socket:
        def __init__(self):
            self.messages = []
            self.closed = False

        async def send_str(self, message):
            self.messages.append(message)

        async def close(self, **_kwargs):
            self.closed = True

    socket = Socket()

    def authorize():
        return active

    await manager.add(socket, authorize=authorize, authority=authority)
    original_is_authorized = manager._is_authorized
    paused_once = False

    async def pause_after_authorization(ws):
        nonlocal paused_once
        result = await original_is_authorized(ws)
        if not paused_once:
            paused_once = True
            assert result is True
            authorization_succeeded.set()
            await release_broadcast.wait()
        return result

    monkeypatch.setattr(manager, "_is_authorized", pause_after_authorization)
    broadcast = asyncio.create_task(manager.broadcast(
        "projection_invalidated",
        {"epoch": "epoch-a", "revision": 8, "domains": ["files"]},
    ))
    await asyncio.wait_for(authorization_succeeded.wait(), timeout=1)

    def revoke_authority():
        nonlocal active
        active = False
        return True

    assert await manager.revoke_authority(authority, revoke_authority) is True
    release_broadcast.set()
    await asyncio.wait_for(broadcast, timeout=1)

    assert socket.messages == []
    assert socket.closed
    assert socket not in manager._clients


@pytest.mark.anyio
async def test_authority_revocation_wins_after_admission_authorization(
        monkeypatch):
    manager = WebSocketManager()
    authority = ("user", 41)
    authorization_completed = asyncio.Event()
    release_admission = asyncio.Event()
    active = True

    class Socket:
        def __init__(self):
            self.messages = []
            self.closed = False

        async def send_str(self, message):
            self.messages.append(message)

        async def close(self, **_kwargs):
            self.closed = True

    socket = Socket()

    def authorize():
        return active

    original_authorize = manager._authorize_for_authority

    async def pause_after_authorization(*args, **kwargs):
        result = await original_authorize(*args, **kwargs)
        authorization_completed.set()
        await release_admission.wait()
        return result

    monkeypatch.setattr(
        manager, "_authorize_for_authority", pause_after_authorization,
    )
    admission = asyncio.create_task(
        manager.add(socket, authorize=authorize, authority=authority),
    )
    await asyncio.wait_for(authorization_completed.wait(), timeout=1)

    def revoke_authority():
        nonlocal active
        active = False
        return True

    assert await manager.revoke_authority(authority, revoke_authority) is True
    release_admission.set()

    assert await asyncio.wait_for(admission, timeout=1) is False
    assert socket.closed
    assert socket not in manager._clients
    assert socket not in manager._leases

    await manager.broadcast(
        "projection_invalidated",
        {"epoch": "epoch-a", "revision": 8, "domains": ["files"]},
    )
    assert socket.messages == []


@pytest.mark.anyio
async def test_broadcast_truncates_oversized_paths_payload():
    """Oversized frames carrying a paths list are truncated, not dropped."""
    from AssetsManager.lan.ws import MAX_BROADCAST_FRAME_BYTES

    manager = WebSocketManager()

    class Socket:
        def __init__(self):
            self.messages = []
            self.closed = False

        async def send_str(self, message):
            self.messages.append(message)

        async def close(self, **_kwargs):
            self.closed = True

    socket = Socket()
    assert await manager.add(socket)

    prefix = "C:/Assets/Library/Subfolder/" + "x" * 96
    paths = tuple(f"{prefix}/{i:05d}" for i in range(20000))
    assert sum(len(p) for p in paths) > MAX_BROADCAST_FRAME_BYTES

    await manager.broadcast(
        "projection_invalidated",
        {"epoch": "epoch-a", "revision": 8, "domains": ["files"], "paths": paths},
    )

    assert len(socket.messages) == 1
    payload = json.loads(socket.messages[0])
    assert payload["type"] == "projection_invalidated"
    assert payload["epoch"] == "epoch-a"
    assert 0 < len(payload["paths"]) < len(paths)
    assert payload["paths"] == list(paths[:len(payload["paths"])])
    assert len(json.dumps(payload).encode("utf-8")) <= MAX_BROADCAST_FRAME_BYTES
    assert manager.truncated_broadcast_frames == 1
    assert manager.dropped_broadcast_frames == 0
    assert socket.closed is False


@pytest.mark.anyio
async def test_broadcast_drops_oversized_payload_without_paths():
    """Oversized frames without a trimmable paths list are counted + dropped."""
    manager = WebSocketManager()

    class Socket:
        def __init__(self):
            self.messages = []
            self.closed = False

        async def send_str(self, message):
            self.messages.append(message)

        async def close(self, **_kwargs):
            self.closed = True

    socket = Socket()
    assert await manager.add(socket)

    await manager.broadcast(
        "projection_invalidated",
        {"epoch": "epoch-a", "revision": 8, "domains": ["files"],
         "blob": "y" * (2 * 1024 * 1024)},
    )

    assert socket.messages == []
    assert manager.dropped_broadcast_frames == 1
    assert manager.truncated_broadcast_frames == 0
    assert socket.closed is False


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("kind", "token", "authority"),
    (
        ("access_key", "access-secret", ("access_key",)),
        ("password", "password-secret", ("password",)),
        ("local_ui", "local-secret", ("local_ui",)),
    ),
)
async def test_credential_revocation_wins_after_validation_before_send(
        monkeypatch, kind, token, authority):
    """Server teardown invalidates each process-bound credential lease."""
    from AssetsManager.lan.auth import generate_token, hash_key, hash_password
    from AssetsManager.lan.utils import generate_auth_token

    manager = WebSocketManager()
    authorization_succeeded = asyncio.Event()
    release_broadcast = asyncio.Event()
    password_hash = hash_password(token) if kind == "password" else None
    lan = SimpleNamespace(
        access_key_hash=hash_key(token) if kind == "access_key" else None,
        password_hash=password_hash,
        local_ui_auth_secret=token if kind == "local_ui" else None,
        token_secret="wrong-secret" if kind == "local_ui" else None,
    )
    presented = (
        generate_auth_token(token) if kind == "local_ui"
        else generate_token(password_hash) if kind == "password"
        else token
    )
    request = SimpleNamespace(
        headers={"Authorization": f"Bearer {presented}"},
        cookies={},
        query={},
    )
    principal = principal_for_request(kind)

    class Socket:
        def __init__(self):
            self.messages = []
            self.closed = False

        async def send_str(self, message):
            self.messages.append(message)

        async def close(self, **_kwargs):
            self.closed = True

    socket = Socket()
    await manager.add(
        socket,
        authorize=_authorization_validator(request, lan, principal),
        authority=_authorization_authority(principal),
    )
    assert manager._leases[socket].authority == authority
    assert manager._leases[socket].lock is manager._authority_locks[authority]
    original_is_authorized = manager._is_authorized
    paused_once = False

    async def pause_after_authorization(ws):
        nonlocal paused_once
        result = await original_is_authorized(ws)
        if not paused_once:
            paused_once = True
            assert result is True
            authorization_succeeded.set()
            await release_broadcast.wait()
        return result

    monkeypatch.setattr(manager, "_is_authorized", pause_after_authorization)
    broadcast = asyncio.create_task(manager.broadcast(
        "projection_invalidated",
        {"epoch": "epoch-a", "revision": 8, "domains": ["files"]},
    ))
    await asyncio.wait_for(authorization_succeeded.wait(), timeout=1)

    teardown = asyncio.create_task(manager.close_all())
    await asyncio.sleep(0)
    rejected = Socket()
    assert await manager.add(
        rejected,
        authorize=_authorization_validator(request, lan, principal),
        authority=_authorization_authority(principal),
    ) is False
    release_broadcast.set()
    await asyncio.wait_for(asyncio.gather(broadcast, teardown), timeout=1)

    assert socket.messages == []
    assert socket.closed
    assert rejected.closed
    assert socket not in manager._clients


@pytest.mark.anyio
async def test_logout_revokes_only_the_matching_websocket_token():
    manager = WebSocketManager()

    class Socket:
        def __init__(self):
            self.closed = False

        async def close(self, **_kwargs):
            self.closed = True

    first = Socket()
    second = Socket()
    assert await manager.add(
        first, authorize=lambda: True, authority=("access_key",),
        auth_token="token-a",
    )
    assert await manager.add(
        second, authorize=lambda: True, authority=("access_key",),
        auth_token="token-b",
    )

    assert await manager.revoke_auth_token("token-a") == 1
    assert first.closed is True
    assert second.closed is False
    assert first not in manager._clients
    assert second in manager._clients

    await manager.evict(second)


@pytest.mark.anyio
async def test_revision_and_realtime_reject_guest_capability():
    app, _runtime, _lan = _app(guest=True)
    client = await _client(app)
    try:
        assert (await client.get("/api/revision")).status == 403
        with pytest.raises(WSServerHandshakeError) as error:
            await client.ws_connect("/ws")
        assert error.value.status == 401
    finally:
        await client.close()


@pytest.mark.anyio
async def test_websocket_rejects_legacy_user_context_without_canonical_principal():
    runtime = _Runtime()
    lan = _Lan(runtime)

    @web.middleware
    async def legacy_auth(request, handler):
        return await handler(request)

    app = web.Application(middlewares=[legacy_auth])
    app[LAN_APP_KEY] = lan
    setup_routes(app)
    client = await _client(app)
    try:
        with pytest.raises(WSServerHandshakeError) as error:
            await client.ws_connect("/ws")
        assert error.value.status == 401
    finally:
        await client.close()


def test_runtime_invalidation_closes_broadcast_coroutine_when_submission_fails(monkeypatch):
    app, runtime, _lan = _app()
    submitted = []

    def fail_submission(coro, loop):
        submitted.append(coro)
        raise RuntimeError("loop race")

    monkeypatch.setattr("AssetsManager.lan.api.asyncio.run_coroutine_threadsafe", fail_submission)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        loop = asyncio.new_event_loop()
        try:
            app.freeze()
            loop.run_until_complete(app.startup())
            original_is_running = loop.is_running
            monkeypatch.setattr(loop, "is_running", lambda: True)
            try:
                runtime.event_router.emit(_Event("epoch-a", 8, ("files",), ("a.txt",)))
            finally:
                monkeypatch.setattr(loop, "is_running", original_is_running)
            gc.collect()
        finally:
            loop.run_until_complete(app.cleanup())
            loop.close()

    assert len(submitted) == 1
    assert submitted[0].cr_frame is None
    assert not [warning for warning in caught if "never awaited" in str(warning.message)]


def test_runtime_invalidation_consumes_cancelled_broadcast_future(monkeypatch, caplog):
    app, runtime, _lan = _app()

    class CancelledFuture(concurrent.futures.Future):
        def add_done_callback(self, callback):
            loop.call_soon(callback, self)

        def result(self, timeout=None):
            raise asyncio.CancelledError

    cancelled = CancelledFuture()
    cancelled.cancel()

    def submit(coro, loop):
        coro.close()
        return cancelled

    monkeypatch.setattr("AssetsManager.lan.api.asyncio.run_coroutine_threadsafe", submit)
    loop = asyncio.new_event_loop()
    loop_errors = []
    loop.set_exception_handler(lambda _loop, context: loop_errors.append(context))
    try:
        app.freeze()
        loop.run_until_complete(app.startup())
        original_is_running = loop.is_running
        monkeypatch.setattr(loop, "is_running", lambda: True)
        try:
            with caplog.at_level(logging.ERROR):
                runtime.event_router.emit(_Event("epoch-a", 8, ("files",), ("a.txt",)))
        finally:
            monkeypatch.setattr(loop, "is_running", original_is_running)
        loop.run_until_complete(asyncio.sleep(0))
    finally:
        loop.run_until_complete(app.cleanup())
        loop.close()

    assert not loop_errors
    assert not [record for record in caplog.records if record.exc_info]


def test_runtime_invalidation_consumes_base_exception_broadcast_future(monkeypatch, caplog):
    app, runtime, _lan = _app()

    class FailedFuture(concurrent.futures.Future):
        def add_done_callback(self, callback):
            loop.call_soon(callback, self)

        def result(self, timeout=None):
            raise SystemExit("broadcast failed")

    failed = FailedFuture()
    failed.set_result(None)

    def submit(coro, loop):
        coro.close()
        return failed

    monkeypatch.setattr("AssetsManager.lan.api.asyncio.run_coroutine_threadsafe", submit)
    loop = asyncio.new_event_loop()
    loop_errors = []
    loop.set_exception_handler(lambda _loop, context: loop_errors.append(context))
    try:
        app.freeze()
        loop.run_until_complete(app.startup())
        original_is_running = loop.is_running
        monkeypatch.setattr(loop, "is_running", lambda: True)
        try:
            with caplog.at_level(logging.ERROR):
                runtime.event_router.emit(_Event("epoch-a", 8, ("files",), ("a.txt",)))
        finally:
            monkeypatch.setattr(loop, "is_running", original_is_running)
        loop.run_until_complete(asyncio.sleep(0))
    finally:
        loop.run_until_complete(app.cleanup())
        loop.close()

    assert not loop_errors
    assert not [record for record in caplog.records if record.exc_info]


@pytest.mark.anyio
async def test_websocket_admission_sends_runtime_ready_before_registration_invalidation(
        monkeypatch):
    from AssetsManager.lan.routes import websocket as websocket_route

    class FakeWebSocket:
        def __init__(self, **kwargs):
            self.messages = []

        async def prepare(self, request):
            return self

        async def send_json(self, payload):
            self.messages.append(payload)

        async def send_str(self, payload):
            self.messages.append(payload)

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class BoundaryManager:
        def __init__(self):
            self.client = None

        async def add(self, ws, **kwargs):
            self.client = ws
            await ws.send_str("projection_invalidated")
            return True

        async def remove(self, ws):
            self.client = None

    class FakeRequest:
        query = {}
        headers = {}
        cookies = {}
        remote = "127.0.0.1"

    manager = BoundaryManager()
    lan = type("Lan", (), {
        "ws_manager": manager,
        "runtime": type("Runtime", (), {"epoch": "e", "revision": 1})(),
    })()
    socket = FakeWebSocket()
    monkeypatch.setattr(
        websocket_route.web, "WebSocketResponse", lambda **kwargs: socket,
    )
    monkeypatch.setattr(websocket_route, "get_lan", lambda request: lan)
    monkeypatch.setattr(
        websocket_route,
        "get_request_principal",
        lambda request: principal_for_request("local_ui"),
    )

    await websocket_route.handle_websocket(FakeRequest())

    assert socket.messages == [
        {"type": "runtime_ready", "epoch": "e", "revision": 1},
        "projection_invalidated",
    ]


@pytest.mark.anyio
async def test_websocket_admission_recovers_invalidation_while_ready_send_is_paused(
        monkeypatch):
    original_send_json = web.WebSocketResponse.send_json
    ready_send_started = asyncio.Event()
    release_ready_send = asyncio.Event()
    broadcast_snapshot_completed = asyncio.Event()
    paused_once = False

    async def pause_first_runtime_ready(self, payload, *args, **kwargs):
        nonlocal paused_once
        if payload.get("type") == "runtime_ready" and not paused_once:
            paused_once = True
            ready_send_started.set()
            await release_ready_send.wait()
        return await original_send_json(self, payload, *args, **kwargs)

    monkeypatch.setattr(web.WebSocketResponse, "send_json", pause_first_runtime_ready)
    app, runtime, lan = _app()
    original_broadcast = lan.ws_manager.broadcast

    async def observe_broadcast_snapshot(*args, **kwargs):
        await original_broadcast(*args, **kwargs)
        broadcast_snapshot_completed.set()

    monkeypatch.setattr(lan.ws_manager, "broadcast", observe_broadcast_snapshot)
    client = await _client(app)
    try:
        connect = asyncio.create_task(client.ws_connect("/ws"))
        await asyncio.wait_for(ready_send_started.wait(), timeout=1)

        runtime.revision = 8
        runtime.event_router.emit(
            _Event("epoch-a", 8, ("files",), ("admission-race.txt",)),
        )
        # Do not admit the socket until the real manager's broadcast has
        # completed its client snapshot with no registered clients. This
        # distinguishes cursor reconciliation from post-add event delivery.
        await asyncio.wait_for(broadcast_snapshot_completed.wait(), timeout=1)
        assert not lan.ws_manager._clients
        release_ready_send.set()

        ws = await connect
        assert await ws.receive_json() == {
            "type": "runtime_ready", "epoch": "epoch-a", "revision": 7,
        }
        assert await asyncio.wait_for(ws.receive_json(), timeout=1) == {
            "type": "runtime_ready", "epoch": "epoch-a", "revision": 8,
        }
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(ws.receive_json(), timeout=0.05)
        await ws.close()
    finally:
        release_ready_send.set()
        await client.close()


@pytest.mark.anyio
async def test_websocket_admission_serializes_post_add_baseline_before_broadcast(
        monkeypatch):
    app, runtime, lan = _app()
    client = await _client(app)
    add_returned = asyncio.Event()
    release_admission = asyncio.Event()
    broadcast_started = asyncio.Event()
    broadcast_completed = asyncio.Event()
    original_add = lan.ws_manager.add
    original_broadcast = lan.ws_manager.broadcast

    async def pause_after_add(*args, **kwargs):
        result = await original_add(*args, **kwargs)
        add_returned.set()
        await release_admission.wait()
        return result

    async def observe_broadcast(*args, **kwargs):
        broadcast_started.set()
        result = await original_broadcast(*args, **kwargs)
        broadcast_completed.set()
        return result

    monkeypatch.setattr(lan.ws_manager, "add", pause_after_add)
    monkeypatch.setattr(lan.ws_manager, "broadcast", observe_broadcast)
    try:
        connect = asyncio.create_task(client.ws_connect("/ws"))
        await asyncio.wait_for(add_returned.wait(), timeout=1)

        runtime.revision = 8
        runtime.event_router.emit(
            _Event("epoch-a", 8, ("files",), ("post-add-race.txt",)),
        )
        await asyncio.wait_for(broadcast_started.wait(), timeout=1)
        assert not broadcast_completed.is_set()
        release_admission.set()
        await asyncio.wait_for(broadcast_completed.wait(), timeout=1)
        ws = await connect

        messages = [
            await asyncio.wait_for(ws.receive_json(), timeout=1)
            for _ in range(3)
        ]
        assert [message["type"] for message in messages] == [
            "runtime_ready", "runtime_ready", "projection_invalidated",
        ]
        assert messages[1] == {
            "type": "runtime_ready", "epoch": "epoch-a", "revision": 8,
        }
        await ws.close()
    finally:
        release_admission.set()
        await client.close()


@pytest.mark.anyio
async def test_websocket_rejects_runtime_missing_before_registration(monkeypatch):
    from AssetsManager.lan.routes import websocket as websocket_route

    class FakeWebSocket:
        def __init__(self):
            self.prepared = False
            self.close_kwargs = None

        async def prepare(self, request):
            self.prepared = True
            return self

        async def close(self, **kwargs):
            self.close_kwargs = kwargs
            raise ConnectionResetError("close failed")

    class FakeManager:
        def __init__(self):
            self.added = []
            self.removed = []

        async def add(self, ws, **kwargs):
            self.added.append(ws)
            return True

        async def remove(self, ws):
            self.removed.append(ws)

    class FakeRequest:
        query = {}
        headers = {}
        cookies = {}

    socket = FakeWebSocket()
    manager = FakeManager()
    lan = type("Lan", (), {"ws_manager": manager, "runtime": None})()
    monkeypatch.setattr(
        websocket_route.web, "WebSocketResponse", lambda **kwargs: socket,
    )
    monkeypatch.setattr(websocket_route, "get_lan", lambda request: lan)
    monkeypatch.setattr(
        websocket_route,
        "get_request_principal",
        lambda request: principal_for_request("local_ui"),
    )

    result = await websocket_route.handle_websocket(FakeRequest())

    assert result is socket
    assert socket.prepared
    assert manager.removed == [socket]
    assert manager.added == []
    assert socket.close_kwargs == {"code": 1013, "message": b"Runtime unavailable"}


@pytest.mark.anyio
async def test_websocket_removes_client_when_initial_ready_send_fails(monkeypatch):
    from AssetsManager.lan.routes import websocket as websocket_route

    class FakeWebSocket:
        def __init__(self, **kwargs):
            self.closed = False

        async def prepare(self, request):
            return self

        async def send_json(self, payload):
            raise ConnectionResetError("peer disconnected")

        async def close(self):
            self.closed = True
            raise ConnectionResetError("close failed")

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class FakeManager:
        def __init__(self):
            self.clients = set()
            self.added = []
            self.removed = []

        async def add(self, ws, **kwargs):
            self.clients.add(ws)
            self.added.append(ws)
            return True

        async def remove(self, ws):
            self.removed.append(ws)
            self.clients.discard(ws)

    class FakeRequest:
        query = {}

    manager = FakeManager()
    lan = type("Lan", (), {
        "ws_manager": manager,
        "runtime": type("Runtime", (), {"epoch": "e", "revision": 1})(),
    })()
    monkeypatch.setattr(websocket_route.web, "WebSocketResponse", FakeWebSocket)
    monkeypatch.setattr(websocket_route, "get_lan", lambda request: lan)
    monkeypatch.setattr(
        websocket_route,
        "get_request_principal",
        lambda request: principal_for_request("local_ui"),
    )

    socket = FakeWebSocket()
    monkeypatch.setattr(
        websocket_route.web, "WebSocketResponse", lambda **kwargs: socket,
    )

    result = await websocket_route.handle_websocket(FakeRequest())

    assert result is socket
    assert not manager.added
    assert manager.removed == [socket]
    assert not manager.clients
    assert socket.closed


@pytest.mark.anyio
async def test_websocket_reconciliation_failure_removes_client_when_close_fails(
        monkeypatch):
    from AssetsManager.lan.routes import websocket as websocket_route

    class FakeWebSocket:
        def __init__(self):
            self.send_count = 0
            self.close_attempted = False

        async def prepare(self, request):
            return self

        async def send_json(self, payload):
            self.send_count += 1
            if self.send_count == 2:
                raise ConnectionResetError("reconciliation send failed")

        async def close(self):
            self.close_attempted = True
            raise ConnectionResetError("close failed")

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class FakeManager:
        def __init__(self, runtime):
            self.runtime = runtime
            self.clients = set()
            self.removed = []

        async def add(self, ws, **kwargs):
            self.clients.add(ws)
            self.runtime.revision += 1
            return True

        async def remove(self, ws):
            self.removed.append(ws)
            self.clients.discard(ws)

    class FakeRequest:
        query = {}
        headers = {}
        cookies = {}

    runtime = type("Runtime", (), {"epoch": "e", "revision": 1})()
    manager = FakeManager(runtime)
    lan = type("Lan", (), {"ws_manager": manager, "runtime": runtime})()
    socket = FakeWebSocket()
    monkeypatch.setattr(
        websocket_route.web, "WebSocketResponse", lambda **kwargs: socket,
    )
    monkeypatch.setattr(websocket_route, "get_lan", lambda request: lan)
    monkeypatch.setattr(
        websocket_route,
        "get_request_principal",
        lambda request: principal_for_request("local_ui"),
    )

    result = await websocket_route.handle_websocket(FakeRequest())

    assert result is socket
    assert socket.send_count == 2
    assert socket.close_attempted
    assert manager.removed == [socket]
    assert not manager.clients


@pytest.mark.anyio
async def test_wrong_session_event_is_silent():
    app, runtime, _lan = _app()
    client = await _client(app)
    try:
        ws = await client.ws_connect("/ws")
        await ws.receive_json()
        runtime.event_router.emit(_Event("other-epoch", 99, ("files",), ("secret.txt",)))
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(ws.receive(), timeout=0.05)
        await ws.close()
    finally:
        await client.close()


@pytest.mark.anyio
async def test_disconnect_unsubscribes_and_server_cleanup_closes_clients():
    app, runtime, lan = _app()
    client = await _client(app)
    ws = await client.ws_connect("/ws")
    await ws.receive_json()
    assert len(runtime.event_router.subscriptions) == 1
    await ws.close()
    await asyncio.sleep(0)
    assert len(runtime.event_router.subscriptions) == 1
    ws2 = await client.ws_connect("/ws")
    await ws2.receive_json()
    assert len(runtime.event_router.subscriptions) == 1
    await lan.ws_manager.close_all()
    await asyncio.sleep(0)
    await app.cleanup()
    assert not runtime.event_router.subscriptions
    await client.close()


@pytest.mark.anyio
async def test_same_root_reopen_does_not_deliver_old_runtime_event(tmp_path):
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.domain.events import FileSystemChanged

    bootstrap = ApplicationBootstrap()
    first_session = bootstrap.library_service.open_session(tmp_path)
    first_runtime = bootstrap.runtime_for(first_session)
    first_epoch = first_runtime.epoch
    first_token = first_session.event_token
    first_runtime.close()
    first_session.close()
    second_session = bootstrap.library_service.open_session(tmp_path)
    second_runtime = bootstrap.runtime_for(second_session)
    assert second_runtime.epoch != first_epoch
    assert second_runtime.revision == 0

    lan = _Lan(second_runtime)
    @web.middleware
    async def auth(request, handler):
        set_request_principal(request, principal_for_request("local_ui"), {})
        return await handler(request)

    app = web.Application(middlewares=[auth])
    app[LAN_APP_KEY] = lan
    setup_routes(app)
    client = await _client(app)
    try:
        ws = await client.ws_connect("/ws")
        assert await ws.receive_json() == {
            "type": "runtime_ready", "epoch": second_runtime.epoch, "revision": 0,
        }

        get_event_bus().publish(FileSystemChanged(
            library_root=str(tmp_path), session_token=first_token,
            paths=("old.txt",),
        ))
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(ws.receive(), timeout=0.05)
        await ws.close()
    finally:
        await client.close()
        second_session.close()
        bootstrap.library_service.close()


@pytest.mark.anyio
async def test_real_library_close_session_stops_lan_server_and_websocket(
        tmp_path):
    """Closing the owning session tears down the real LAN runtime boundary."""
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.lan.server import _LanServerImpl
    from AssetsManager.lan.auth import generate_token

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)
    server = _LanServerImpl(runtime=runtime, password="test-password")
    client = None
    ws = None
    close_future = None
    cleanup_error = None
    pending_sync_cleanups = {}
    stop_calls = []
    lifecycle_order = []
    close_session_calls = []
    original_close_session = bootstrap.library_service.close_session

    def observe_close_session(close_session):
        close_session_calls.append(close_session)
        return original_close_session(close_session)

    async def run_sync_cleanup(key, function, *args):
        nonlocal cleanup_error
        pending = pending_sync_cleanups.get(key)
        if pending is None:
            pending = {
                "completed": threading.Event(),
                "error": None,
                "result": None,
            }
            pending_sync_cleanups[key] = pending

            def worker():
                try:
                    pending["result"] = function(*args)
                except BaseException as exc:
                    pending["error"] = exc
                finally:
                    pending["completed"].set()

            threading.Thread(target=worker, daemon=True).start()

        deadline = asyncio.get_running_loop().time() + 8
        while not pending["completed"].is_set():
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                if cleanup_error is None:
                    cleanup_error = TimeoutError(
                        f"timed out waiting for {function.__name__} cleanup"
                    )
                return
            await asyncio.sleep(min(0.01, remaining))

        error = pending["error"]
        result = pending["result"]
        pending_sync_cleanups.pop(key, None)
        if error is not None:
            raise error
        return result

    async def cleanup(awaitable):
        nonlocal cleanup_error
        try:
            await asyncio.wait_for(awaitable, timeout=8)
        except Exception as exc:
            if cleanup_error is None:
                cleanup_error = exc

    original_stop = server.stop

    def observe_stop():
        stop_calls.append("stop")
        lifecycle_order.append("stop")
        result = original_stop()
        return result

    server.stop = observe_stop

    try:
        from AssetsManager.application.security_preflight import SecurityPreflight
        preflight = SecurityPreflight()
        preflight.confirm_authenticated_lan()
        server.start(port=0, bind="127.0.0.1", preflight=preflight)
        initial_revision = runtime.revision
        client = ClientSession()
        ws = await client.ws_connect(
            f"http://127.0.0.1:{server._port}/ws",
            headers={
                "Authorization": (
                    f"Bearer {generate_token(server.password_hash)}"
                ),
            },
        )
        assert await ws.receive_json() == {
            "type": "runtime_ready",
            "epoch": runtime.epoch,
            "revision": initial_revision,
        }
        admission_deadline = asyncio.get_running_loop().time() + 2
        while len(server._ws_manager._clients) != 1:
            assert asyncio.get_running_loop().time() < admission_deadline
            await asyncio.sleep(0.01)
        assert server._runtime_subscription is not None
        assert server in runtime._lifecycle_adapters

        lifecycle_order.append("close_session_started")
        close_future = asyncio.create_task(run_sync_cleanup(
            "session",
            observe_close_session, session,
        ))
        deadline = asyncio.get_running_loop().time() + 8
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            assert remaining > 0
            message = await asyncio.wait_for(ws.receive(), timeout=remaining)
            if message.type in {WSMsgType.CLOSE, WSMsgType.CLOSED}:
                break
            assert message.type is WSMsgType.TEXT
        await close_future
        lifecycle_order.append("close_session_returned")

        assert server._lifecycle_state == "stopped"
        assert not server.is_running()
        assert not server._thread
        assert not server._ws_manager._clients
        assert server._runtime_subscription is None
        assert not runtime.event_router._event_subscriptions
        assert not runtime._lifecycle_adapters
        assert session.is_closed
        assert stop_calls == ["stop"]
        assert lifecycle_order.index("close_session_started") < lifecycle_order.index(
            "stop",
        ) < lifecycle_order.index("close_session_returned")

        # Both the service close path and finalizers remain bounded and idempotent.
        await run_sync_cleanup(
            "session",
            observe_close_session, session,
        )
        assert close_session_calls == [session, session]
        assert not server._thread
        assert not server._ws_manager._clients
    finally:
        if close_future is not None and not close_future.done():
            try:
                await asyncio.wait_for(asyncio.shield(close_future), timeout=8)
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError as exc:
                if cleanup_error is None:
                    cleanup_error = exc
            except Exception as exc:
                if cleanup_error is None:
                    cleanup_error = exc
        if ws is not None and not ws.closed:
            await cleanup(ws.close())
        if client is not None:
            await cleanup(client.close())
        if not session.is_closed:
            await cleanup(run_sync_cleanup(
                "session",
                observe_close_session, session,
            ))
        if server._thread is not None or server.is_running():
            await cleanup(run_sync_cleanup("server", server.stop))
        await cleanup(run_sync_cleanup(
            "service", bootstrap.library_service.close,
        ))
        if cleanup_error is not None:
            raise cleanup_error


def test_shutdown_race_does_not_schedule_after_realtime_unsubscribe(monkeypatch):
    app, runtime, lan = _app()
    scheduled = []

    def submit(coro, loop):
        scheduled.append(coro)
        coro.close()
        return concurrent.futures.Future()

    monkeypatch.setattr("AssetsManager.lan.api.asyncio.run_coroutine_threadsafe", submit)
    loop = asyncio.new_event_loop()
    try:
        app.freeze()
        loop.run_until_complete(app.startup())
        assert len(runtime.event_router.subscriptions) == 1
        subscription = runtime.event_router.subscriptions[0]
        callback = subscription.callback
        loop.run_until_complete(app.cleanup())
        assert len(runtime.event_router.subscriptions) == 0

        monkeypatch.setattr(loop, "is_running", lambda: True)
        callback(_Event("epoch-a", 8, ("files",), ("race.txt",)))
        assert scheduled == []
        assert lan._runtime_subscription is None
    finally:
        monkeypatch.undo()
        loop.close()


def test_cleanup_closes_gate_between_callback_check_and_submission(monkeypatch):
    app, runtime, lan = _app()
    checked = threading.Barrier(2)
    released = threading.Barrier(2)
    submitted = []

    def submit(coro, loop):
        submitted.append(coro)
        coro.close()
        return concurrent.futures.Future()

    monkeypatch.setattr("AssetsManager.lan.api.asyncio.run_coroutine_threadsafe", submit)
    loop = asyncio.new_event_loop()
    original_is_running = loop.is_running

    def is_running():
        checked.wait()
        released.wait()
        return True

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        try:
            app.freeze()
            loop.run_until_complete(app.startup())
            monkeypatch.setattr(loop, "is_running", is_running)
            callback = runtime.event_router.subscriptions[0].callback
            callback_thread = threading.Thread(
                target=callback,
                args=(_Event("epoch-a", 8, ("files",), ("race.txt",)),),
            )
            callback_thread.start()
            checked.wait()
            monkeypatch.setattr(loop, "is_running", original_is_running)
            loop.run_until_complete(app.cleanup())
            released.wait()
            callback_thread.join(timeout=1)
        finally:
            monkeypatch.setattr(loop, "is_running", original_is_running)
            if not loop.is_closed():
                loop.close()

    assert not callback_thread.is_alive()
    assert submitted == []
    assert not [warning for warning in caught if "never awaited" in str(warning.message)]


def test_real_server_shutdown_closes_realtime_gate_before_transport_shutdown(monkeypatch):
    from AssetsManager.lan.server import _LanServerImpl

    app, runtime, _lan = _app()
    server = object.__new__(_LanServerImpl)
    server.runtime = runtime
    server._ws_manager = _lan.ws_manager
    server._running = True
    server._site = None
    server._runner = None
    server._runtime_subscription = None
    app[LAN_APP_KEY] = server

    checked = threading.Barrier(2)
    released = threading.Barrier(2)
    scheduled = []
    shutdown_started = threading.Event()

    def submit(coro, loop):
        scheduled.append(coro)
        coro.close()
        return concurrent.futures.Future()

    monkeypatch.setattr("AssetsManager.lan.api.asyncio.run_coroutine_threadsafe", submit)
    loop = asyncio.new_event_loop()
    original_is_running = loop.is_running

    def is_running():
        checked.wait()
        released.wait()
        return True

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        try:
            app.freeze()
            loop.run_until_complete(app.startup())
            server._runtime_subscription = runtime.event_router.subscriptions[0]
            callback = runtime.event_router.subscriptions[0].callback
            monkeypatch.setattr(loop, "is_running", is_running)
            callback_thread = threading.Thread(
                target=callback,
                args=(_Event("epoch-a", 8, ("files",), ("race.txt",)),),
            )
            callback_thread.start()
            checked.wait()

            monkeypatch.setattr(loop, "is_running", original_is_running)
            shutdown = loop.create_task(_LanServerImpl._shutdown(server))
            shutdown_started.set()
            # Give shutdown a chance to enter before releasing the callback.
            loop.run_until_complete(asyncio.sleep(0))
            released.wait()
            loop.run_until_complete(shutdown)
            callback_thread.join(timeout=1)
        finally:
            monkeypatch.setattr(loop, "is_running", original_is_running)
            if not loop.is_closed():
                loop.close()

    assert shutdown_started.is_set()
    assert not callback_thread.is_alive()
    assert scheduled == []
    assert server._runtime_subscription is None
    assert not [warning for warning in caught if "never awaited" in str(warning.message)]
