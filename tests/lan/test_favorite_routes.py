from __future__ import annotations

from dataclasses import replace

import pytest
from PIL import Image

from AssetsManager.application.favorite_service import FavoriteService
from AssetsManager.application.gallery_service import GalleryService
from AssetsManager.lan.routes._helpers import AUTH_SERVICE_APP_KEY, LAN_APP_KEY
from AssetsManager.repositories.auth_repository import AuthRepository
from AssetsManager.repositories.favorite_repository import FavoriteRepository
from tests.lan.support.api_helpers import _make_client, _make_lan_app


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _image(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 16), (40, 80, 160)).save(path)


def _attach_favorite_services(app, conn):
    lan = app[LAN_APP_KEY]
    FavoriteRepository(conn).init_table()
    lan.services = replace(
        lan.services,
        favorite_service=FavoriteService(connection_provider=lan.connection_for),
        gallery_service=GalleryService(connection_provider=lan.connection_for),
    )


def _user_headers(app, conn, username: str) -> dict[str, str]:
    repository = AuthRepository(conn)
    user_id = repository.insert_user(username, "test-password-hash", role="user")
    assert user_id is not None
    token = app[AUTH_SERVICE_APP_KEY].generate_user_token(user_id, username, "user")
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.anyio
async def test_favorite_routes_are_principal_scoped_and_return_gallery_entries(tmp_path):
    app, library, conn = _make_lan_app(tmp_path)
    _image(library / "collection" / "art.png")
    _attach_favorite_services(app, conn)
    alice = _user_headers(app, conn, "alice")
    bob = _user_headers(app, conn, "bob")
    client = await _make_client(app)
    try:
        added = await client.post(
            "/api/favorites", json={"path": "collection"}, headers=alice
        )
        assert added.status == 200
        assert await added.json() == {
            "ok": True,
            "path": "collection",
            "favorite": True,
            "changed": True,
        }

        duplicate = await client.post(
            "/api/favorites", json={"path": "collection"}, headers=alice
        )
        assert duplicate.status == 200
        assert (await duplicate.json())["changed"] is False

        bob_empty = await client.get("/api/favorites", headers=bob)
        assert bob_empty.status == 200
        assert await bob_empty.json() == {"favorites": []}

        bob_add = await client.post(
            "/api/favorites", json={"path": "collection/art.png"}, headers=bob
        )
        assert bob_add.status == 200

        alice_list = await client.get("/api/favorites", headers=alice)
        assert alice_list.status == 200
        assert alice_list.headers["Cache-Control"] == "private, no-store"
        alice_payload = await alice_list.json()
        assert [entry["path"] for entry in alice_payload["favorites"]] == [
            "collection"
        ]
        assert alice_payload["favorites"][0]["kind"] in {"collection", "project"}
        assert str(library.resolve()) not in str(alice_payload)

        bob_list = await client.get("/api/favorites", headers=bob)
        assert [entry["path"] for entry in (await bob_list.json())["favorites"]] == [
            "collection/art.png"
        ]
    finally:
        await client.close()


@pytest.mark.anyio
async def test_favorite_routes_support_both_remove_contracts(tmp_path):
    app, library, conn = _make_lan_app(tmp_path)
    (library / "collection").mkdir()
    _attach_favorite_services(app, conn)
    headers = _user_headers(app, conn, "alice")
    client = await _make_client(app)
    try:
        await client.post(
            "/api/favorites", json={"path": "collection"}, headers=headers
        )

        removed = await client.post(
            "/api/favorites/remove",
            json={"path": "collection"},
            headers=headers,
        )
        assert removed.status == 200
        assert await removed.json() == {
            "ok": True,
            "path": "collection",
            "favorite": False,
            "changed": True,
        }

        missing = await client.delete(
            "/api/favorites?path=collection", headers=headers
        )
        assert missing.status == 200
        assert (await missing.json())["changed"] is False
    finally:
        await client.close()


@pytest.mark.anyio
async def test_favorite_routes_validate_paths_and_target_types(tmp_path):
    app, library, conn = _make_lan_app(tmp_path)
    (library / "notes.txt").write_text("notes", encoding="utf-8")
    _attach_favorite_services(app, conn)
    headers = _user_headers(app, conn, "alice")
    client = await _make_client(app)
    try:
        invalid_body = await client.post(
            "/api/favorites", json={}, headers=headers
        )
        assert invalid_body.status == 400

        root = await client.post(
            "/api/favorites", json={"path": "."}, headers=headers
        )
        assert root.status == 400

        missing = await client.post(
            "/api/favorites", json={"path": "missing"}, headers=headers
        )
        assert missing.status == 404

        # Regular files of every category are favoritable now; the earlier
        # image-only whitelist returned 400 here.
        regular_file = await client.post(
            "/api/favorites", json={"path": "notes.txt"}, headers=headers
        )
        assert regular_file.status == 200

        escape = await client.post(
            "/api/favorites", json={"path": "../outside"}, headers=headers
        )
        assert escape.status == 400
    finally:
        await client.close()
