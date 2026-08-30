"""LAN route tests for /api/collections and its subresources."""
from __future__ import annotations

import pytest

from tests.lan.support.api_helpers import _make_client, _make_lan_app, _local_ui_headers


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _index_asset(conn, library, name: str) -> str:
    path = library / name
    path.write_text("data", encoding="utf-8")
    # Seed the assets index directly. The index table arrives via migration
    # v2 and the LAN fixture runs the bare baseline _SCHEMA, so create the
    # migrated shape locally instead of perturbing the shared fixture (an
    # existing-but-empty assets table changes the /api/search status contract).
    conn.execute(
        "CREATE TABLE IF NOT EXISTS assets ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "file_path TEXT NOT NULL UNIQUE, "
        "name TEXT NOT NULL, "
        "extension TEXT NOT NULL DEFAULT '', "
        "kind TEXT NOT NULL DEFAULT 'file', "
        "size INTEGER DEFAULT 0, "
        "mtime REAL DEFAULT 0, "
        "parent_path TEXT NOT NULL, "
        "library_root TEXT NOT NULL, "
        "created_at REAL DEFAULT (strftime('%s','now')), "
        "updated_at REAL DEFAULT (strftime('%s','now')))"
    )
    conn.execute(
        "INSERT INTO assets (file_path, name, extension, kind, size, mtime, "
        "parent_path, library_root) VALUES (?, ?, ?, 'file', ?, ?, ?, ?)",
        (
            str(path),
            path.stem,
            path.suffix,
            path.stat().st_size,
            path.stat().st_mtime,
            str(library),
            str(library),
        ),
    )
    conn.commit()
    return str(path)


@pytest.mark.anyio
async def test_collection_crud_and_members_over_lan(tmp_path):
    app, library, conn = _make_lan_app(tmp_path)
    asset = library / "a.png"
    asset.write_bytes(b"png")
    client = await _make_client(app)
    try:
        # Writes require user-write; anonymous callers are rejected.
        anonymous = await client.post("/api/collections", json={"name": "hero"})
        assert anonymous.status == 403

        created = await client.post(
            "/api/collections",
            json={"name": "hero"},
            headers=_local_ui_headers(app),
        )
        assert created.status == 201
        collection = (await created.json())["collection"]
        assert collection["kind"] == "manual"
        assert collection["member_count"] == 0
        collection_id = collection["id"]

        duplicate = await client.post(
            "/api/collections",
            json={"name": "hero"},
            headers=_local_ui_headers(app),
        )
        assert duplicate.status == 409

        listed = await client.get("/api/collections", headers=_local_ui_headers(app))
        assert listed.status == 200
        assert [c["name"] for c in (await listed.json())["collections"]] == ["hero"]

        added = await client.post(
            f"/api/collections/{collection_id}/members",
            json={"paths": ["a.png"]},
            headers=_local_ui_headers(app),
        )
        assert added.status == 200
        assert (await added.json())["added"] == 1

        members = await client.get(
            f"/api/collections/{collection_id}/members",
            headers=_local_ui_headers(app),
        )
        assert members.status == 200
        member_rows = (await members.json())["members"]
        assert member_rows == [
            {"path": "a.png", "added_at": member_rows[0]["added_at"], "exists": True}
        ]

        renamed = await client.patch(
            f"/api/collections/{collection_id}",
            json={"name": "hero2"},
            headers=_local_ui_headers(app),
        )
        assert renamed.status == 200

        removed = await client.delete(
            f"/api/collections/{collection_id}/members",
            json={"paths": ["a.png"]},
            headers=_local_ui_headers(app),
        )
        assert removed.status == 200
        assert (await removed.json())["removed"] == 1

        deleted = await client.delete(
            f"/api/collections/{collection_id}",
            headers=_local_ui_headers(app),
        )
        assert deleted.status == 200

        missing = await client.get(
            f"/api/collections/{collection_id}/members",
            headers=_local_ui_headers(app),
        )
        assert missing.status == 404

        # The collection is a reference set: the file itself is untouched.
        assert asset.exists()
    finally:
        await client.close()
        conn.close()


@pytest.mark.anyio
async def test_collection_smart_evaluate_over_lan(tmp_path):
    app, library, conn = _make_lan_app(tmp_path)
    _index_asset(conn, library, "a.png")
    _index_asset(conn, library, "b.jpg")
    client = await _make_client(app)
    try:
        created = await client.post(
            "/api/collections",
            json={"name": "pngs", "kind": "smart", "query": {"extensions": [".png"]}},
            headers=_local_ui_headers(app),
        )
        assert created.status == 201
        collection_id = (await created.json())["collection"]["id"]

        evaluated = await client.get(
            f"/api/collections/{collection_id}/evaluate",
            headers=_local_ui_headers(app),
        )
        assert evaluated.status == 200
        results = (await evaluated.json())["results"]
        assert [r["path"] for r in results] == ["a.png"]
        assert results[0]["name"] == "a"

        paged = await client.get(
            f"/api/collections/{collection_id}/evaluate?limit=1&offset=0",
            headers=_local_ui_headers(app),
        )
        assert len((await paged.json())["results"]) == 1

        # Smart collections reject manual membership writes.
        rejected = await client.post(
            f"/api/collections/{collection_id}/members",
            json={"paths": ["a.png"]},
            headers=_local_ui_headers(app),
        )
        assert rejected.status == 400

        # Unknown predicate keys are a client error at creation time.
        bad = await client.post(
            "/api/collections",
            json={"name": "bad", "kind": "smart", "query": {"nope": 1}},
            headers=_local_ui_headers(app),
        )
        assert bad.status == 400
    finally:
        await client.close()
        conn.close()


@pytest.mark.anyio
async def test_collection_list_reports_live_smart_counts(tmp_path):
    """Smart rows carry the evaluated total (asset_count), manual rows do not."""
    app, library, conn = _make_lan_app(tmp_path)
    _index_asset(conn, library, "a.png")
    _index_asset(conn, library, "b.png")
    client = await _make_client(app)
    try:
        created = await client.post(
            "/api/collections",
            json={"name": "pngs", "kind": "smart", "query": {"extensions": [".png"]}},
            headers=_local_ui_headers(app),
        )
        assert created.status == 201

        manual = await client.post(
            "/api/collections",
            json={"name": "refs"},
            headers=_local_ui_headers(app),
        )
        assert manual.status == 201

        listed = await client.get("/api/collections", headers=_local_ui_headers(app))
        assert listed.status == 200
        rows = {c["name"]: c for c in (await listed.json())["collections"]}
        assert rows["pngs"]["asset_count"] == 2
        assert rows["refs"]["asset_count"] is None
        assert rows["refs"]["member_count"] == 0

        # Adding another indexed png bumps the live count on the next list.
        _index_asset(conn, library, "c.png")
        listed = await client.get("/api/collections", headers=_local_ui_headers(app))
        rows = {c["name"]: c for c in (await listed.json())["collections"]}
        assert rows["pngs"]["asset_count"] == 3
    finally:
        await client.close()
        conn.close()


@pytest.mark.anyio
async def test_collection_rating_and_favorite_dimensions_over_lan(tmp_path):
    """rating/favorite predicates evaluate; favorite follows the requester."""
    app, library, conn = _make_lan_app(tmp_path)
    _index_asset(conn, library, "a.png")
    _index_asset(conn, library, "b.png")
    file_paths = {name: str(library / name) for name in ("a.png", "b.png")}
    conn.execute(
        "INSERT INTO file_meta(file_path, rating) VALUES (?, 5)", (file_paths["a.png"],)
    )
    from AssetsManager.core.schema_defs import LIBRARY_FAVORITES_SCHEMA

    for statement in LIBRARY_FAVORITES_SCHEMA.split(";"):
        if sql := statement.strip():
            conn.execute(sql)
    conn.execute(
        "INSERT INTO library_favorites(owner_key, file_path) VALUES (?, ?)",
        ("principal:local_ui", file_paths["b.png"]),
    )
    conn.commit()
    client = await _make_client(app)
    try:
        top = await client.post(
            "/api/collections",
            json={"name": "top", "kind": "smart", "query": {"rating_min": 4}},
            headers=_local_ui_headers(app),
        )
        top_id = (await top.json())["collection"]["id"]
        evaluated = await client.get(
            f"/api/collections/{top_id}/evaluate", headers=_local_ui_headers(app)
        )
        assert [r["path"] for r in (await evaluated.json())["results"]] == ["a.png"]

        mine = await client.post(
            "/api/collections",
            json={"name": "mine", "kind": "smart", "query": {"favorite": True}},
            headers=_local_ui_headers(app),
        )
        mine_id = (await mine.json())["collection"]["id"]
        evaluated = await client.get(
            f"/api/collections/{mine_id}/evaluate", headers=_local_ui_headers(app)
        )
        assert [r["path"] for r in (await evaluated.json())["results"]] == ["b.png"]

        # A guest viewer owns no favorites: their evaluation is empty.
        guest = await client.get(f"/api/collections/{mine_id}/evaluate")
        assert guest.status == 200
        assert (await guest.json())["results"] == []
    finally:
        await client.close()
        conn.close()


@pytest.mark.anyio
async def test_collection_routes_reject_bad_ids_and_bodies(tmp_path):
    app, library, conn = _make_lan_app(tmp_path)
    client = await _make_client(app)
    try:
        bad_id = await client.get(
            "/api/collections/not-an-id/members", headers=_local_ui_headers(app)
        )
        assert bad_id.status == 400

        missing_body = await client.post(
            "/api/collections/1/members", json={}, headers=_local_ui_headers(app)
        )
        assert missing_body.status == 400

        missing_paths = await client.post(
            "/api/collections/1/members",
            json={"paths": ["missing.png"]},
            headers=_local_ui_headers(app),
        )
        assert missing_paths.status == 404

        no_body_patch = await client.patch(
            "/api/collections/1", json={}, headers=_local_ui_headers(app)
        )
        assert no_body_patch.status == 400
    finally:
        await client.close()
        conn.close()
