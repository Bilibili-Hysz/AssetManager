"""Regression tests: concurrent SQLite read safety and write-lock integrity.

These guard against future regressions in the LAN server's shared
SQLite connection model (WAL mode + check_same_thread=False).
"""
import sqlite3
import threading
import time

import pytest

from AssetsManager.core.database import DatabaseManager, db_write_lock

NUM_READERS = 8
NUM_ROWS = 50
NUM_WRITE_ITERS = 100


def _init_wal_db(db_path):
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, val TEXT)")
    for i in range(NUM_ROWS):
        conn.execute("INSERT INTO items (id, val) VALUES (?, ?)", (i, f"row-{i}"))
    conn.commit()
    return conn


def test_concurrent_reads(tmp_path):
    db_path = tmp_path / "test.db"
    conn = _init_wal_db(db_path)
    lock = threading.Lock()
    errors = []
    results = []

    def reader(tid):
        try:
            with lock:
                rows = conn.execute(
                    "SELECT id, val FROM items ORDER BY id"
                ).fetchall()
            results.append((tid, rows))
        except Exception as e:
            errors.append((tid, e))

    threads = [threading.Thread(target=reader, args=(i,)) for i in range(NUM_READERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent read errors: {errors}"
    assert len(results) == NUM_READERS
    expected = [(i, f"row-{i}") for i in range(NUM_ROWS)]
    for tid, rows in results:
        assert rows == expected, f"Reader {tid} got wrong data"
    conn.close()


def test_write_lock_prevents_corruption(tmp_path):
    db_path = tmp_path / "test.db"
    conn = _init_wal_db(db_path)
    counter = {"val": 0}
    lock = threading.RLock()
    errors = []

    def writer(tid):
        try:
            for _ in range(NUM_WRITE_ITERS):
                with lock:
                    counter["val"] += 1
                    conn.execute(
                        "INSERT INTO items (id, val) VALUES (?, ?)",
                        (NUM_ROWS + counter["val"], f"written-{tid}"),
                    )
                    conn.commit()
        except Exception as e:
            errors.append((tid, e))

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(NUM_READERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent write errors: {errors}"
    total = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    expected_total = NUM_ROWS + NUM_READERS * NUM_WRITE_ITERS
    assert total == expected_total, f"Row count {total} != expected {expected_total}"
    conn.close()


def test_connection_for_returns_same_object(tmp_path):
    lib_root = tmp_path / "lib"
    lib_root.mkdir()

    mgr = DatabaseManager()
    try:
        c1 = mgr.connection_for(lib_root)
        c2 = mgr.connection_for(lib_root)
        c3 = mgr.connection_for(lib_root)
        assert c1 is c2 is c3, "connection_for() must return the same connection object"
    finally:
        mgr.close()


def test_explicit_write_lock_uses_connection_owner_not_global_singleton(tmp_path, monkeypatch):
    """Scoped repositories must not silently lock a different manager instance."""
    lib_root = tmp_path / "lib"
    lib_root.mkdir()
    manager = DatabaseManager()
    conn = manager.connection_for(lib_root)

    from AssetsManager.core.singleton import ThreadSafeSingleton

    monkeypatch.setattr(
        ThreadSafeSingleton,
        "get",
        lambda _type: (_ for _ in ()).throw(AssertionError("global manager used")),
    )

    try:
        with db_write_lock(conn):
            conn.execute("SELECT 1")
    finally:
        manager.close()


def test_close_library_waits_for_explicit_connection_write_lock(tmp_path):
    lib_root = tmp_path / "lib"
    lib_root.mkdir()
    manager = DatabaseManager()
    conn = manager.connection_for(lib_root)
    entered = threading.Event()
    release = threading.Event()
    closed = threading.Event()

    def writer():
        with db_write_lock(conn):
            entered.set()
            assert release.wait(5)
            conn.execute("SELECT 1")

    def closer():
        manager.close_library(lib_root)
        closed.set()

    writer_thread = threading.Thread(target=writer)
    close_thread = threading.Thread(target=closer)
    writer_thread.start()
    assert entered.wait(5)
    close_thread.start()
    try:
        assert not closed.wait(0.2)
    finally:
        release.set()
    writer_thread.join(5)
    close_thread.join(5)

    assert not writer_thread.is_alive()
    assert not close_thread.is_alive()
    assert closed.is_set()


def test_two_library_write_locks_are_independent(tmp_path):
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    manager = DatabaseManager()
    first = manager.connection_for(first_root)
    second = manager.connection_for(second_root)
    first_entered = threading.Event()
    release_first = threading.Event()
    second_finished = threading.Event()

    def first_writer():
        with db_write_lock(first):
            first_entered.set()
            assert release_first.wait(5)

    def second_writer():
        with db_write_lock(second):
            second.execute("SELECT 1")
            second_finished.set()

    first_thread = threading.Thread(target=first_writer)
    second_thread = threading.Thread(target=second_writer)
    first_thread.start()
    assert first_entered.wait(5)
    second_thread.start()
    try:
        assert second_finished.wait(1)
    finally:
        release_first.set()
    first_thread.join(5)
    second_thread.join(5)
    manager.close()


def test_unmanaged_connection_uses_a_stable_connection_lock(tmp_path, monkeypatch):
    conn = sqlite3.connect(str(tmp_path / "external.db"), check_same_thread=False)
    from AssetsManager.core.singleton import ThreadSafeSingleton

    monkeypatch.setattr(
        ThreadSafeSingleton,
        "get",
        lambda _type: (_ for _ in ()).throw(AssertionError("global manager used")),
    )
    try:
        with db_write_lock(conn):
            with db_write_lock(conn):
                conn.execute("SELECT 1")
    finally:
        conn.close()


def test_closed_library_connection_keeps_its_closed_write_state(tmp_path):
    lib_root = tmp_path / "lib"
    lib_root.mkdir()
    manager = DatabaseManager()
    conn = manager.connection_for(lib_root)

    manager.close_library(lib_root)

    with pytest.raises(RuntimeError, match="closed database connection"):
        with db_write_lock(conn):
            conn.execute("SELECT 1")


def test_managed_write_lock_records_connection_scoped_wait_and_hold(tmp_path):
    from AssetsManager.core.performance import PerformanceRecorder

    root = tmp_path / "library"
    root.mkdir()
    recorder = PerformanceRecorder(enabled=True)
    manager = DatabaseManager(recorder)
    conn = manager.connection_for(root)
    entered = threading.Event()
    release = threading.Event()

    def holder():
        with db_write_lock(conn):
            entered.set()
            assert release.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    assert entered.wait(5)
    release.set()
    thread.join(5)
    manager.close()

    events = recorder.recent()
    assert [event.name for event in events] == ["db.write_lock.wait", "db.write_lock.hold"]
    assert all(event.path == str(root.resolve()) for event in events)
    assert all(event.attributes == {"outcome": "completed"} for event in events)
    assert all(event.elapsed_ms >= 0 for event in events)


def test_write_lock_metrics_remain_independent_per_library(tmp_path):
    from AssetsManager.core.performance import PerformanceRecorder

    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    recorder = PerformanceRecorder(enabled=True)
    manager = DatabaseManager(recorder)
    first = manager.connection_for(first_root)
    second = manager.connection_for(second_root)

    with db_write_lock(first):
        first.execute("SELECT 1")
    with db_write_lock(second):
        second.execute("SELECT 1")
    manager.close()

    assert {event.path for event in recorder.recent()} == {str(first_root.resolve()), str(second_root.resolve())}


def test_write_lock_records_wait_for_queued_writer(tmp_path):
    from AssetsManager.core.performance import PerformanceRecorder

    root = tmp_path / "library"
    root.mkdir()
    recorder = PerformanceRecorder(enabled=True)
    manager = DatabaseManager(recorder)
    conn = manager.connection_for(root)
    holder_entered = threading.Event()
    queued_started = threading.Event()
    release_holder = threading.Event()

    def holder():
        with db_write_lock(conn):
            holder_entered.set()
            assert release_holder.wait(5)

    def queued_writer():
        assert holder_entered.wait(5)
        queued_started.set()
        with db_write_lock(conn):
            conn.execute("SELECT 1")

    holder_thread = threading.Thread(target=holder)
    queued_thread = threading.Thread(target=queued_writer)
    holder_thread.start()
    assert holder_entered.wait(5)
    queued_thread.start()
    assert queued_started.wait(5)
    time.sleep(0.05)
    release_holder.set()
    holder_thread.join(5)
    queued_thread.join(5)
    manager.close()

    wait_events = [event for event in recorder.recent() if event.name == "db.write_lock.wait"]
    assert len(wait_events) == 2
    assert max(event.elapsed_ms for event in wait_events) > 0


def test_nested_write_lock_records_only_outermost_scope(tmp_path):
    from AssetsManager.core.performance import PerformanceRecorder

    root = tmp_path / "library"
    root.mkdir()
    recorder = PerformanceRecorder(enabled=True)
    manager = DatabaseManager(recorder)
    conn = manager.connection_for(root)

    with db_write_lock(conn):
        with db_write_lock(conn):
            conn.execute("SELECT 1")
    manager.close()

    assert [event.name for event in recorder.recent()] == ["db.write_lock.wait", "db.write_lock.hold"]


def test_close_rejects_writer_queued_behind_active_connection_lock(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    manager = DatabaseManager()
    conn = manager.connection_for(root)
    holder_entered = threading.Event()
    release_holder = threading.Event()
    queued_started = threading.Event()
    queued_finished = threading.Event()
    close_finished = threading.Event()
    queued_errors = []

    def holder():
        with db_write_lock(conn):
            holder_entered.set()
            assert release_holder.wait(5)

    def queued_writer():
        queued_started.set()
        try:
            with db_write_lock(conn):
                conn.execute("SELECT 1")
        except RuntimeError as exc:
            queued_errors.append(exc)
        finally:
            queued_finished.set()

    def closer():
        manager.close_library(root)
        close_finished.set()

    holder_thread = threading.Thread(target=holder)
    queued_thread = threading.Thread(target=queued_writer)
    close_thread = threading.Thread(target=closer)
    holder_thread.start()
    assert holder_entered.wait(5)
    queued_thread.start()
    assert queued_started.wait(5)
    close_thread.start()
    import AssetsManager.core.database as database_module
    state = database_module._connection_locks[id(conn)]
    deadline = time.monotonic() + 5
    while not state.closed and time.monotonic() < deadline:
        time.sleep(0.01)
    assert state.closed
    release_holder.set()
    assert queued_finished.wait(5)
    assert close_finished.wait(5)
    holder_thread.join(5)
    queued_thread.join(5)
    close_thread.join(5)

    assert len(queued_errors) == 1


def test_write_lock_records_error_outcome_without_masking_exception(tmp_path):
    from AssetsManager.core.performance import PerformanceRecorder

    root = tmp_path / "library"
    root.mkdir()
    recorder = PerformanceRecorder(enabled=True)
    manager = DatabaseManager(recorder)
    conn = manager.connection_for(root)

    with pytest.raises(ValueError, match="operation failed"):
        with db_write_lock(conn):
            raise ValueError("operation failed")
    manager.close()

    assert [event.attributes["outcome"] for event in recorder.recent()] == ["error", "error"]


def test_disabled_write_lock_recorder_does_not_read_clock(tmp_path, monkeypatch):
    import AssetsManager.core.database as database_module
    from AssetsManager.core.performance import PerformanceRecorder

    root = tmp_path / "library"
    root.mkdir()
    manager = DatabaseManager(PerformanceRecorder())
    conn = manager.connection_for(root)
    monkeypatch.setattr(database_module.time, "perf_counter", lambda: (_ for _ in ()).throw(AssertionError()))

    with db_write_lock(conn):
        conn.execute("SELECT 1")
    manager.close()
