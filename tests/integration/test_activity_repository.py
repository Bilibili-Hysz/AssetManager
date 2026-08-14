"""Tests for the persisted LAN ActivityLog (G4-3)."""
from __future__ import annotations

import sqlite3

from AssetsManager.core import database
from AssetsManager.core.db_migrations import migrate
from AssetsManager.lan.routes._helpers import ActivityLog


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(database._SCHEMA)
    migrate(conn)
    return conn


def test_activity_log_persists_with_connection_provider():
    conn = _conn()
    try:
        log = ActivityLog(connection_provider=lambda: conn)
        log.add("alice", "download", "hero.png", ip="127.0.0.1")
        log.add("guest", "browse", "", ip="unknown")

        rows = log.recent(10)
        assert len(rows) == 2
        assert rows[0]["action"] == "browse"  # newest first
        assert rows[1]["action"] == "download"
        assert rows[1]["username"] == "alice"
        assert rows[1]["details"] == "hero.png"
        assert rows[1]["ip"] == "127.0.0.1"
        assert all(isinstance(row["timestamp"], float) for row in rows)
    finally:
        conn.close()


def test_activity_log_recent_respects_count():
    conn = _conn()
    try:
        log = ActivityLog(connection_provider=lambda: conn)
        for index in range(5):
            log.add("user", f"action-{index}", "", ip="ip")

        assert len(log.recent(3)) == 3
        assert log.recent(3)[0]["action"] == "action-4"
    finally:
        conn.close()


def test_activity_log_falls_back_to_memory_without_provider():
    log = ActivityLog()
    log.add("alice", "browse", "")
    rows = log.recent(10)
    assert len(rows) == 1
    assert rows[0]["username"] == "alice"
    assert rows[0]["action"] == "browse"


def test_activity_log_persistence_failure_keeps_memory_entry():
    conn = _conn()
    try:
        log = ActivityLog(connection_provider=lambda: conn)
        # Drop the table after wiring so the INSERT fails; the in-memory
        # deque must still serve the entry.
        conn.execute("DROP TABLE activity_log")
        conn.commit()

        log.add("alice", "browse", "")
        rows = log.recent(10)
        assert len(rows) == 1
        assert rows[0]["username"] == "alice"
    finally:
        conn.close()
