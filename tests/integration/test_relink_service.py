"""H2-b relink service: broken-link scan, pairing suggestions, relink action.

Covers the product contract on a real migrated schema (``schema_db``) plus a
scratch library on disk: external moves create metadata orphans that pair
with newcomer files, relinking migrates every projection to the new path in
one transaction, and a failed migration rolls the whole pair back.
"""
import os
from pathlib import Path

import pytest

from AssetsManager.application.asset_index_service import AssetIndexService
from AssetsManager.application.relink_service import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    LostEntry,
    NewcomerEntry,
    RelinkTargetMissingError,
    relink,
    scan,
    suggest_pairs,
)


def _index_library(conn, lib):
    AssetIndexService().index_directory(conn, lib, lib)


def _rows(conn, sql, params=()):
    return conn.execute(sql, params).fetchall()


def _resolve(*parts):
    return str(Path(*parts).resolve())


def test_scan_reports_orphan_newcomer_and_high_pair(schema_db, tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    hero = lib / "hero.png"
    hero.write_bytes(b"A" * 100)
    _index_library(schema_db, lib)

    old_path = _resolve(hero)
    schema_db.execute(
        "INSERT INTO file_meta (file_path, notes, urls, rating) VALUES (?,?,?,?)",
        (old_path, "production notes", '["https://example.test"]', 4))
    schema_db.execute(
        "INSERT INTO file_tags (file_path, tag) VALUES (?,?)", (old_path, "art"))
    conn = schema_db
    conn.commit()

    # The user moves the file outside the app.
    new_disk_path = lib / "hero_moved.png"
    os.rename(hero, new_disk_path)

    report = scan(conn, lib)

    assert [entry.file_path for entry in report.lost] == [old_path]
    assert [entry.file_path for entry in report.newcomers] == [
        _resolve(new_disk_path)]
    assert report.missing_index_rows == 1
    assert len(report.suggestions) == 1
    suggestion = report.suggestions[0]
    assert suggestion.confidence == CONFIDENCE_HIGH
    assert suggestion.lost.file_path == old_path
    assert suggestion.newcomer.file_path == _resolve(new_disk_path)
    assert not report.unpaired_lost
    assert not report.truncated


def test_scan_counts_pure_index_rows_but_does_not_report_them(
        schema_db, tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    plain = lib / "plain.txt"
    plain.write_text("x")
    marked = lib / "marked.txt"
    marked.write_bytes(b"12345678")
    _index_library(schema_db, lib)
    schema_db.execute(
        "INSERT INTO file_tags (file_path, tag) VALUES (?,?)",
        (_resolve(marked), "keep"))
    schema_db.commit()

    # The unmarked file is deleted: a missing pure index row, diagnostic only.
    os.unlink(plain)
    # The tagged file is moved into a subfolder and rewritten in place with
    # equal size — same name + size but a fresh mtime, so only the weak rule
    # can pair it (cross-drive / editor-rewrite scenario).
    sub = lib / "moved"
    sub.mkdir()
    moved = sub / "marked.txt"
    os.rename(marked, moved)
    moved.write_bytes(b"87654321")

    report = scan(schema_db, lib)

    assert [entry.file_path for entry in report.lost] == [_resolve(marked)]
    assert report.missing_index_rows == 2
    assert len(report.suggestions) == 1
    assert report.suggestions[0].confidence == CONFIDENCE_LOW
    assert report.suggestions[0].newcomer.file_path == _resolve(moved)


def test_scan_skips_hidden_entries(schema_db, tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / ".hidden_dir").mkdir()
    (lib / ".hidden_dir" / "secret.txt").write_text("s")
    (lib / ".dotfile").write_text("d")
    _index_library(schema_db, lib)

    report = scan(schema_db, lib)

    assert report.newcomers == ()
    assert report.lost == ()
    assert report.missing_index_rows == 0


def test_scan_detects_lost_paths_beyond_walk_budget(schema_db, tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    marked = lib / "marked.txt"
    marked.write_text("y")
    _index_library(schema_db, lib)
    schema_db.execute(
        "INSERT INTO file_tags (file_path, tag) VALUES (?,?)",
        (_resolve(marked), "keep"))
    schema_db.commit()
    os.rename(marked, lib / "marked_moved.txt")

    # max_dirs=0 exhausts the budget before any directory is walked; the
    # exists() probe still separates truly-lost rows from unvisited ones.
    report = scan(schema_db, lib, max_dirs=0)

    assert report.truncated is True
    assert [entry.file_path for entry in report.lost] == [_resolve(marked)]
    assert report.newcomers == ()
    assert not report.suggestions


def test_suggest_pairs_priority_and_ambiguity():
    lost_a = LostEntry("/lib/a.png", "a.png", "file", 10, 100.0, True, False)
    lost_b = LostEntry("/lib/b.png", "b.png", "file", 10, 200.0, True, False)
    lost_kept_name = LostEntry(
        "/lib/old.png", "old.png", "file", 7, 500.0, True, True)
    near_a = NewcomerEntry("/lib2/a.png", "a.png", 10, int(100.0 * 1e9))
    near_b = NewcomerEntry("/lib2/b.png", "b.png", 10, int(200.0 * 1e9))
    # Same name + size, but the mtime changed (editor rewrote it): only the
    # weak name rule pairs it, with no directory-identity signal.
    rewritten = NewcomerEntry(
        "/lib2/old.png", "old.png", 7, int(999.0 * 1e9))

    # Same size + mtime beats the name rule; the rewritten case falls to the
    # weak name rule. mtime float→ns round-trip noise stays in tolerance.
    pairs = suggest_pairs([lost_a, lost_b, lost_kept_name],
                          [near_b, near_a, rewritten])
    assert [(s.lost.file_path, s.newcomer.file_path, s.confidence)
            for s in pairs] == [
        ("/lib/a.png", "/lib2/a.png", CONFIDENCE_HIGH),
        ("/lib/b.png", "/lib2/b.png", CONFIDENCE_HIGH),
        ("/lib/old.png", "/lib2/old.png", CONFIDENCE_LOW),
    ]

    # Ambiguous groups pair with nothing: two same-name same-size newcomers.
    ambiguous = NewcomerEntry("/lib2/copy-1.png", "old.png", 7, 1)
    other = NewcomerEntry("/lib2/copy-2.png", "old.png", 7, 2)
    assert suggest_pairs([lost_kept_name], [ambiguous, other]) == []

    # Each newcomer is claimed at most once.
    clone = LostEntry("/lib/a2.png", "a.png", "file", 10, 100.0, True, False)
    pairs = suggest_pairs([lost_a, clone], [near_a])
    assert len(pairs) == 1
    assert pairs[0].lost.file_path == "/lib/a.png"


def test_relink_migrates_every_projection_to_the_new_path(
        schema_db, tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    hero = lib / "hero.png"
    hero.write_bytes(b"A" * 100)
    _index_library(schema_db, lib)

    old_path = _resolve(hero)
    schema_db.execute(
        "INSERT INTO file_meta (file_path, notes, urls, rating) "
        "VALUES (?,?,?,?)", (old_path, "keep these notes", "[]", 5))
    schema_db.execute(
        "INSERT INTO file_tags (file_path, tag) VALUES (?,?)",
        (old_path, "art"))
    schema_db.execute(
        "INSERT INTO file_tags (file_path, tag) VALUES (?,?)",
        (old_path, "props"))
    schema_db.execute(
        "INSERT INTO library_favorites (owner_key, file_path, created_at) "
        "VALUES (?,?,?)", ("guest", old_path, 42.0))
    schema_db.commit()

    new_disk_path = lib / "sub" / "hero-moved.png"
    new_disk_path.parent.mkdir()
    os.rename(hero, new_disk_path)
    new_path = _resolve(new_disk_path)

    assert relink(
        schema_db,
        library_root=lib,
        thumb_dir=tmp_path / "thumbs",
        old_path=old_path,
        new_path=new_disk_path,
    ) is True

    # Metadata rows byte-level moved to the new path, nothing left behind.
    meta_rows = _rows(schema_db, "SELECT file_path, notes, urls, rating "
                                 "FROM file_meta")
    assert meta_rows == [(new_path, "keep these notes", "[]", 5)]
    assert _rows(schema_db, "SELECT file_path, tag FROM file_tags "
                            "ORDER BY tag") == [
        (new_path, "art"), (new_path, "props")]
    assert _rows(schema_db, "SELECT owner_key, file_path, created_at "
                            "FROM library_favorites") == [
        ("guest", new_path, 42.0)]
    # The index row followed the file (path/parent/name/ext) with a fresh
    # stat of the same content, and the old path has no residue anywhere.
    index_rows = _rows(schema_db, "SELECT file_path, name, extension, "
                                  "parent_path, size FROM assets")
    assert index_rows == [(
        new_path, "hero-moved.png", ".png", str(new_disk_path.parent), 100)]
    revision = _rows(schema_db, "SELECT revision FROM asset_index_state")
    assert revision and revision[0][0] >= 1
    assert os.path.isfile(new_disk_path)


def test_relink_rolls_back_the_whole_pair_on_failure(
        schema_db, tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    lib.mkdir()
    hero = lib / "hero.png"
    hero.write_bytes(b"A" * 100)
    _index_library(schema_db, lib)
    old_path = _resolve(hero)
    schema_db.execute(
        "INSERT INTO file_meta (file_path, notes, rating) VALUES (?,?,?)",
        (old_path, "notes", 3))
    schema_db.commit()

    new_disk_path = lib / "hero-moved.png"
    os.rename(hero, new_disk_path)
    before = _rows(schema_db, "SELECT file_path, notes, rating FROM file_meta")
    revision_before = _rows(
        schema_db, "SELECT revision FROM asset_index_state")

    def _boom(*_args, **_kwargs):
        raise RuntimeError("migration exploded")

    monkeypatch.setattr(
        "AssetsManager.core.database._migrate_path_metadata_impl", _boom)
    with pytest.raises(RuntimeError, match="migration exploded"):
        relink(
            schema_db,
            library_root=lib,
            thumb_dir=tmp_path / "thumbs",
            old_path=old_path,
            new_path=new_disk_path,
        )
    monkeypatch.undo()

    # Both the metadata remap and the index repoint rolled back.
    assert _rows(schema_db, "SELECT file_path, notes, rating FROM file_meta") \
        == before
    assert _rows(schema_db, "SELECT file_path, parent_path FROM assets") == [
        (old_path, str(lib.resolve()))]
    assert _rows(schema_db, "SELECT revision FROM asset_index_state") \
        == revision_before


def test_relink_refuses_missing_target_and_same_path(schema_db, tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    hero = lib / "hero.png"
    hero.write_bytes(b"A" * 100)
    _index_library(schema_db, lib)
    old_path = _resolve(hero)

    with pytest.raises(RelinkTargetMissingError):
        relink(
            schema_db,
            library_root=lib,
            thumb_dir=tmp_path / "thumbs",
            old_path=old_path,
            new_path=lib / "never-created.png",
        )
    # Identical paths are a no-op, not an error.
    assert relink(
        schema_db,
        library_root=lib,
        thumb_dir=tmp_path / "thumbs",
        old_path=old_path,
        new_path=hero,
    ) is False
    assert _rows(schema_db, "SELECT file_path FROM assets") == [(old_path,)]