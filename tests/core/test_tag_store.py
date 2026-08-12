"""Tests for TagStore."""
import os
import sqlite3
import pytest
from AssetsManager.core.tag_store import TagStore


def _clean(s: TagStore, *paths):
    for p in paths:
        s.remove_file(p)


def test_add_get_tags(schema_db):
    s = TagStore("/test/library", db_conn=schema_db)
    _clean(s, "/test/library/file1.png")
    s.add_tag("/test/library/file1.png", "hero")
    s.add_tag("/test/library/file1.png", "villain")
    tags = s.get_tags("/test/library/file1.png")
    assert "hero" in tags
    assert "villain" in tags
    _clean(s, "/test/library/file1.png")


def test_get_tags_for_files(schema_db):
    s = TagStore("/test/library", db_conn=schema_db)
    a = os.path.abspath("/test/library/batch_a.png")
    b = os.path.abspath("/test/library/batch_b.png")
    _clean(s, a, b)
    s.add_tag(a, "hero")
    s.add_tag(b, "villain")

    tags = s.get_tags_for_files([a, b])

    assert tags[a] == ["hero"]
    assert tags[b] == ["villain"]
    _clean(s, a, b)


def test_remove_tag(schema_db):
    s = TagStore("/test/library", db_conn=schema_db)
    _clean(s, "/test/library/file1.png")
    s.add_tag("/test/library/file1.png", "temp")
    s.remove_tag("/test/library/file1.png", "temp")
    assert "temp" not in s.get_tags("/test/library/file1.png")
    _clean(s, "/test/library/file1.png")


def test_get_files_by_tag(schema_db):
    s = TagStore("/test/library", db_conn=schema_db)
    a = os.path.abspath("/test/library/a.png")
    b = os.path.abspath("/test/library/b.png")
    c = os.path.abspath("/test/library/c.png")
    _clean(s, a, b, c)
    s.add_tag(a, "shared")
    s.add_tag(b, "shared")
    s.add_tag(c, "other")
    shared = s.get_files_by_tag("shared")
    assert a in shared
    assert b in shared
    assert c not in shared
    _clean(s, a, b, c)


def test_get_all_tags(schema_db):
    s = TagStore("/test/library", db_conn=schema_db)
    _clean(s, "/test/library/a.png", "/test/library/b.png")
    s.add_tag("/test/library/a.png", "Zebra")
    s.add_tag("/test/library/b.png", "alpha")
    tags = [t.lower() for t in s.get_all_tags()]
    assert "alpha" in tags
    assert "zebra" in tags
    _clean(s, "/test/library/a.png", "/test/library/b.png")


def test_normalize(schema_db):
    s = TagStore("/test/library", db_conn=schema_db)
    _clean(s, "/test/library/f.png")
    s.add_tag("/test/library/f.png", "  Dupe  ")
    s.add_tag("/test/library/f.png", "DUPE")
    assert len(s.get_tags("/test/library/f.png")) == 1
    _clean(s, "/test/library/f.png")


def test_remove_file(schema_db):
    s = TagStore("/test/library", db_conn=schema_db)
    _clean(s, "/test/library/g.png")
    s.add_tag("/test/library/g.png", "label")
    s.remove_file("/test/library/g.png")
    assert "/test/library/g.png" not in s.get_all_tagged_files()
    _clean(s, "/test/library/g.png")


def test_explicit_managed_connection_rejects_different_root(tmp_path):
    from AssetsManager.core.database import DatabaseManager

    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"
    root_a.mkdir()
    root_b.mkdir()
    manager = DatabaseManager()
    try:
        root_b_conn = manager.connection_for(root_b)

        with pytest.raises(ValueError, match="different library root"):
            TagStore(str(root_a), db_conn=root_b_conn)
    finally:
        manager.close()


def test_explicit_managed_connection_accepts_same_root(tmp_path):
    from AssetsManager.core.database import DatabaseManager

    root = tmp_path / "root"
    root.mkdir()
    manager = DatabaseManager()
    try:
        conn = manager.connection_for(root)

        store = TagStore(str(root), db_conn=conn)

        assert store._db is conn
    finally:
        manager.close()


def test_explicit_unmanaged_connection_remains_compatible(tmp_path):
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    try:
        conn.executescript(database._SCHEMA)
        migrate(conn)

        store = TagStore(str(tmp_path), db_conn=conn)

        assert store._db is conn
    finally:
        conn.close()


def test_deprecated_get_store_does_not_retain_process_global_store(tmp_path):
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate
    from AssetsManager.core.tag_store import get_store

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(database._SCHEMA)
    migrate(conn)
    try:
        with pytest.warns(DeprecationWarning, match="get_store"):
            first = get_store(str(tmp_path), db_conn=conn)
        with pytest.warns(DeprecationWarning, match="get_store"):
            second = get_store(str(tmp_path), db_conn=conn)

        assert first is not second
        assert first._db is second._db is conn
    finally:
        conn.close()
