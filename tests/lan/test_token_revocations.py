"""Regression tests for durable LAN token revocations."""

from __future__ import annotations

import asyncio
import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from aiohttp.test_utils import make_mocked_request

from AssetsManager.lan.routes._helpers import LAN_APP_KEY
from AssetsManager.lan.routes.auth import handle_logout
from AssetsManager.lan.token_revocations import (
    TokenRevocationPersistenceError,
    TokenRevocationRegistry,
)


class _FailingAuthService:
    def __init__(self) -> None:
        self.load_calls = 0

    def revoke_token(self, token: str, *, ttl: float) -> None:
        raise RuntimeError("database write failed")

    def load_active_revocations(self) -> dict[str, float]:
        self.load_calls += 1
        if self.load_calls == 1:
            raise RuntimeError("database read failed")
        return {}

    def prune_revocations(self) -> None:
        return None


def _host(auth_service) -> SimpleNamespace:
    return SimpleNamespace(
        _revoked_tokens={},
        _revoked_loaded=False,
        _auth_service=auth_service,
        _TOKEN_REVOCATION_TTL=86400.0,
        _TOKEN_REVOCATION_MAX=100,
    )


def test_logout_clears_cookie_when_durable_revocation_fails():
    class FailingLan:
        def revoke_auth_token(self, _token):
            raise TokenRevocationPersistenceError("database unavailable")

    request = make_mocked_request(
        "POST", "/api/auth/logout",
        headers={"Authorization": "Bearer token"},
        app={LAN_APP_KEY: FailingLan()},
    )
    response = asyncio.run(handle_logout(request))
    assert response.status == 503
    assert response.cookies["lan_token"]["max-age"] == "0"


def test_revoke_does_not_publish_cache_when_persistence_fails():
    host = _host(_FailingAuthService())
    registry = TokenRevocationRegistry(host)

    with pytest.raises(RuntimeError, match="Unable to persist token revocation"):
        registry.revoke_auth_token("token")

    # The durable write is still retryable, but this process must reject the
    # token immediately after the failed logout attempt.
    assert registry.is_auth_token_revoked("token") is True


def test_failed_initial_load_is_retryable_and_fails_closed():
    auth_service = _FailingAuthService()
    host = _host(auth_service)
    registry = TokenRevocationRegistry(host)

    # Unknown tokens are rejected while the durable state is unavailable.
    assert registry.is_auth_token_revoked("token") is True
    assert host._revoked_loaded is False

    # A later successful read is retried and establishes the loaded marker.
    assert registry.is_auth_token_revoked("token") is False
    assert host._revoked_loaded is True
    assert auth_service.load_calls == 2


def test_concurrent_first_load_runs_once():
    class BlockingAuthService:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.release = threading.Event()
            self.load_calls = 0

        def load_active_revocations(self) -> dict[str, float]:
            self.load_calls += 1
            self.started.set()
            assert self.release.wait(2)
            return {}

        def is_token_revoked(self, _token: str) -> bool:
            return False

    auth_service = BlockingAuthService()
    host = _host(auth_service)
    registry = TokenRevocationRegistry(host)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(registry.is_auth_token_revoked, "first")
        assert auth_service.started.wait(2)
        second = executor.submit(registry.is_auth_token_revoked, "second")
        time.sleep(0.05)
        assert not second.done()
        auth_service.release.set()
        assert first.result() is False
        assert second.result() is False
    assert auth_service.load_calls == 1


def test_cache_bound_keeps_durable_miss_authoritative():
    class DurableAuthService:
        def __init__(self) -> None:
            self.revoked = {"evicted-token"}
            self.lookups = 0

        def load_active_revocations(self) -> dict[str, float]:
            return {}

        def revoke_token(self, _token: str, *, ttl: float) -> None:
            return None

        def is_token_revoked(self, token: str) -> bool:
            self.lookups += 1
            return token in self.revoked

    auth_service = DurableAuthService()
    host = _host(auth_service)
    host._TOKEN_REVOCATION_MAX = 2
    registry = TokenRevocationRegistry(host)
    assert registry.is_auth_token_revoked("probe") is False
    now = time.time()
    registry._host._revoked_tokens.update({
        hashlib.sha256("evicted-token".encode()).hexdigest(): now + 10.0,
        hashlib.sha256("keep-token".encode()).hexdigest(): now + 20.0,
    })
    registry.revoke_auth_token("new-token")
    assert len(host._revoked_tokens) == 2
    assert registry.is_auth_token_revoked("evicted-token") is True
    assert auth_service.lookups == 2
