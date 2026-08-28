"""Production `_LanServerImpl._build_app` assembly contract.

Every prior security test stopped at a standalone ``create_security_middleware``
or mocked ``_build_app`` away entirely.  This file drives the real production
builder on a skeleton instance and pins:

* the app registers THIS server under LAN_APP_KEY plus the ZIP executor key;
* the middleware chain starts with the security middleware;
* the production resolver validates cookies minted by the free-download
  quota route, and the production minter produces tokens that route's
  validator accepts — cross-module trust wired through real code paths.
"""
from types import SimpleNamespace

from aiohttp.test_utils import make_mocked_request

from AssetsManager.lan import tunnel_identity
from AssetsManager.lan.routes._helpers import LAN_APP_KEY
from AssetsManager.lan.routes.quota import (
    _new_quota_cookie_token,
    _QUOTA_ID_COOKIE,
    _quota_cookie_id,
    _valid_quota_cookie_token,
)
from AssetsManager.lan.security import AuthRateLimiter, IPBlacklist, RateLimiter
from AssetsManager.lan.server import ZIP_EXECUTOR_APP_KEY, _LanServerImpl


def _skeleton_server():
    """Build an impl without __init__: only what `_build_app` touches."""
    server = object.__new__(_LanServerImpl)
    server._rate_limiter = RateLimiter()
    server._ip_blacklist = IPBlacklist()
    server._auth_rate_limiter = AuthRateLimiter(max_attempts=5, window_seconds=300)
    server._browse_rate_limiter = RateLimiter()
    server._ip_whitelist = []
    # Resolver/minter derive their HMAC secret from these four attributes.
    server._token_secret = "a" * 64
    server._password_value = None
    server._access_key_value = None
    server._auth_mode = "none"
    server._zip_executor = SimpleNamespace(name="zip-executor")
    return server


def test_build_app_registers_server_and_zip_executor_with_security_first():
    server = _skeleton_server()
    assert getattr(server, "_app", None) is None

    server._build_app()

    app = server._app
    assert app[LAN_APP_KEY] is server
    assert app[ZIP_EXECUTOR_APP_KEY] is server._zip_executor
    middlewares = list(app.middlewares)
    # Shape unification: the error-contract middleware is wired as the
    # innermost (handler-adjacent) layer on top of the previous three.
    assert len(middlewares) == 4
    assert middlewares[0].__qualname__.endswith("security_middleware")
    assert middlewares[-1].__qualname__.endswith("error_contract_middleware")


def test_production_resolver_accepts_quota_minted_cookie():
    server = _skeleton_server()
    secret = tunnel_identity.signing_secret(server)
    quota_token = _new_quota_cookie_token(secret)
    request = make_mocked_request(
        "GET", "/api/quota", headers={"Cookie": f"{_QUOTA_ID_COOKIE}={quota_token}"}
    )

    resolved = server._tunnel_identity_resolver(request)

    assert resolved == tunnel_identity.token_client_id(quota_token)


def test_production_minter_emits_tokens_the_quota_route_validates():
    server = _skeleton_server()
    client_id, cookie_token = server._tunnel_identity_minter()

    assert _valid_quota_cookie_token(cookie_token, tunnel_identity.signing_secret(server))
    assert client_id == _quota_cookie_id(cookie_token)
