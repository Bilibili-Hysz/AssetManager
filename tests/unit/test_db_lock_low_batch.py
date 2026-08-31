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
    (25, "shop_share_claims"),
    (26, "gallery_home_projection"),
    (27, "revoked_tokens"),
    (28, "user_can_write"),
    (29, "activity_log"),
    (30, "filesystem_projection_repair"),
    (31, "import_manifests"),
    (32, "thumbnail_cache_lifecycle"),
    (33, "thumbnail_render_profile"),
    (34, "import_manifest_recovery_lease"),
    (35, "file_count_mtime_snapshot"),
    (36, "tag_source_partition"),
    (37, "media_derivatives_and_sequences"),
    (38, "asset_collections"),
    (39, "asset_search_fts"),
    (40, "asset_search_trigram"),
    (41, "asset_derivative_lifecycle"),
    (42, "command_executions"),
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


def _write_fake_lock_file(lock_file, pid: int) -> None:
    """Write a QLockFile-format lock file recording the given owner PID."""
    lock_file.write_text(
        f"{pid}\npython\nHOST\n00000000-0000-0000-0000-000000000000\n\n",
        encoding="utf-8",
    )


def test_library_lock_recovers_stale_lock_from_dead_process(tmp_path):
    """A lock left by a crashed/force-killed process must not block reopening."""
    from AssetsManager.core.library_lock import LibraryLock

    lock_file = tmp_path / "stale.lock"
    _write_fake_lock_file(lock_file, 99999999)  # far outside any live PID range

    lock = LibraryLock(lock_file)  # must not raise

    try:
        assert lock._lock.isLocked()
    finally:
        lock.release()


def test_library_lock_does_not_recover_live_lock(tmp_path):
    """A lock owned by a live PID is still reported as already open."""
    from AssetsManager.core.library_lock import LibraryAlreadyOpenError

    lock_file = tmp_path / "live.lock"
    _write_fake_lock_file(lock_file, os.getpid())  # our own, live process

    with pytest.raises(LibraryAlreadyOpenError):
        LibraryLock(lock_file)


def test_posix_recovery_fails_closed_without_usable_flock(monkeypatch, tmp_path):
    """Missing POSIX recovery capability retains the failed lock state."""
    from contextlib import contextmanager

    from AssetsManager.core import library_lock

    class FailedLock:
        pass

    failed_lock = FailedLock()

    @contextmanager
    def unavailable_guard(_path):
        raise library_lock._PosixRecoveryUnavailable("flock unavailable")
        yield

    monkeypatch.setattr(
        library_lock, "_posix_stale_recovery_guard", unavailable_guard
    )
    lock, acquired = library_lock._recover_posix_stale_lock(
        tmp_path / "live.lock", failed_lock
    )

    assert lock is failed_lock
    assert acquired is False


def test_posix_recovery_rechecks_after_guard(monkeypatch, tmp_path):
    """The recovery seam observes a marker that became live while waiting."""
    from contextlib import contextmanager

    from AssetsManager.core import library_lock

    lock_file = tmp_path / "recheck.lock"
    guard_paths = []
    unlink_attempts = []

    class LiveMarker:
        def tryLock(self, _timeout):
            return False

        def error(self):
            return library_lock.QLockFile.LockError.LockFailedError

        def getLockInfo(self):
            return os.getpid(), "HOST", "python"

    @contextmanager
    def recovery_guard(path):
        guard_paths.append(path)
        # The competing recovery owner is represented by a live PID when the
        # guarded recheck runs.
        yield

    monkeypatch.setattr(library_lock, "_posix_stale_recovery_guard", recovery_guard)
    monkeypatch.setattr(library_lock, "_new_lock", lambda _path: LiveMarker())
    monkeypatch.setattr(
        library_lock.Path,
        "unlink",
        lambda self, **_kwargs: unlink_attempts.append(self),
    )

    lock, acquired = library_lock._recover_posix_stale_lock(lock_file)

    assert isinstance(lock, LiveMarker)
    assert acquired is False
    assert guard_paths == [lock_file]
    assert unlink_attempts == []
