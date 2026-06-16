"""Regression tests: concurrent SQLite read safety and write-lock integrity.

These guard against future regressions in the LAN server's shared
SQLite connection model (WAL mode + check_same_thread=False).
"""
import sqlite3
import threading

from AssetsManager.core.database import DatabaseManager

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
