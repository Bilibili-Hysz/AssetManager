"""Low-level DirectoryCache tests: key normalization and batch mtime filtering."""
import os
import sys

import pytest

from AssetsManager.core import database
from AssetsManager.core.db_migrations import migrate
from AssetsManager.core.directory_cache import DirectoryCache

WINDOWS = sys.platform == "win32"


@pytest.fixture(autouse=True)
def _no_probabilistic_prune(monkeypatch):
    """Freeze directory_cache's ~1%-of-reads prune sweep off.

    The legacy-row fixtures below insert ``scanned_at=0.0`` (epoch 1970), so
    a prune sweep firing inside ``cache.get()`` deletes the row under test
    and turns the assertion into a flake. Linux xdist workers are forked and
    inherit identical random state, so the ~1% draw is deterministic per
    interpreter version — this bit the 3.12 CI lane while 3.13/3.14 passed.
    Prune behavior itself is covered by tests that opt into fresh timestamps.
    """
    from AssetsManager.core import directory_cache as directory_cache_module

    monkeypatch.setattr(directory_cache_module.random, "random", lambda: 1.0)


def _migrate_with_baseline(conn):
    conn.executescript(database._SCHEMA)
    return migrate(conn)


# --- Bug 12: cache keys are normalized (absolute + normcase) ---


def test_set_absolute_get_relative_hits(memory_db):
    """Relative and absolute spellings of the same directory share one row."""
    _migrate_with_baseline(memory_db)
    cache = DirectoryCache(memory_db)
    relative = os.path.join("lib", "file.txt")
    absolute = os.path.abspath(relative)

    cache.set(absolute, item_count=7, preview_path=None, mtime=100.0)

    assert cache.get(relative) is not None
    assert cache.get(relative).item_count == 7
    # Single canonical row on disk, not one per spelling.
    rows = memory_db.execute("SELECT count(*) FROM directory_cache").fetchone()[0]
    assert rows == 1


def test_set_relative_get_absolute_hits(memory_db):
    """Writes are normalized too: a relative set is readable via absolute path."""
    _migrate_with_baseline(memory_db)
    cache = DirectoryCache(memory_db)
    relative = os.path.join("lib", "file.txt")
    absolute = os.path.abspath(relative)

    cache.set(relative, item_count=7, preview_path=None, mtime=100.0)

    assert cache.get(absolute) is not None
    assert cache.get(absolute).item_count == 7


@pytest.mark.skipif(not WINDOWS, reason="normcase is identity on case-sensitive platforms")
def test_set_get_matches_case_variant(memory_db):
    """Case variants of the same Windows path hit the same (normcase) key."""
    _migrate_with_baseline(memory_db)
    cache = DirectoryCache(memory_db)

    cache.set(r"C:\LIB\File.txt", item_count=7, preview_path=None, mtime=100.0)

    assert cache.get(r"c:\lib\file.txt") is not None
    assert cache.get(r"c:\lib\file.txt").item_count == 7


@pytest.mark.skipif(not WINDOWS, reason="normcase is identity on case-sensitive platforms")
def test_case_variants_do_not_create_duplicate_rows(memory_db):
    """Upsert via a case-variant key updates the same row instead of duplicating."""
    _migrate_with_baseline(memory_db)
    cache = DirectoryCache(memory_db)

    cache.set(r"C:\LIB\DUP", item_count=1, preview_path=None, mtime=100.0)
    cache.set(r"c:\lib\dup", item_count=2, preview_path=None, mtime=200.0)

    rows = memory_db.execute("SELECT count(*) FROM directory_cache").fetchone()[0]
    assert rows == 1
    assert cache.get(r"c:\lib\dup").item_count == 2


def test_relative_and_absolute_spelling_share_one_row(memory_db):
    """Different spellings of one path update a single row (last write wins)."""
    _migrate_with_baseline(memory_db)
    cache = DirectoryCache(memory_db)
    relative = os.path.join("lib", "dup")
    absolute = os.path.abspath(relative)

    cache.set(relative, item_count=1, preview_path=None, mtime=100.0)
    cache.set(absolute, item_count=2, preview_path=None, mtime=200.0)

    rows = memory_db.execute("SELECT count(*) FROM directory_cache").fetchone()[0]
    assert rows == 1
    assert cache.get(absolute).item_count == 2


def test_get_falls_back_to_legacy_un_normalized_row(memory_db):
    """Rows written before key normalization remain readable via raw-key fallback."""
    _migrate_with_baseline(memory_db)
    legacy_path = os.path.join("legacy", "dir")
    memory_db.execute(
        "INSERT INTO directory_cache (dir_path, item_count, preview_path, mtime, scanned_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (legacy_path, 3, None, 100.0, 0.0),
    )
    memory_db.commit()
    cache = DirectoryCache(memory_db)

    entry = cache.get(legacy_path)

    assert entry is not None
    assert entry.item_count == 3


def test_invalidate_removes_legacy_and_normalized_rows(memory_db):
    """invalidate clears both the canonical key and the legacy raw spelling."""
    _migrate_with_baseline(memory_db)
    legacy_path = os.path.join("legacy", "dir")
    memory_db.execute(
        "INSERT INTO directory_cache (dir_path, item_count, preview_path, mtime, scanned_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (legacy_path, 3, None, 100.0, 0.0),
    )
    memory_db.commit()
    cache = DirectoryCache(memory_db)

    cache.invalidate(legacy_path)

    assert cache.get(legacy_path) is None


def test_get_batch_normalizes_keys_and_keys_result_by_requested_path(memory_db):
    """get_batch finds normalized rows and keys its result by the requested spelling."""
    _migrate_with_baseline(memory_db)
    cache = DirectoryCache(memory_db)
    relative = os.path.join("lib", "batch", "dir")
    absolute = os.path.abspath(relative)

    cache.set(absolute, item_count=9, preview_path=None, mtime=100.0)

    entries = cache.get_batch([relative])

    assert set(entries) == {relative}
    assert entries[relative].item_count == 9


# --- Bug 13: get_batch filters stale rows when mtimes is provided ---


def test_get_batch_filters_stale_rows_by_mtime(memory_db):
    """Hit rows whose stored mtime differs from the expected value are dropped."""
    _migrate_with_baseline(memory_db)
    cache = DirectoryCache(memory_db)
    cache.set_batch([
        ("/lib/fresh", 1, None, 1000.0),
        ("/lib/stale", 2, None, 2000.0),
        ("/lib/noexpect", 3, None, 3000.0),
    ])

    entries = cache.get_batch(
        ["/lib/fresh", "/lib/stale", "/lib/noexpect", "/lib/missing"],
        mtimes={"/lib/fresh": 1000.0, "/lib/stale": 9999.0},
    )

    assert set(entries) == {"/lib/fresh", "/lib/noexpect"}
    assert entries["/lib/fresh"].item_count == 1
    # Paths absent from the mtimes map are not filtered.
    assert entries["/lib/noexpect"].item_count == 3


def test_get_batch_without_mtimes_returns_all_hits(memory_db):
    """No mtimes argument: behavior unchanged — every hit row is returned."""
    _migrate_with_baseline(memory_db)
    cache = DirectoryCache(memory_db)
    cache.set_batch([
        ("/lib/a", 5, None, 1000.0),
        ("/lib/b", 10, "/lib/b/img.jpg", 2000.0),
    ])

    entries = cache.get_batch(["/lib/a", "/lib/missing", "/lib/b"])

    assert set(entries) == {"/lib/a", "/lib/b"}
    assert entries["/lib/b"].preview_path == "/lib/b/img.jpg"


def test_get_batch_filters_legacy_rows_by_mtime(memory_db):
    """mtime filtering applies to rows found via the legacy raw-key fallback too."""
    _migrate_with_baseline(memory_db)
    legacy_path = os.path.join("legacy", "dir")
    memory_db.execute(
        "INSERT INTO directory_cache (dir_path, item_count, preview_path, mtime, scanned_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (legacy_path, 3, None, 100.0, 0.0),
    )
    memory_db.commit()
    cache = DirectoryCache(memory_db)

    fresh = cache.get_batch([legacy_path], mtimes={legacy_path: 100.0})
    stale = cache.get_batch([legacy_path], mtimes={legacy_path: 999.0})

    assert set(fresh) == {legacy_path}
    assert stale == {}
