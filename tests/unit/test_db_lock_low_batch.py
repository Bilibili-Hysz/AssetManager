"""Low-batch regression tests: concurrent migration, frozen history, lock keys.

Covers:
- Bug 5: concurrent ``migrate()`` calls on the same library database — an
  in-process guard serializes them, and a single retry covers the cross-process
  race (IntegrityError / "database is locked").
- Bug 13: the shipped migration history is frozen; renaming a recorded
  migration is rejected with an immutability hint.
- Bug 12: LibraryLock registry keys are normalized so relative/absolute and
  slash/case spellings of one path never report a false "already open".
"""
import os
import sqlite3
import threading

import pytest

from AssetsManager.core.library_lock import LibraryLock


# Shipped (version, name) history. Freeze: adding a migration or renaming one
# requires deliberately updating this snapshot AND keeping
# `frozen_history_signature()` stable for existing databases.
_EXPECTED_HISTORY = (
    (1, "baseline_current_schema"),
    (2, "add_assets_index"),
    (3, "add_tag_metadata"),
    (4, "add_plugin_metadata"),
    (5, "directory_cache"),
    (6, "auth_share_schema"),
    (7, "library_favorites"),
    (8, "commerce_schema"),
    (9, "asset_index_state"),
    (10, "free_download_quota"),
    (11, "shop_order_receipts"),
    (12, "seller_profile"),
    (13, "storefront_analytics"),
    (14, "reconciliation_tasks"),
    (15, "reconciliation_queue_state"),
    (16, "shop_cart_wishlist"),
    (17, "reconciliation_lease_token"),
    (18, "shop_order_buyer_owner"),
    (19, "shop_checkout_generation"),
    (20, "shop_order_receipt_recovery"),
    (21, "shop_checkout_fingerprint"),
    (22, "shop_delivery_attempts"),
    (23, "shop_catalog_ordering_index"),
    (24, "asset_dir_mtime_snapshot"),
)


def _open_schema_db(path: str) -> sqlite3.Connection:
    """Open a fresh library database with the application baseline schema."""
    from AssetsManager.core import database

    conn = sqlite3.connect(path, timeout=30)
    conn.executescript(database._SCHEMA)
    conn.commit()
    return conn


def _history_rows(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    return [
        (row[0], row[1])
        for row in conn.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        )
    ]


def test_concurrent_migrate_same_library_serializes(tmp_path):
    """Two threads migrating the same file library must both succeed."""
    from AssetsManager.core import db_migrations
    from AssetsManager.core.db_migrations import CURRENT_SCHEMA_VERSION, migrate

    db_file = tmp_path / "library.db"
    conn = _open_schema_db(str(db_file))
    conn.close()

    results: list[int] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        conn = sqlite3.connect(str(db_file), timeout=30, check_same_thread=False)
        try:
            barrier.wait(timeout=30)
            results.append(migrate(conn))
        except BaseException as error:  # pragma: no cover - failure reporting
            errors.append(error)
        finally:
            conn.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)

    assert not errors
    assert results == [CURRENT_SCHEMA_VERSION, CURRENT_SCHEMA_VERSION]

    with sqlite3.connect(str(db_file)) as conn:
        assert _history_rows(conn) == [
            (migration.version, migration.name)
            for migration in db_migrations.MIGRATIONS
        ]


@pytest.mark.parametrize(
    "failure",
    [
        sqlite3.IntegrityError("UNIQUE constraint failed: schema_migrations.version"),
        sqlite3.OperationalError("database is locked"),
    ],
)
def test_migrate_retries_once_after_concurrent_failure(memory_db, monkeypatch, failure):
    """A cross-process loser retries once and completes after re-reading history."""
    from AssetsManager.core import database, db_migrations
    from AssetsManager.core.db_migrations import CURRENT_SCHEMA_VERSION, migrate

    conn = memory_db
    conn.executescript(database._SCHEMA)
    real_record = db_migrations._record
    calls = {"count": 0}

    def flaky_record(target_conn, migration):
        if calls["count"] == 0:
            calls["count"] += 1
            raise failure
        calls["count"] += 1
        real_record(target_conn, migration)

    monkeypatch.setattr(db_migrations, "_record", flaky_record)

    assert migrate(conn) == CURRENT_SCHEMA_VERSION
    assert calls["count"] == CURRENT_SCHEMA_VERSION + 1
    assert _history_rows(conn) == [
        (migration.version, migration.name)
        for migration in db_migrations.MIGRATIONS
    ]


def test_migrate_propagates_persistent_concurrent_failure(memory_db, monkeypatch):
    """A failure that repeats on the retry is surfaced, not swallowed."""
    from AssetsManager.core import database, db_migrations
    from AssetsManager.core.db_migrations import migrate

    conn = memory_db
    conn.executescript(database._SCHEMA)

    def always_fail(target_conn, migration):
        raise sqlite3.IntegrityError(
            "UNIQUE constraint failed: schema_migrations.version"
        )

    monkeypatch.setattr(db_migrations, "_record", always_fail)

    with pytest.raises(sqlite3.IntegrityError, match="schema_migrations"):
        migrate(conn)


def test_frozen_history_signature_is_stable():
    from AssetsManager.core.db_migrations import (
        CURRENT_SCHEMA_VERSION,
        frozen_history_signature,
    )

    signature = frozen_history_signature()

    assert signature == _EXPECTED_HISTORY
    assert len(signature) == CURRENT_SCHEMA_VERSION
    assert [version for version, _name in signature] == list(
        range(1, CURRENT_SCHEMA_VERSION + 1)
    )
    names = [name for _version, name in signature]
    assert len(set(names)) == len(names)


def test_history_rename_error_mentions_immutable_history():
    from AssetsManager.core.db_migrations import (
        MigrationHistoryError,
        _validate_history,
    )

    with pytest.raises(MigrationHistoryError, match="name does not match"):
        _validate_history([(1, "renamed_baseline")])
    with pytest.raises(MigrationHistoryError, match="immutable"):
        _validate_history([(1, "renamed_baseline")])


def test_library_lock_normalizes_registry_key(tmp_path):
    """Absolute slash/case/Path spellings of one lock file share a single lease."""
    lock_file = tmp_path / "RuntimeData" / "Shared" / "x.lock"
    variants: list[str | os.PathLike[str]] = [
        str(lock_file),
        lock_file.as_posix(),
        lock_file,
    ]
    if os.name == "nt":
        variants.append(lock_file.as_posix().swapcase())

    locks: list[LibraryLock] = []
    try:
        for variant in variants:
            # Must not raise LibraryAlreadyOpenError for the same lock file.
            locks.append(LibraryLock(variant))
        assert len({lock._key for lock in locks}) == 1
        assert all(lock._lock is locks[0]._lock for lock in locks)
    finally:
        for lock in locks:
            lock.release()


def test_library_lock_relative_and_absolute_spellings_share(tmp_path, monkeypatch):
    """A relative spelling and its absolute form must not false-conflict."""
    monkeypatch.chdir(tmp_path)
    relative = os.path.join("RuntimeData", "Shared", "x.lock")
    absolute = str(tmp_path / "RuntimeData" / "Shared" / "x.lock")

    lock_a = LibraryLock(relative)
    lock_b = LibraryLock(absolute)
    try:
        assert lock_a._key == lock_b._key
        assert lock_a._lock is lock_b._lock
    finally:
        lock_a.release()
        lock_b.release()


def test_library_lock_distinct_paths_stay_distinct(tmp_path):
    lock_a = LibraryLock(str(tmp_path / "a.lock"))
    lock_b = LibraryLock(str(tmp_path / "b.lock"))
    try:
        assert lock_a._key != lock_b._key
        assert lock_a._lock is not lock_b._lock
    finally:
        lock_a.release()
        lock_b.release()
