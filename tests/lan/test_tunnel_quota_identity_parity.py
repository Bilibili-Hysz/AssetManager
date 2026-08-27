"""quota <-> tunnel_identity visitor-cookie parity contract.

The tunnel limiter must accept exactly the cookies the free-download quota
route mints, and vice versa: same cookie name, same HMAC secret precedence
(including the shared random fallback on a bare lan object), and identical
client-id extraction.  No prior test pinned this cross-module trust even
though both the middleware and the route depend on it.
"""
from AssetsManager.lan import tunnel_identity
from AssetsManager.lan.routes.quota import (
    _new_quota_cookie_token,
    _QUOTA_ID_COOKIE,
    _quota_cookie_id,
    _quota_cookie_signing_secret,
    _valid_quota_cookie_token,
)
from AssetsManager.lan.routes.storefront_analytics import _cookie_signing_secret


class _ConfiguredLan:
    """Secret surface mirroring the lan server object."""

    local_ui_auth_secret = b"parity-secret"
    token_secret = None


class _BareLan:
    """No configured secrets: both modules must share one random fallback."""


def test_cookie_names_and_formats_match():
    assert tunnel_identity.COOKIE_NAME == _QUOTA_ID_COOKIE


def test_signing_secret_precedence_is_shared():
    configured = tunnel_identity.signing_secret(_ConfiguredLan())
    assert configured == _quota_cookie_signing_secret(_ConfiguredLan())
    assert configured == _cookie_signing_secret(_ConfiguredLan())

    bare = _BareLan()
    first = tunnel_identity.signing_secret(bare)
    second = _quota_cookie_signing_secret(bare)
    third = _cookie_signing_secret(bare)
    assert first == second == third
    # The cached fallback attribute is what makes later mints agree.
    assert getattr(bare, "_quota_cookie_secret") == first


def test_tokens_verify_across_modules_in_both_directions():
    secret = tunnel_identity.signing_secret(_ConfiguredLan())

    quota_token = _new_quota_cookie_token(secret)
    assert tunnel_identity.valid_token(quota_token, secret) is not None
    client_from_tunnel = tunnel_identity.token_client_id(quota_token)
    assert client_from_tunnel == _quota_cookie_id(quota_token)

    tunnel_token = tunnel_identity.new_token(secret)
    assert _valid_quota_cookie_token(tunnel_token, secret) is not None
