"""Regression tests for low-batch defects in core/project_data.py.

Covers four defects:

* Bug 20: the persisted-size check compared the directory mtime with ``>=``,
  so a backwards mtime drift (clock skew, restoring an older snapshot) still
  served the stale cached size; the check now requires an exact ``==`` match.
* Bug 21: ``get_urls`` trusted ``json.loads`` output to be a list; a valid
  JSON non-list payload (e.g. ``{"x": 1}``) made ``add_url``/``remove_url``
  raise AttributeError on ``list.append``/``list.remove``.
* Bug 22: ``compute_dir_size`` recursed without a depth budget; a
  pathologically deep tree could exhaust the recursion stack.
* Bug 23: evaluated case-normalizing ``_key`` with ``os.path.normcase`` and
  rejected it — ``MetadataRepository`` keys the same ``file_meta`` table
  with non-normcased ``resolve()`` paths, so the drive-letter case fold
  would break cross-component reads. ``Path.resolve()`` already
  canonicalizes to the on-disk case on Windows; the tests below lock in the
  shared-key contract.
"""
from __future__ import annotations

import logging
import os
import sqlite3

import pytest

from AssetsManager.core import database


def _memory_conn() -> sqlite3.Connection:
    """Fresh in-memory DB with the file_meta schema.

    Note: ``migrate()`` is intentionally not run — its full-schema validation
    is coupled to unrelated in-flight commerce schema changes in this working
    tree; these tests only exercise ``file_meta``, which ``database._SCHEMA``
    already creates with all required columns (notes, urls, cached_size,
    cached_mtime).
    """
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(database._SCHEMA)
    return conn


def _make_pd(lib_root, conn):
    from AssetsManager.core.project_data import ProjectData

    return ProjectData(str(lib_root), db_conn=conn)


def _seed_non_list_urls(pd, conn, path: str) -> None:
    """Insert a legal JSON non-list payload into file_meta.urls."""
    conn.execute(
        "INSERT INTO file_meta (file_path, urls) VALUES (?, ?)",
        (pd._key(path), '{"x": 1}'),
    )
    conn.commit()


# ── Bug 21: non-list urls payload ────────────────────────────────


def test_get_urls_returns_empty_for_non_list_payload(tmp_path):
    conn = _memory_conn()
    try:
        pd = _make_pd(tmp_path, conn)
        path = str(tmp_path / "asset.bin")
        _seed_non_list_urls(pd, conn, path)

        assert pd.get_urls(path) == []
    finally:
        conn.close()


def test_get_urls_logs_debug_for_non_list_payload(tmp_path, caplog):
    conn = _memory_conn()
    try:
        pd = _make_pd(tmp_path, conn)
        path = str(tmp_path / "asset.bin")
        _seed_non_list_urls(pd, conn, path)

        with caplog.at_level(logging.DEBUG, logger="AssetsManager.core.project_data"):
            pd.get_urls(path)
        assert any("not a JSON list" in record.message for record in caplog.records)
    finally:
        conn.close()


def test_add_url_does_not_raise_on_non_list_payload(tmp_path):
    conn = _memory_conn()
    try:
        pd = _make_pd(tmp_path, conn)
        path = str(tmp_path / "asset.bin")
        _seed_non_list_urls(pd, conn, path)

        # Pre-fix: add_url -> urls.append raised AttributeError on the dict.
        pd.add_url(path, "https://example.com")
        assert pd.get_urls(path) == ["https://example.com"]
    finally:
        conn.close()


def test_remove_url_does_not_raise_on_non_list_payload(tmp_path):
    conn = _memory_conn()
    try:
        pd = _make_pd(tmp_path, conn)
        path = str(tmp_path / "asset.bin")
        _seed_non_list_urls(pd, conn, path)

        # Pre-fix: remove_url -> urls.remove raised AttributeError on the dict.
        pd.remove_url(path, "https://example.com")
        assert pd.get_urls(path) == []
    finally:
        conn.close()


def test_get_urls_still_returns_empty_on_invalid_json(tmp_path):
    conn = _memory_conn()
    try:
        pd = _make_pd(tmp_path, conn)
        path = str(tmp_path / "asset.bin")
        conn.execute(
            "INSERT INTO file_meta (file_path, urls) VALUES (?, ?)",
            (pd._key(path), "{not json"),
        )
        conn.commit()

        assert pd.get_urls(path) == []
    finally:
        conn.close()


# ── Bug 22: compute_dir_size depth budget ────────────────────────


def test_compute_dir_size_obeys_depth_budget(tmp_path, monkeypatch):
    from AssetsManager.core.project_data import ProjectData

    # Shrink the budget instead of building a >64-level real tree (Windows
    # MAX_PATH makes deep fixtures unreliable).
    import AssetsManager.core.project_data as project_data_module

    monkeypatch.setattr(project_data_module, "_MAX_SIZE_DEPTH", 2)

    root = tmp_path / "root"
    (root / "a" / "b" / "c" / "d").mkdir(parents=True)
    (root / "f0.bin").write_bytes(b"1")  # depth 0 -> counted
    (root / "a" / "f1.bin").write_bytes(b"22")  # depth 1 -> counted
    (root / "a" / "b" / "f2.bin").write_bytes(b"4444")  # depth 2 -> counted
    (root / "a" / "b" / "c" / "f3.bin").write_bytes(b"88888888")  # depth 3 -> omitted
    (root / "a" / "b" / "c" / "d" / "f4.bin").write_bytes(b"x" * 16)  # depth 4 -> omitted

    # Pre-fix this still returned 1+2+4+8+16; with the budget only levels
    # 0..2 contribute and the walk never raises RecursionError.
    assert ProjectData.compute_dir_size(str(root)) == 1 + 2 + 4


# ── Bug 23: _key case normalization contract ─────────────────────
#
# A normcase-only change was evaluated and rejected: MetadataRepository, the
# primary file_meta access path, keys rows with str(Path(...).resolve())
# without case folding. normcase would lowercase the drive letter (C:\ vs
# c:\) and strand rows written by MetadataService, breaking cross-component
# reads on Windows. Case dedup for existing files is already provided by
# Path.resolve(), which canonicalizes to the on-disk case on Windows. These
# tests lock in the shared-key contract and the resolve()-based dedup.


def test_key_matches_metadata_repository_key(tmp_path):
    """ProjectData and MetadataRepository must address rows with the same key.

    Regression guard for the cross-component contract exercised by
    tests/integration/test_metadata_service.py: a ProjectData write must be
    readable through MetadataRepository (and vice versa).
    """
    from AssetsManager.core.project_data import ProjectData
    from AssetsManager.repositories.metadata_repository import MetadataRepository

    conn = _memory_conn()
    try:
        path = tmp_path / "asset.bin"
        path.write_bytes(b"x")

        pd_key = ProjectData(str(tmp_path), db_conn=conn)._key(str(path))
        repo = MetadataRepository(conn=conn, library_root=str(tmp_path))
        repo_key = repo._path_key(str(path))

        assert pd_key == repo_key
    finally:
        conn.close()


@pytest.mark.skipif(
    os.name != "nt",
    reason="resolve() on-disk case canonicalization is Windows-specific",
)
def test_key_dedups_case_variants_of_existing_file(tmp_path):
    """On Windows, Path.resolve() canonicalizes to the on-disk case, so case
    variants of an existing file already share one key without normcase."""
    conn = _memory_conn()
    try:
        pd = _make_pd(tmp_path, conn)
        path = tmp_path / "Test.TXT"
        path.write_text("x", encoding="utf-8")

        assert pd._key(str(path)) == pd._key(str(path.with_name("test.txt")))
    finally:
        conn.close()


# ── Bug 20: directory mtime drift invalidates cached size ────────


def test_dir_size_cache_invalidates_on_backwards_mtime_drift(tmp_path):
    conn = _memory_conn()
    try:
        pd = _make_pd(tmp_path, conn)
        folder = tmp_path / "folder"
        folder.mkdir()
        (folder / "asset.bin").write_bytes(b"1234")

        assert pd.get_dir_size(str(folder)) == (4, False)
        assert pd.get_dir_size(str(folder)) == (4, True)  # fresh hit inside TTL

        # Backwards mtime drift (clock skew / restoring an older snapshot):
        # the exact-match check must invalidate; the pre-fix >= comparison
        # served the stale cached value here.
        old = os.path.getmtime(folder)
        os.utime(folder, (old - 200.0, old - 200.0))

        assert pd.get_dir_size(str(folder)) == (4, False)
    finally:
        conn.close()
