"""L1 tests — declarative route capabilities and middleware enforcement."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from AssetsManager.lan.principal import principal_for_request
from AssetsManager.lan.route_policy import (
    GUEST_ALLOWED_CAPABILITIES,
    KNOWN_CAPABILITIES,
    RoutePolicy,
)
from AssetsManager.lan.routes._helpers import PRINCIPAL_REQUEST_KEY
from AssetsManager.lan.authorization import enforce_capabilities

ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = ROOT / "scripts" / "check_route_capabilities.py"
_spec = importlib.util.spec_from_file_location("check_route_capabilities", _SCRIPT)
assert _spec is not None and _spec.loader is not None
check_route_capabilities = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = check_route_capabilities
_spec.loader.exec_module(check_route_capabilities)


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ── Declaration vocabulary ─────────────────────────────────────────


def test_route_capability_gate_passes_on_current_tree():
    violations = check_route_capabilities.collect_violations(ROOT)
    assert violations == [], "\n".join(v.format() for v in violations)


def test_unknown_route_capability_fails_closed_at_declaration():
    with pytest.raises(ValueError, match="unknown route capabilities"):
        RoutePolicy(auth="public_optional", capabilities=("superpower",))


def test_guest_allowed_capabilities_are_a_subset_of_known_capabilities():
    assert GUEST_ALLOWED_CAPABILITIES <= KNOWN_CAPABILITIES


def test_capability_vocabulary_covers_principal_fields():
    principal_fields = {
        "browse", "preview", "download", "manage_links", "manage_users",
        "settings", "realtime",
    }
    assert principal_fields <= KNOWN_CAPABILITIES


# ── Enforcement unit tests ─────────────────────────────────────────


def _request_with_principal(kind="guest", **user):
    request = make_mocked_request("POST", "/", app=web.Application())
    request[PRINCIPAL_REQUEST_KEY] = principal_for_request(kind, user=user or None)
    return request


@pytest.mark.anyio
async def test_enforce_allows_when_principal_has_capability():
    request = _request_with_principal("access_key")
    policy = RoutePolicy(capabilities=("manage_links",))
    assert await enforce_capabilities(request, policy) is None


@pytest.mark.anyio
async def test_enforce_denies_guest_for_principal_backed_write():
    request = _request_with_principal("guest")
    policy = RoutePolicy(capabilities=("manage_links",))
    response = await enforce_capabilities(request, policy)
    assert response is not None
    assert response.status == 403
    assert b'"code": "forbidden"' in response.body


@pytest.mark.anyio
async def test_enforce_write_notes_uses_require_user_write():
    request = _request_with_principal(
        "user", user={"id": 1, "username": "alice", "role": "user", "can_write": 0},
    )
    response = await enforce_capabilities(
        request, RoutePolicy(capabilities=("write_notes",)))
    assert response is not None and response.status == 403

    request[PRINCIPAL_REQUEST_KEY] = principal_for_request(
        "user", user={"id": 1, "username": "alice", "role": "user", "can_write": 1})
    assert await enforce_capabilities(
        request, RoutePolicy(capabilities=("write_notes",))) is None


@pytest.mark.anyio
async def test_enforce_admin_tags_denies_can_write_user():
    request = _request_with_principal(
        "user", user={"id": 1, "username": "alice", "role": "user", "can_write": 1},
    )
    response = await enforce_capabilities(
        request, RoutePolicy(capabilities=("admin_tags",)))
    assert response is not None and response.status == 403


@pytest.mark.anyio
async def test_enforce_admin_users_and_settings_deny_non_admin():
    """The hardened read capabilities reject non-admin principals."""
    user = _request_with_principal(
        "user", user={"id": 2, "username": "bob", "role": "user", "can_write": 0},
    )
    for capability in ("admin_users", "settings"):
        response = await enforce_capabilities(
            user, RoutePolicy(capabilities=(capability,)))
        assert response is not None and response.status == 403

    admin = _request_with_principal("local_ui")
    for capability in ("admin_users", "settings"):
        assert await enforce_capabilities(
            admin, RoutePolicy(capabilities=(capability,))) is None

# ── Sensitive read declarations (read-surface hardening) ───────────


def test_sensitive_read_routes_declare_their_data_plane_capability():
    """Audited GET surfaces keep a middleware-enforced capability contract.

    These reads historically relied on handler-level ``require_admin`` only;
    the middleware no-ops on an empty capability tuple. The declarations pin
    the contract at registration time so dropping a handler guard can no
    longer silently reopen the account/operator data planes. Rate-limit
    tiers are unchanged — the golden test in test_route_policy_contract.py
    pins auth/rate_limit and would catch any drift.
    """
    from AssetsManager.lan.api import setup_routes
    from AssetsManager.lan.route_policy import POLICY_KEY

    app = web.Application()
    setup_routes(app)
    table = app[POLICY_KEY]

    expected = {
        ("GET", "/api/users"): ("admin_users",),
        ("GET", "/api/invites"): ("admin_users",),
        ("GET", "/api/activity"): ("admin_users",),
        ("GET", "/api/online-users"): ("admin_users",),
        ("GET", "/api/tunnel/status"): ("settings",),
    }
    for (method, path), capabilities in expected.items():
        policy = table.get((method, path))
        assert policy is not None, f"{method} {path} lost its policy entry"
        assert policy.capabilities == capabilities, (
            f"{method} {path}: capabilities {policy.capabilities!r} "
            f"!= {capabilities!r}"
        )
    # Capability hardening must not drag these reads off their rate tiers.
    assert table[("GET", "/api/tunnel/status")].rate_limit == "browse"
    assert table[("GET", "/api/activity")].rate_limit == "browse"


@pytest.mark.anyio
async def test_hardened_admin_read_is_blocked_by_middleware_before_handler(
    tmp_path, monkeypatch,
):
    """A declared GET capability rejects a non-admin before the handler.

    Proves the new read declarations are enforced by the middleware itself:
    the invite listing 403s even though the handler's own ``require_admin``
    guard is instrumented and never runs.
    """
    from aiohttp.test_utils import TestClient, TestServer

    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.core.settings import AppSettings
    from AssetsManager.lan.routes import users as users_module
    from AssetsManager.lan.server import _LanServerImpl

    class Settings:
        def get(self, key, default=None):
            return {
                "lan_commerce_enabled": False,
                "lan_seller_enabled": False,
                "lan_quota_enabled": False,
                "lan_guest_list": True,
                "lan_guest_download": False,
            }.get(key, default)

    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: Settings()))

    real_require_admin = users_module.require_admin
    handler_guard_calls: list[int] = []

    def counting_require_admin(request):
        handler_guard_calls.append(1)
        return real_require_admin(request)

    monkeypatch.setattr(users_module, "require_admin", counting_require_admin)

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    server = _LanServerImpl(runtime=bootstrap.runtime_for(session),
                            password="real-test-password")
    client = TestClient(TestServer(server._app))
    await client.start_server()
    try:
        registered = await client.post(
            "/api/auth/register",
            json={"username": "plainuser", "password": "Test@1234"},
        )
        assert registered.status == 200
        token = registered.cookies["lan_token"].value

        denied = await client.get(
            "/api/invites", headers={"Authorization": f"Bearer {token}"},
        )
        assert denied.status == 403
        # The middleware rejected the request before handle_invites could
        # run its own admin guard.
        assert handler_guard_calls == []
    finally:
        await client.close()
        session.close()
