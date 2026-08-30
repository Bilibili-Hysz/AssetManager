"""Integration tests for the collection repository (migration v38 tables)."""
import sqlite3

import pytest

from AssetsManager.domain.errors import DuplicateError, NotFoundError
from AssetsManager.repositories.collection_repository import CollectionRepository


def _memory_conn() -> sqlite3.Connection:
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(database._SCHEMA)
    migrate(conn)
    return conn


def _repo(conn: sqlite3.Connection) -> CollectionRepository:
    return CollectionRepository(conn)


def test_create_manual_and_smart_collections_with_defaults(tmp_path):
    conn = _memory_conn()
    try:
        repo = _repo(conn)
        manual = repo.create("manual", "hero shots", "{}")
        smart = repo.create("smart", "big pngs", '{"extensions": [".png"]}')

        assert manual["kind"] == "manual"
        assert manual["query_json"] == "{}"
        assert manual["member_count"] == 0
        assert smart["kind"] == "smart"
        assert smart["query_json"] == '{"extensions": [".png"]}'

        listed = repo.list_collections()
        assert [c["name"] for c in listed] == ["big pngs", "hero shots"]
        assert listed[0]["member_count"] == 0

        assert repo.get(manual["id"])["name"] == "hero shots"
        assert repo.get(9999) is None
    finally:
        conn.close()


def test_create_rejects_duplicate_names(tmp_path):
    conn = _memory_conn()
    try:
        repo = _repo(conn)
        repo.create("manual", "hero", "{}")
        with pytest.raises(DuplicateError, match="Duplicate collection: hero"):
            repo.create("smart", "hero", "{}")
        assert len(repo.list_collections()) == 1
    finally:
        conn.close()


def test_create_rejects_unknown_kind():
    conn = _memory_conn()
    try:
        with pytest.raises(ValueError, match="unknown collection kind"):
            _repo(conn).create("wishlist", "nope", "{}")
    finally:
        conn.close()


def test_rename_updates_name_and_rejects_duplicates_and_missing():
    conn = _memory_conn()
    try:
        repo = _repo(conn)
        first = repo.create("manual", "alpha", "{}")
        second = repo.create("manual", "beta", "{}")

        repo.rename(first["id"], "alpha2")
        assert repo.get(first["id"])["name"] == "alpha2"

        with pytest.raises(DuplicateError, match="alpha2"):
            repo.rename(second["id"], "alpha2")
        with pytest.raises(NotFoundError, match="collection not found"):
            repo.rename(4242, "ghost")

        # Same-name rename of the row itself is a no-op success.
        repo.rename(first["id"], "alpha2")
    finally:
        conn.close()


def test_set_query_only_touches_target_row():
    conn = _memory_conn()
    try:
        repo = _repo(conn)
        smart = repo.create("smart", "query", "{}")
        other = repo.create("manual", "plain", "{}")

        repo.set_query(smart["id"], '{"extensions": [".png"]}')
        assert repo.get(smart["id"])["query_json"] == '{"extensions": [".png"]}'
        assert repo.get(other["id"])["query_json"] == "{}"

        with pytest.raises(NotFoundError):
            repo.set_query(4242, "{}")
    finally:
        conn.close()


def test_add_members_deduplicates_and_counts(tmp_path):
    conn = _memory_conn()
    try:
        repo = _repo(conn)
        collection = repo.create("manual", "refs", "{}")
        asset = tmp_path / "asset.png"
        asset.write_bytes(b"png")

        assert repo.add_members(collection["id"], [str(asset)]) == 1
        # Re-adding the same reference is an idempotent no-op.
        assert repo.add_members(collection["id"], [str(asset)]) == 0
        assert repo.add_members(collection["id"], [str(asset), str(asset)]) == 0
        assert repo.count_members(collection["id"]) == 1
        assert repo.list_collections()[0]["member_count"] == 1

        with pytest.raises(NotFoundError):
            repo.add_members(4242, [str(asset)])
    finally:
        conn.close()


def test_get_members_orders_by_added_at(tmp_path):
    conn = _memory_conn()
    try:
        repo = _repo(conn)
        collection = repo.create("manual", "ordered", "{}")
        # Explicit added_at stamps keep the ordering contract deterministic
        # (wall-clock time.time() can collapse within its resolution).
        conn.executemany(
            "INSERT INTO asset_collection_members "
            "(collection_id, file_path, added_at) VALUES (?, ?, ?)",
            [
                (collection["id"], str(tmp_path / "c.png"), 3.0),
                (collection["id"], str(tmp_path / "a.png"), 1.0),
                (collection["id"], str(tmp_path / "b.png"), 2.0),
            ],
        )

        members = repo.get_members(collection["id"])
        assert [m["file_path"] for m in members] == [
            str(tmp_path / "a.png"),
            str(tmp_path / "b.png"),
            str(tmp_path / "c.png"),
        ]
        assert [m["added_at"] for m in members] == [1.0, 2.0, 3.0]
    finally:
        conn.close()


def test_remove_members_removes_only_targets(tmp_path):
    conn = _memory_conn()
    try:
        repo = _repo(conn)
        collection = repo.create("manual", "refs", "{}")
        keep = tmp_path / "keep.png"
        drop = tmp_path / "drop.png"
        repo.add_members(collection["id"], [str(keep), str(drop)])

        assert repo.remove_members(collection["id"], [str(drop), str(drop)]) == 1
        # Removing a path that is not a member is an idempotent no-op.
        assert repo.remove_members(collection["id"], [str(drop)]) == 0
        assert [
            m["file_path"] for m in repo.get_members(collection["id"])
        ] == [str(keep)]
    finally:
        conn.close()


def test_delete_cascades_membership_rows():
    conn = _memory_conn()
    try:
        repo = _repo(conn)
        collection = repo.create("manual", "doomed", "{}")
        repo.add_members(collection["id"], ["/lib/a.png", "/lib/b.png"])

        assert repo.delete(collection["id"]) is True
        assert repo.delete(collection["id"]) is False
        assert conn.execute(
            "SELECT COUNT(*) FROM asset_collection_members"
        ).fetchone() == (0,)
    finally:
        conn.close()


def test_path_containment_rejects_paths_outside_root(tmp_path):
    conn = _memory_conn()
    try:
        outside = tmp_path / "outside.png"
        outside.write_bytes(b"png")
        root = tmp_path / "library"
        root.mkdir()
        repo = CollectionRepository(conn, library_root=str(root))
        collection = repo.create("manual", "contained", "{}")
        with pytest.raises(ValueError, match="must be under library_root"):
            repo.add_members(collection["id"], [str(outside)])
        assert repo.count_members(collection["id"]) == 0
    finally:
        conn.close()
