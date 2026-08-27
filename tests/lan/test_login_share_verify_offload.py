"""Login / register / share-password verification must not block the loop.

Each handler wraps its PBKDF2-heavy service call in ``asyncio.to_thread``.
These regressions prove the *routing* (recording fake) plus liveness while
the verification is parked: a bystander task scheduled before the handler
only ticks after the parked fake signals ``started``, so a synchronous
regression fails fast on an empty call list instead of hanging, and the
passing path sleeps nowhere.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from AssetsManager.lan.routes._helpers import LAN_APP_KEY, PRINCIPAL_REQUEST_KEY
import AssetsManager.lan.routes.auth as auth_routes
import AssetsManager.lan.routes.shares as shares_routes


def pytest_configure(config):
    config.addinivalue_line("markers", "anyio: run test using anyio")


def pytest_generate_tests(metafunc):
    if "anyio_backend" in metafunc.fixturenames:
        metafunc.parametrize("anyio_backend", ["asyncio"])


class _ParkedOffload:
    """Recording ``to_thread`` fake that parks until the test releases it."""

    def __init__(self):
        self.calls: list[tuple[object, tuple, dict]] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.ticks = 0

    async def __call__(self, function, *args, **kwargs):
        self.calls.append((function, args, kwargs))
        self.started.set()
        await self.release.wait()
        return function(*args, **kwargs)

    async def run_with_bystander(self, awaitable, *, timeout=2.0):
        async def bystander():
            await self.started.wait()
            self.ticks += 1
            self.release.set()

        task = asyncio.create_task(bystander())
        try:
            response = await asyncio.wait_for(awaitable, timeout)
            assert self.calls, "crypto ran synchronously on the event loop"
            await asyncio.wait_for(task, timeout)
        finally:
            self.release.set()
            task.cancel()
        assert self.ticks >= 1, "event loop was blocked for the whole call"
        return response


def _lan(*, auth_service=None, share_service=None, activity_log=None, **attributes):
    services = SimpleNamespace(
        activity_log=activity_log,
        auth_service=auth_service,
        share_service=share_service,
    )
    base = {"ssl_active": False, "password_hash": None}
    base.update(attributes)
    return SimpleNamespace(services=services, **base)


def _post_request(app, path, body):
    request = make_mocked_request("POST", path, app=app)
    request.json = AsyncMock(return_value=body)
    return request


_USER_RECORD = {
    "id": 7,
    "username": "alice",
    "role": "user",
    "active": True,
    "created_at": 0.0,
}


@pytest.mark.anyio
async def test_password_mode_login_offloads_pbkdf2(monkeypatch):
    harness = _ParkedOffload()
    monkeypatch.setattr(auth_routes.asyncio, "to_thread", harness)
    auth_service = SimpleNamespace(
        verify_password=lambda password, password_hash: password == "p" and password_hash == "hash",
        generate_token=lambda password_hash: f"tok-{password_hash}",
    )
    lan = _lan(auth_service=auth_service, password_hash="hash")
    app = web.Application()
    app[LAN_APP_KEY] = lan

    response = await harness.run_with_bystander(
        auth_routes.handle_login(_post_request(app, "/api/auth/login", {"password": "p"}))
    )

    assert harness.calls == [(auth_service.verify_password, ("p", "hash"), {})]
    assert response.status == 200
    cookie = response.cookies["lan_token"]
    assert cookie["httponly"] is True
    assert cookie.value == "tok-hash"


@pytest.mark.anyio
async def test_login_activity_add_is_offloaded_after_verification(monkeypatch):
    """The activity-log commit must leave the loop like the PBKDF2 step."""

    class RecordingLog:
        def __init__(self):
            self.entries = []

        def add(self, username, action, details, ip=None):
            self.entries.append((username, action, details, ip))

    harness = _ParkedOffload()
    monkeypatch.setattr(auth_routes.asyncio, "to_thread", harness)
    auth_service = SimpleNamespace(
        verify_password=lambda password, password_hash: password == "p" and password_hash == "hash",
        generate_token=lambda password_hash: f"tok-{password_hash}",
    )
    activity_log = RecordingLog()
    lan = _lan(auth_service=auth_service, activity_log=activity_log, password_hash="hash")
    app = web.Application()
    app[LAN_APP_KEY] = lan

    response = await harness.run_with_bystander(
        auth_routes.handle_login(_post_request(app, "/api/auth/login", {"password": "p"}))
    )

    assert response.status == 200
    # First call: PBKDF2 verification. Second: the deferred activity add,
    # parked behind the same fake so the loop demonstrably stayed live.
    assert len(harness.calls) >= 2
    # The fake captures a fresh bound-method object per attribute access, so
    # identify the activity call by its receiver class instead of identity.
    def _is_activity_call(call):
        receiver = getattr(call[0], "__self__", None)
        return type(receiver).__name__ == "RecordingLog"

    add_calls = [c for c in harness.calls if _is_activity_call(c)]
    assert len(add_calls) == 1
    _fn, args, kwargs = add_calls[0]
    assert args == (None, "login", "signed in")
    assert kwargs.get("ip") is not None
    # The bystander released the parked verification step; the deferred add
    # then ran through to_thread as well, so it executed after parking and
    # recorded exactly one entry with the expected IP fallback.
    assert activity_log.entries == [(None, "login", "signed in", "unknown")]


@pytest.mark.anyio
async def test_user_mode_login_offloads_authentication(monkeypatch):
    harness = _ParkedOffload()
    monkeypatch.setattr(auth_routes.asyncio, "to_thread", harness)
    auth_service = SimpleNamespace(
        authenticate_user=lambda username, password: (_USER_RECORD, None),
        generate_user_token=lambda user_id, username, role: f"tok-{user_id}",
    )
    lan = _lan(auth_service=auth_service)
    app = web.Application()
    app[LAN_APP_KEY] = lan

    response = await harness.run_with_bystander(
        auth_routes.handle_login(
            _post_request(
                app,
                "/api/auth/login",
                {"username": "alice", "password": "pw"},
            )
        )
    )

    assert harness.calls == [(auth_service.authenticate_user, ("alice", "pw"), {})]
    assert response.status == 200
    assert response.cookies["lan_token"].value == "tok-7"


@pytest.mark.anyio
async def test_register_offloads_hash_and_followup_verification(monkeypatch):
    harness = _ParkedOffload()
    monkeypatch.setattr(auth_routes.asyncio, "to_thread", harness)
    def register_user(username, password, email=None, invite_code=None):
        return 12, None

    def authenticate_user(username, password):
        return _USER_RECORD, None

    auth_service = SimpleNamespace(
        register_user=register_user,
        authenticate_user=authenticate_user,
        generate_user_token=lambda user_id, username, role: f"tok-{user_id}",
    )
    lan = _lan(auth_service=auth_service)
    lan.invalidate_user_cache = lambda: None
    app = web.Application()
    app[LAN_APP_KEY] = lan

    response = await harness.run_with_bystander(
        auth_routes.handle_register(
            _post_request(
                app,
                "/api/auth/register",
                {"username": "bob", "password": "pw"},
            )
        )
    )

    functions = [function.__name__ for function, _args, _kwargs in harness.calls]
    assert functions == ["register_user", "authenticate_user"]
    assert harness.calls[1] == (auth_service.authenticate_user, ("bob", "pw"), {})
    assert harness.calls[0][2] == {"email": None, "invite_code": None}
    assert response.status == 200
    assert response.cookies["lan_token"].value == "tok-7"


@pytest.mark.anyio
async def test_share_password_verify_offloads_pbkdf2_and_keeps_accounting_order(
    monkeypatch,
):
    harness = _ParkedOffload()
    monkeypatch.setattr(shares_routes.asyncio, "to_thread", harness)
    order: list[str] = []

    class Share:
        id = "share-id"
        has_password = True

        def is_expired(self):
            return False

        def to_public_dict(self):
            return {"id": self.id, "has_password": True}

    class ShareService:
        def get_share_record(self, share_id):
            return Share()

        def password_attempt_blocked(self, share_id):
            order.append("blocked")
            return 0

        def verify_password(self, share_id, password):
            order.append("verify")
            return True

        def reset_password_failures(self, share_id):
            order.append("reset")

        def generate_token(self, share_id):
            return "share-secret"

    lan = _lan(share_service=ShareService())
    app = web.Application()
    app[LAN_APP_KEY] = lan
    request = make_mocked_request(
        "POST", "/api/shares/share-id/verify", app=app
    )
    request.json = AsyncMock(return_value={"password": "pw"})
    request.match_info["id"] = "share-id"

    response = await harness.run_with_bystander(
        shares_routes.handle_verify_share_password(request)
    )

    verify_calls = [
        (function, args)
        for function, args, _kwargs in harness.calls
        if function.__name__ == "verify_password"
    ]
    assert len(harness.calls) == 1
    assert verify_calls[0][1] == ("share-id", "pw")
    assert order == ["blocked", "verify", "reset"]
    assert response.status == 200
    cookie = response.cookies["share_token"]
    assert cookie["httponly"] is True
    assert cookie["path"] == "/api/shares/share-id"
    assert request[PRINCIPAL_REQUEST_KEY].kind == "share"
