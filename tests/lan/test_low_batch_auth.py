"""Low-severity LAN auth batch (group A): empty-login, user enumeration,
duplicate registration, and auth-cookie Secure flag call sites.

These tests pin the public error contract introduced to avoid leaking whether
a username exists (Bug 16) and to reject credential-less logins (Bug 15).
"""

import sqlite3

import pytest

from tests.lan.support.api_helpers import _init_lan_schemas, _make_client, _make_lan_app


def _set_plain_http_lan(app):
    """Document that the test fixture serves plain HTTP (ssl_active=False).

    The _FakeLan test double may or may not define ``ssl_active`` yet
    (AssetsManager.lan.LanServer does); the auth routes read it to decide
    whether the auth cookie carries the Secure attribute.
    """
    from AssetsManager.lan.routes._helpers import LAN_APP_KEY

    lan = app[LAN_APP_KEY]
    if not hasattr(lan, "ssl_active"):
        lan.ssl_active = False
    return lan


@pytest.mark.anyio
async def test_empty_login_without_credentials_returns_400(tmp_path):
    """A login with no username and no password must not succeed with 200."""
    app, library, conn = _make_lan_app(tmp_path)

    client = await _make_client(app)
    try:
        resp = await client.post("/api/auth/login", json={})
        assert resp.status == 400
        body = await resp.json()
        assert "error" in body
    finally:
        await client.close()


@pytest.mark.anyio
async def test_login_failure_message_does_not_enumerate_users(tmp_path):
    """Wrong username and wrong password must yield the identical error."""
    app, library, conn = _make_lan_app(tmp_path)
    _set_plain_http_lan(app)

    client = await _make_client(app)
    try:
        registered = await client.post(
            "/api/auth/register",
            json={"username": "alice", "password": "Test@1234"},
        )
        assert registered.status == 200
        client.session.cookie_jar.clear()

        wrong_user = await client.post(
            "/api/auth/login",
            json={"username": "no-such-user", "password": "Test@1234"},
        )
        assert wrong_user.status == 401
        assert (await wrong_user.json())["error"] == "Invalid username or password"

        wrong_password = await client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "Wrong@1234"},
        )
        assert wrong_password.status == 401
        assert (await wrong_password.json())["error"] == "Invalid username or password"
    finally:
        await client.close()


@pytest.mark.anyio
async def test_duplicate_registration_returns_generic_error(tmp_path):
    """Re-registering an existing username must not reveal the username."""
    app, library, conn = _make_lan_app(tmp_path)
    _set_plain_http_lan(app)

    client = await _make_client(app)
    try:
        first = await client.post(
            "/api/auth/register",
            json={"username": "dup-user", "password": "Test@1234"},
        )
        assert first.status == 200
        client.session.cookie_jar.clear()

        second = await client.post(
            "/api/auth/register",
            json={"username": "dup-user", "password": "Test@1234"},
        )
        assert second.status == 400
        assert (await second.json())["error"] == "Registration failed"
    finally:
        await client.close()


def test_authenticate_user_error_message_is_uniform():
    """Service-level check that unknown user and wrong password agree."""
    from AssetsManager.application.auth_service import AuthService
    from AssetsManager.core import database

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    try:
        conn.executescript(database._SCHEMA)
        conn.commit()
        _init_lan_schemas(conn)

        svc = AuthService(conn, "test-secret")
        user_id, err = svc.register_user("alice", "Test@1234")
        assert user_id is not None
        assert err == ""

        _, missing_user_err = svc.authenticate_user("ghost", "Test@1234")
        _, wrong_password_err = svc.authenticate_user("alice", "Wrong@1234")
        assert missing_user_err == wrong_password_err == "Invalid username or password"

        _, dup_err = svc.register_user("alice", "Test@1234")
        assert dup_err == "Registration failed"
    finally:
        conn.close()


@pytest.mark.anyio
async def test_auth_cookie_secure_flag_follows_lan_ssl_active(tmp_path):
    """Plain-HTTP LAN fixtures (ssl_active=False) must keep the auth cookie
    usable without the Secure attribute."""
    app, library, conn = _make_lan_app(tmp_path)
    _set_plain_http_lan(app)

    client = await _make_client(app)
    try:
        resp = await client.post(
            "/api/auth/register",
            json={"username": "cookie-user", "password": "Test@1234"},
        )
        assert resp.status == 200
        cookie = resp.cookies["lan_token"]
        assert cookie["httponly"] is True
        assert not cookie["secure"]
    finally:
        await client.close()
