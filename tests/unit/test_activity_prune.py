"""H2-a3: ``activity_log`` retention prune (90 days).

Unit-level: a real SQLite connection with the v29 ``activity_log`` shape and
a plain ``ActivityRecorder`` — no bootstrap needed, mirroring the recorder's
own swallow-on-error contracts.
"""
import sqlite3
import time
from pathlib import Path


from AssetsManager.application.activity_recorder import ActivityRecorder
from AssetsManager.core.constants import ACTIVITY_RETENTION_DAYS


def _recorder(tmp_path: Path):
    conn = sqlite3.connect(
        str(tmp_path / "assetmanager.db"), check_same_thread=False)
    conn.execute(
        "CREATE TABLE activity_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "username TEXT NOT NULL DEFAULT 'guest', "
        "action TEXT NOT NULL, "
        "details TEXT NOT NULL DEFAULT '', "
        "ip TEXT NOT NULL DEFAULT 'unknown', "
        "timestamp REAL NOT NULL)")
    conn.commit()
    return ActivityRecorder(lambda: conn), conn


def _insert(conn, action: str, timestamp: float) -> None:
    conn.execute(
        "INSERT INTO activity_log (action, timestamp) VALUES (?, ?)",
        (action, timestamp))
    conn.commit()


def test_retention_constant_is_ninety_days():
    assert ACTIVITY_RETENTION_DAYS == 90


def test_prune_deletes_only_expired_rows(tmp_path):
    recorder, conn = _recorder(tmp_path)
    now = time.time()
    _insert(conn, "old-row", now - 91 * 86400)
    _insert(conn, "today-row", now)

    assert recorder.prune() == 1

    remaining = [row[0] for row in
                 conn.execute("SELECT action FROM activity_log").fetchall()]
    assert remaining == ["today-row"]

    # A second pass is a clean no-op.
    assert recorder.prune() == 0
    assert conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0] == 1


def test_prune_custom_window_and_zero_window(tmp_path):
    recorder, conn = _recorder(tmp_path)
    now = time.time()
    _insert(conn, "week-old", now - 7 * 86400)
    _insert(conn, "now", now)

    # 90-day default keeps the week-old row; a 1-day window removes it.
    assert recorder.prune() == 0
    assert recorder.prune(retention_days=1) == 1

    # retention_days=0 removes every row strictly older than the current
    # instant — the surviving "now" row included (its captured timestamp is
    # already in the past by the time the DELETE runs).
    _insert(conn, "again", now)
    assert recorder.prune(retention_days=0) == 2
    assert conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0] == 0


def test_prune_swallows_provider_failures():
    def _boom():
        raise RuntimeError("connection unavailable")

    recorder = ActivityRecorder(_boom)
    assert recorder.prune() == 0


def test_prune_swallows_missing_table(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "empty.db"), check_same_thread=False)
    recorder = ActivityRecorder(lambda: conn)
    assert recorder.prune() == 0


def test_prune_handles_null_provider():
    recorder = ActivityRecorder(lambda: None)
    assert recorder.prune() == 0
