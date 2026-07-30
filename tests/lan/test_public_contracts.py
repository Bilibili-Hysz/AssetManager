"""Phase 1 public LAN response contracts."""
import copy
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from AssetsManager.lan.dto import (
    InviteResponse,
    StatsResponse,
    TagResponse,
    TreeItemResponse,
    UserResponse,
)


CONTRACTS = Path(__file__).parents[1] / "contracts" / "lan_public_contracts.json"


def test_user_normalizes_active_and_excludes_secret_fields():
    record = {
        "id": 1,
        "username": "owner",
        "role": "admin",
        "is_active": 1,
        "created_at": 100,
        "password_hash": "never-public",
        "email": "owner@example.test",
    }
    assert UserResponse.from_record(record).to_dict() == {
        "id": 1, "username": "owner", "role": "admin", "active": True,
        "created_at": 100.0,
    }


def test_invite_normalizes_used_and_revoked_with_null_default():
    assert InviteResponse.from_record({
        "code": "USED", "created_at": 101, "used_by": "alice", "is_active": 1,
        "secret": "never-public",
    }).to_dict() == {
        "code": "USED", "created_at": 101.0, "used_by": "alice", "revoked": False,
    }
    assert InviteResponse.from_record({
        "code": "REVOKED", "created_at": 102, "is_active": 0,
    }).to_dict() == {
        "code": "REVOKED", "created_at": 102.0, "used_by": None, "revoked": True,
    }


def test_tag_has_exact_guaranteed_keys():
    # TagService.list_tags() returns repository count records without IDs;
    # null is the explicit public value when no real repository ID exists.
    assert TagResponse.from_record({"name": "hero", "count": 3, "metadata": "ignored"}).to_dict() == {
        "id": None, "name": "hero", "count": 3,
    }


def test_tree_is_recursive_and_has_public_type():
    tree = TreeItemResponse.from_record({
        "name": "project", "path": "project", "is_leaf": False,
        "children": [
            {"name": "assets", "path": "project/assets", "is_leaf": True},
            {"name": "source", "path": "project/source", "is_leaf": True},
        ],
        "repository_only": "ignored",
    })
    assert tree.to_dict() == {
        "name": "project", "path": "project", "type": "dir", "is_leaf": False,
        "children": [
            {"name": "assets", "path": "project/assets", "type": "dir",
             "is_leaf": True, "children": []},
            {"name": "source", "path": "project/source", "type": "dir",
             "is_leaf": True, "children": []},
        ],
    }


def test_tree_leaf_directory_without_explicit_type_defaults_to_dir():
    assert TreeItemResponse.from_record({
        "name": "project", "path": "project", "is_leaf": True, "children": [],
    }).to_dict()["type"] == "dir"


def test_tree_rejects_file_type_from_directory_source():
    with pytest.raises(ValueError, match="tree type must be 'dir'"):
        TreeItemResponse.from_record({
            "name": "asset.txt", "path": "asset.txt", "type": "file", "is_leaf": True,
        })


def test_tree_rejects_unknown_explicit_type():
    with pytest.raises(ValueError, match="tree type must be 'dir'"):
        TreeItemResponse.from_record({
            "name": "project", "path": "project", "type": "symlink", "is_leaf": True,
        })


def test_tree_rejects_malformed_string_leaf_flag():
    # ProjectTree records continue to provide a real bool, never a string flag.
    with pytest.raises(TypeError, match="is_leaf must be bool"):
        TreeItemResponse.from_record({
            "name": "assets", "path": "assets", "is_leaf": "0",
        })


def test_tree_rejects_missing_leaf_flag():
    with pytest.raises(TypeError, match="is_leaf must be bool"):
        TreeItemResponse.from_record({
            "name": "missing-leaf", "path": "missing-leaf", "children": [],
        })


def test_stats_has_exact_public_keys():
    assert StatsResponse.from_record({
        "connections": 2, "requests": 7, "bytes_transferred": 1024,
        "bytes_transferred_fmt": "1 KB", "uptime": 12.5, "secret": "ignored",
    }).to_dict() == {
        "connections": 2, "requests": 7, "bytes_transferred": 1024,
        "bytes_transferred_fmt": "1 KB", "uptime": 12.5,
    }


def test_dtos_are_frozen():
    response = UserResponse.from_record({
        "id": 1, "username": "u", "role": "viewer", "is_active": 1, "created_at": 1,
    })
    with pytest.raises(FrozenInstanceError):
        response.username = "changed"


def test_conversion_does_not_mutate_raw_record():
    record = {"id": 1, "username": "u", "role": "viewer", "is_active": 1, "created_at": 1,
              "password_hash": "secret"}
    original = copy.deepcopy(record)
    UserResponse.from_record(record)
    assert record == original


def test_golden_fixture_exact_equality():
    expected = json.loads(CONTRACTS.read_text(encoding="utf-8"))
    assert UserResponse.from_record(expected["records"]["user"]).to_dict() == expected["responses"]["user"]
    assert InviteResponse.from_record(expected["records"]["invite_used"]).to_dict() == expected["responses"]["invite_used"]
    assert InviteResponse.from_record(expected["records"]["invite_revoked"]).to_dict() == expected["responses"]["invite_revoked"]
    assert TagResponse.from_record(expected["records"]["tag"]).to_dict() == expected["responses"]["tag"]
    assert TreeItemResponse.from_record(expected["records"]["tree"]).to_dict() == expected["responses"]["tree"]
    assert StatsResponse.from_record(expected["records"]["stats"]).to_dict() == expected["responses"]["stats"]


@pytest.mark.anyio
async def test_route_responses_are_normalized_and_keep_envelopes(tmp_path, monkeypatch):
    from tests.lan.test_lan_api import _local_ui_headers, _make_client, _make_lan_app

    app, library, conn = _make_lan_app(tmp_path)
    (library / "project" / "assets").mkdir(parents=True)
    (library / "project" / "source").mkdir()
    asset_path = library / "asset.txt"
    asset_path.write_text("asset", encoding="utf-8")
    conn.execute(
        "INSERT INTO file_tags (file_path, tag) VALUES (?, ?)",
        (str(asset_path.resolve()), "hero"),
    )
    conn.commit()
    from AssetsManager.lan.routes._helpers import LAN_APP_KEY

    lan = app[LAN_APP_KEY]
    monkeypatch.setattr(lan, "status", lambda: {
        "connections": 2, "requests": 7, "bytes_transferred": 1024, "uptime": 12.5,
    }, raising=False)
    client = await _make_client(app)
    try:
        headers = _local_ui_headers(app)
        tags = await client.get("/api/tags", headers=headers)
        stats = await client.get("/api/stats", headers=headers)
        tree = await client.get("/api/tree", headers=headers)
        assert tags.status == stats.status == tree.status == 200
        tags_payload = (await tags.json())["tags"]
        assert tags_payload == [{"id": None, "name": "hero", "count": 1}]
        assert set((await stats.json()).keys()) == {
            "connections", "requests", "bytes_transferred", "bytes_transferred_fmt", "uptime",
        }
        tree_payload = await tree.json()
        assert set(tree_payload.keys()) == {"tree", "depth_config"}
        assert tags_payload
        assert tree_payload["tree"]
        assert all(item["type"] == "dir" and isinstance(item["is_leaf"], bool)
                   for item in tree_payload["tree"])
        assert all(child["type"] == "dir" and isinstance(child["is_leaf"], bool)
                   for item in tree_payload["tree"] for child in item["children"])
        assert all(set(item) == {"name", "path", "type", "is_leaf", "children"}
                   for item in tree_payload["tree"])
    finally:
        await client.close()


@pytest.mark.anyio
async def test_users_route_enforces_admin_and_exposes_only_public_user_keys(tmp_path):
    from tests.lan.test_lan_api import _local_ui_headers, _make_client, _make_lan_app

    app, _library, conn = _make_lan_app(tmp_path)
    conn.execute(
        "INSERT INTO users (username, password, email, role, is_active, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("active-user", "stored-password", "private@example.test", "viewer", 1, 123.0),
    )
    conn.commit()
    client = await _make_client(app)
    try:
        assert (await client.get("/api/users")).status == 403
        non_admin_root = tmp_path / "non-admin"
        non_admin_root.mkdir()
        non_admin_app, _library, non_admin_conn = _make_lan_app(
            non_admin_root, authenticated_context_only=True,
        )
        non_admin_client = await _make_client(non_admin_app)
        try:
            assert (await non_admin_client.get("/api/users")).status == 403
        finally:
            await non_admin_client.close()

        response = await client.get("/api/users", headers=_local_ui_headers(app))
        assert response.status == 200
        users = (await response.json())["users"]
        assert users
        assert all(set(user) == {"id", "username", "role", "active", "created_at"} for user in users)
        assert all(isinstance(user["active"], bool) for user in users)
        assert all("password_hash" not in user and "email" not in user for user in users)
    finally:
        await client.close()


@pytest.mark.anyio
async def test_invites_route_enforces_admin_and_exposes_public_defaults(tmp_path):
    # AuthRepository.list_invite_codes() currently has no used_by field, so
    # route responses always default used_by to null; used-invite semantics
    # from a future data source are deferred.
    from tests.lan.test_lan_api import _local_ui_headers, _make_client, _make_lan_app

    app, _library, conn = _make_lan_app(tmp_path)
    conn.execute(
        "INSERT INTO invite_codes (code, created_by, created_at, is_active) VALUES (?, ?, ?, ?)",
        ("REAL-INVITE", "creator-not-public", 456.0, 1),
    )
    conn.commit()
    client = await _make_client(app)
    try:
        assert (await client.get("/api/invites")).status == 403
        non_admin_root = tmp_path / "non-admin"
        non_admin_root.mkdir()
        non_admin_app, _library, _conn = _make_lan_app(
            non_admin_root, authenticated_context_only=True,
        )
        non_admin_client = await _make_client(non_admin_app)
        try:
            assert (await non_admin_client.get("/api/invites")).status == 403
        finally:
            await non_admin_client.close()

        response = await client.get("/api/invites", headers=_local_ui_headers(app))
        assert response.status == 200
        invites = (await response.json())["invites"]
        assert invites
        assert all(set(invite) == {"code", "created_at", "used_by", "revoked"} for invite in invites)
        assert any(
            invite["code"] == "REAL-INVITE" and invite["used_by"] is None
            and invite["revoked"] is False
            for invite in invites
        )
        assert all("created_by" not in invite for invite in invites)
    finally:
        await client.close()
