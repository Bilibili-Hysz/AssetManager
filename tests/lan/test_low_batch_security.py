"""Low-batch security tests: IP whitelist normalization and tunnel bypass."""
import pytest

from AssetsManager.lan.security import (
    IPBlacklist,
    RateLimiter,
    _normalize_ip,
    create_security_middleware,
)


def pytest_configure(config):
    config.addinivalue_line("markers", "anyio: run test using anyio")


def pytest_generate_tests(metafunc):
    if "anyio_backend" in metafunc.fixturenames:
        metafunc.parametrize("anyio_backend", ["asyncio"])


# ── _normalize_ip ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("::ffff:127.0.0.1", "127.0.0.1"),
        ("::1", "127.0.0.1"),
        ("127.0.0.1", "127.0.0.1"),
        ("not-an-ip", "not-an-ip"),
        ("::ffff:10.0.0.1", "10.0.0.1"),
    ],
)
def test_normalize_ip(raw, expected):
    assert _normalize_ip(raw) == expected


def test_normalize_ip_other_ips_unchanged():
    assert _normalize_ip("10.0.0.1") == "10.0.0.1"
    assert _normalize_ip("192.168.1.5") == "192.168.1.5"
    assert _normalize_ip("2001:db8::1") == "2001:db8::1"


# ── IPBlacklist normalization ────────────────────────────────────


def test_blacklist_load_normalizes_ipv6_forms():
    blacklist = IPBlacklist()
    blacklist.load_from_settings(["::1", "::ffff:10.0.0.1", "not-an-ip"])
    assert blacklist.is_blocked("127.0.0.1") is True
    assert blacklist.is_blocked("10.0.0.1") is True
    assert blacklist.is_blocked("not-an-ip") is True
    assert blacklist.is_blocked("192.168.1.5") is False


def test_blacklist_block_and_unblock_still_match_plain_ips():
    blacklist = IPBlacklist()
    blacklist.block("10.0.0.1")
    assert blacklist.is_blocked("10.0.0.1") is True
    blacklist.unblock("10.0.0.1")
    assert blacklist.is_blocked("10.0.0.1") is False


# ── middleware: whitelist normalization + tunnel bypass ──────────


def _make_middleware(ip_whitelist, tunnel_active=None, blacklist=None):
    blacklist = blacklist or IPBlacklist()
    return create_security_middleware(
        RateLimiter(),
        blacklist,
        ip_whitelist=ip_whitelist,
        tunnel_active=tunnel_active,
    )


async def _call_middleware(middleware, remote):
    """Invoke the middleware directly with a mocked request carrying `remote`."""
    from aiohttp import web
    from aiohttp.test_utils import make_mocked_request

    async def handler(_request):
        return web.json_response({"ok": True})

    request = make_mocked_request("GET", "/")
    request._cache["remote"] = remote
    return await middleware(request, handler)


@pytest.mark.anyio
async def test_whitelist_accepts_equivalent_loopback_forms():
    middleware = _make_middleware(["127.0.0.1"])
    for remote in ("::ffff:127.0.0.1", "::1", "127.0.0.1"):
        response = await _call_middleware(middleware, remote)
        assert response.status == 200, remote


@pytest.mark.anyio
async def test_whitelist_rejects_non_matching_ip():
    middleware = _make_middleware(["127.0.0.1"])
    response = await _call_middleware(middleware, "192.168.1.5")
    assert response.status == 403


@pytest.mark.anyio
async def test_whitelist_rejects_ipv4_mapped_form_of_other_ip():
    middleware = _make_middleware(["10.0.0.1"])
    response = await _call_middleware(middleware, "::ffff:192.168.1.5")
    assert response.status == 403


@pytest.mark.anyio
async def test_tunnel_active_bypasses_whitelist_for_loopback():
    middleware = _make_middleware(["10.0.0.1"], tunnel_active=lambda: True)
    response = await _call_middleware(middleware, "127.0.0.1")
    assert response.status == 200


@pytest.mark.anyio
async def test_tunnel_inactive_does_not_bypass_whitelist():
    middleware = _make_middleware(["10.0.0.1"], tunnel_active=lambda: False)
    response = await _call_middleware(middleware, "127.0.0.1")
    assert response.status == 403


@pytest.mark.anyio
async def test_no_tunnel_callback_does_not_bypass_whitelist():
    middleware = _make_middleware(["10.0.0.1"], tunnel_active=None)
    response = await _call_middleware(middleware, "127.0.0.1")
    assert response.status == 403


@pytest.mark.anyio
async def test_tunnel_bypass_does_not_apply_to_non_loopback():
    middleware = _make_middleware(["10.0.0.1"], tunnel_active=lambda: True)
    response = await _call_middleware(middleware, "192.168.1.5")
    assert response.status == 403


@pytest.mark.anyio
async def test_tunnel_bypass_does_not_apply_to_loopback_ipv6_form():
    middleware = _make_middleware(["10.0.0.1"], tunnel_active=lambda: True)
    response = await _call_middleware(middleware, "::1")
    assert response.status == 200


@pytest.mark.anyio
async def test_tunnel_bypass_does_not_override_blacklist():
    blacklist = IPBlacklist()
    blacklist.load_from_settings(["127.0.0.1"])
    middleware = _make_middleware(
        ["10.0.0.1"], tunnel_active=lambda: True, blacklist=blacklist
    )
    response = await _call_middleware(middleware, "::ffff:127.0.0.1")
    assert response.status == 403
