"""Tests for AssetIndexService."""
from AssetsManager.application.asset_index_service import AssetIndexService


def test_index_directory_populates_assets_table(tmp_path, schema_db):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "photo.jpg").write_bytes(b"jpg")
    (lib / "readme.txt").write_text("txt")
    (lib / "sub").mkdir()

    conn = schema_db
    svc = AssetIndexService()
    count = svc.index_directory(conn, lib, lib)

    assert count == 3
    assert svc.count(conn, lib) == 3


def test_index_directory_skips_if_already_indexed(tmp_path, schema_db):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "file.txt").write_text("x")

    conn = schema_db
    svc = AssetIndexService()
    svc.index_directory(conn, lib, lib)

    count = svc.index_directory(conn, lib, lib, force=False)
    assert count == 1
    assert svc.count(conn, lib) == 1


def test_index_directory_force_reindexes(tmp_path, schema_db):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "file.txt").write_text("x")

    conn = schema_db
    svc = AssetIndexService()
    svc.index_directory(conn, lib, lib)
    (lib / "new.txt").write_text("y")
    count = svc.index_directory(conn, lib, lib, force=True)

    assert count == 2
    assert svc.count(conn, lib) == 2


def test_force_index_removes_stale_entries_from_parent(tmp_path, schema_db):
    lib = tmp_path / "lib"
    stale = lib / "stale.txt"
    lib.mkdir()
    stale.write_text("x")

    svc = AssetIndexService()
    svc.index_directory(schema_db, lib, lib)
    stale.unlink()

    svc.index_directory(schema_db, lib, lib, force=True)

    assert svc.get_entry(schema_db, stale) is None


def test_query_by_parent(tmp_path, schema_db):
    lib = tmp_path / "lib"
    sub = lib / "sub"
    sub.mkdir(parents=True)
    (lib / "a.txt").write_text("a")
    (sub / "b.txt").write_text("b")

    conn = schema_db
    svc = AssetIndexService()
    svc.index_directory(conn, lib, lib)
    svc.index_directory(conn, lib, sub)

    root_items = svc.query_by_parent(conn, lib, lib)
    sub_items = svc.query_by_parent(conn, lib, sub)

    assert len(root_items) == 2  # a.txt + sub/
    assert len(sub_items) == 1
    assert sub_items[0].name == "b.txt"


def test_query_by_extension(tmp_path, schema_db):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "a.jpg").write_bytes(b"a")
    (lib / "b.jpg").write_bytes(b"b")
    (lib / "c.txt").write_text("c")

    conn = schema_db
    svc = AssetIndexService()
    svc.index_directory(conn, lib, lib)

    jpgs = svc.query_by_extension(conn, lib, ".jpg")
    assert len(jpgs) == 2


def test_search_by_name(tmp_path, schema_db):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "hero_idle.png").write_bytes(b"a")
    (lib / "hero_attack.png").write_bytes(b"b")
    (lib / "villain_idle.png").write_bytes(b"c")

    conn = schema_db
    svc = AssetIndexService()
    svc.index_directory(conn, lib, lib)

    results = svc.search_by_name(conn, lib, "hero")
    assert len(results) == 2


def test_remove_entry(tmp_path, schema_db):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "file.txt").write_text("x")

    conn = schema_db
    svc = AssetIndexService()
    svc.index_directory(conn, lib, lib)
    assert svc.count(conn, lib) == 1

    svc.remove_entry(conn, lib / "file.txt")
    assert svc.count(conn, lib) == 0


def test_remove_directory(tmp_path, schema_db):
    lib = tmp_path / "lib"
    sub = lib / "sub"
    sub.mkdir(parents=True)
    (sub / "a.txt").write_text("a")
    (sub / "b.txt").write_text("b")

    conn = schema_db
    svc = AssetIndexService()
    svc.index_directory(conn, lib, sub)

    removed = svc.remove_directory(conn, sub)
    assert removed == 2
    assert svc.count(conn, lib) == 0


def test_get_entry(tmp_path, schema_db):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "photo.jpg").write_bytes(b"jpg")

    conn = schema_db
    svc = AssetIndexService()
    svc.index_directory(conn, lib, lib)

    entry = svc.get_entry(conn, lib / "photo.jpg")
    assert entry is not None
    assert entry.name == "photo.jpg"
    assert entry.extension == ".jpg"
    assert entry.kind == "file"

    assert svc.get_entry(conn, lib / "missing.txt") is None
