"""Audit task C2: per-user metadata/tag write permission (default off).

Covers the require_user_write gate, the three opened write endpoints, the
admin-only PATCH toggle endpoint, and the verify_user_token can_write passthrough.
"""
from __future__ import annotations

import pytest

from AssetsManager.application.auth_service import AuthService
from AssetsManager.domain.event_bus import EventBus
from AssetsManager.domain.events import UserChanged
from AssetsManager.lan.principal import principal_for_request
from AssetsManager.lan.routes._helpers import require_user_write
from tests.lan.support.api_helpers import _local_ui_headers, _make_client, _make_lan_app, _register_user_token


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _user_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── require_user_write unit gate ────────────────────────────────────


def test_require_user_write_allows_admin_principals():
    for kind in ("password", "access_key", "local_ui"):
        request = {"principal": principal_for_request(kind)}
        assert require_user_write(request) is not None


def test_require_user_write_denies_user_without_flag():
    request = {"principal": principal_for_request(
        "user", user={"id": 1, "username": "alice", "role": "user", "can_write": 0},
    )}
    assert require_user_write(request) is None


def test_require_user_write_allows_user_with_flag():
    request = {"principal": principal_for_request(
        "user", user={"id": 1, "username": "alice", "role": "user", "can_write": 1},
    )}
    assert require_user_write(request) is not None


def test_require_user_write_denies_guest_and_share():
    for kind in ("guest", "share"):
        request = {"principal": principal_for_request(kind)}
        assert require_user_write(request) is None


def test_require_user_write_denies_without_principal():
    assert require_user_write({}) is None


# ── Route gate: default off (403) ────────────────────────────────────


@pytest.mark.anyio
async def test_non_enabled_user_cannot_write_meta_or_create_tag(tmp_path):
    app, library, conn = _make_lan_app(tmp_path)
    target = library / "asset.txt"
    target.write_text("asset", encoding="utf-8")
    client = await _make_client(app)
    try:
        token = await _register_user_token(client, username="alice")
        headers = _user_headers(token)

        notes = await client.put(
            "/api/notes/asset.txt", json={"notes": "hello"}, headers=headers
        )
        assert notes.status == 403

        tag = await client.post(
            "/api/tags", json={"tag": "hero", "file_path": "asset.txt"}, headers=headers
        )
        assert tag.status == 403

        # Nothing was written.
        assert conn.execute(
            "SELECT notes FROM file_meta WHERE file_path=?",
            (str(target.resolve()),),
        ).fetchone() is None
        assert conn.execute(
            "SELECT tag FROM file_tags WHERE file_path=?",
            (str(target.resolve()),),
        ).fetchone() is None
    finally:
        await client.close()


@pytest.mark.anyio
async def test_disabled_user_still_cannot_rename_delete_tag(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    target = library / "asset.txt"
    target.write_text("asset", encoding="utf-8")
    client = await _make_client(app)
    try:
        token = await _register_user_token(client, username="alice")
        headers = _user_headers(token)

        rename = await client.put(
            "/api/tags/hero", json={"new_name": "villain"}, headers=headers
        )
        assert rename.status == 403

        delete = await client.delete("/api/tags/hero", headers=headers)
        assert delete.status == 403

        # Admin-only endpoints remain closed to a can_write user.
        users = await client.get("/api/users", headers=headers)
        assert users.status == 403
    finally:
        await client.close()


# ── Route gate: enabled (200) and persisted ──────────────────────────


@pytest.mark.anyio
async def test_enabled_user_can_write_meta_and_create_tag(tmp_path):
    app, library, conn = _make_lan_app(tmp_path)
    target = library / "asset.txt"
    target.write_text("asset", encoding="utf-8")
    client = await _make_client(app)
    try:
        token = await _register_user_token(client, username="alice")
        auth = _local_ui_headers(app)

        patch = await client.patch(
            "/api/users/alice", json={"can_write": True}, headers=auth
        )
        assert patch.status == 200
        assert await patch.json() == {"ok": True, "username": "alice", "can_write": True}

        headers = _user_headers(token)

        notes = await client.put(
            "/api/notes/asset.txt", json={"notes": "hello"}, headers=headers
        )
        assert notes.status == 200
        assert conn.execute(
            "SELECT notes FROM file_meta WHERE file_path=?",
            (str(target.resolve()),),
        ).fetchone() == ("hello",)

        tag = await client.post(
            "/api/tags", json={"tag": "hero", "file_path": "asset.txt"}, headers=headers
        )
        assert tag.status == 200
        assert conn.execute(
            "SELECT tag FROM file_tags WHERE file_path=?",
            (str(target.resolve()),),
        ).fetchone() == ("hero",)
    finally:
        await client.close()


# ── PATCH endpoint contract ─────────────────────────────────────────


@pytest.mark.anyio
async def test_patch_user_can_write_is_admin_only(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    client = await _make_client(app)
    try:
        token = await _register_user_token(client, username="alice")

        # A user principal (even can_write) cannot toggle other users.
        denied = await client.patch(
            "/api/users/alice",
            json={"can_write": True},
            headers=_user_headers(token),
        )
        assert denied.status == 403

        # A guest cannot toggle.
        guest = await client.patch("/api/users/alice", json={"can_write": True})
        assert guest.status == 403
    finally:
        await client.close()


@pytest.mark.anyio
async def test_patch_user_can_write_rejects_unknown_field(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    client = await _make_client(app)
    try:
        await _register_user_token(client, username="alice")
        auth = _local_ui_headers(app)

        bad = await client.patch(
            "/api/users/alice", json={"can_write": True, "role": "admin"}, headers=auth
        )
        assert bad.status == 400

        non_bool = await client.patch(
            "/api/users/alice", json={"can_write": "yes"}, headers=auth
        )
        assert non_bool.status == 400

        missing = await client.patch("/api/users/alice", json={}, headers=auth)
        assert missing.status == 400
    finally:
        await client.close()


@pytest.mark.anyio
async def test_patch_user_can_write_unknown_user_404(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    client = await _make_client(app)
    try:
        auth = _local_ui_headers(app)
        missing = await client.patch(
            "/api/users/ghost", json={"can_write": True}, headers=auth
        )
        assert missing.status == 404
    finally:
        await client.close()


# ── verify_user_token passthrough + UserChanged event ────────────────


def test_verify_user_token_returns_can_write(schema_db):
    service = AuthService(schema_db, "secret")
    user_id, err = service.register_user("alice", "Test@1234")
    assert err == "" and user_id is not None

    token = service.generate_user_token(user_id, "alice", "viewer")

    # Not enabled yet.
    verified = service.verify_user_token(token)
    assert verified is not None
    assert verified["can_write"] == 0

    # Enable and re-verify (cache invalidation makes the update visible).
    assert service.set_user_can_write("alice", True) is True
    re_verified = service.verify_user_token(token)
    assert re_verified is not None
    assert re_verified["can_write"] == 1


def test_set_user_can_write_publishes_user_changed(schema_db, monkeypatch):
    bus = EventBus()
    service = AuthService(schema_db, "secret")
    service.init_tables()
    service._library_root = "/library"
    service._session_token = "session-token"
    service._event_bus = bus

    user_id, _err = service.register_user("bob", "Test@1234")
    assert user_id is not None

    published: list[UserChanged] = []
    monkeypatch.setattr(bus, "publish", published.append)

    assert service.set_user_can_write("bob", True) is True
    assert len(published) == 1
    assert isinstance(published[0], UserChanged)
    assert published[0].library_root == "/library"
    assert published[0].session_token == "session-token"


def test_set_user_can_write_publishes_only_on_success(schema_db, monkeypatch):
    bus = EventBus()
    service = AuthService(schema_db, "secret")
    service.init_tables()
    service._library_root = "/library"
    service._session_token = "session-token"
    service._event_bus = bus

    published: list[UserChanged] = []
    monkeypatch.setattr(bus, "publish", published.append)

    # Unknown username -> repository never updates -> no event.
    assert service.set_user_can_write("ghost", True) is False
    assert published == []


def test_set_user_can_write_unknown_username_returns_false(schema_db):
    service = AuthService(schema_db, "secret")
    service.init_tables()
    assert service.set_user_can_write("ghost", True) is False
