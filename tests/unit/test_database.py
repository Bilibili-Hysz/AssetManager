"""Unit tests for SQL slow-query instrumentation in core.database.

The instrumentation is layered on the connection object (there is no central
``Database.execute``/``executemany`` in this codebase), so these tests drive
:func:`slow_query_wrapper`'s ``SlowQueryConnection`` and the module-level
statement interceptors directly, plus one integration test that routes a real
repository query through the wrapper to verify caller attribution.
"""
import logging
import sqlite3
import time
from typing import Any, Iterable, Sequence

from AssetsManager.core import database
from AssetsManager.core.database import (
    SLOW_QUERY_THRESHOLD_MS,
    SlowQueryConnection,
    slow_query_threshold_ms,
    slow_query_wrapper,
)


class _SleepingConn:
    """Delegating stand-in whose statement methods sleep 150ms.

    ``sqlite3.Connection`` instances are immutable at the attribute level (the
    C type owns ``execute``), so a slow path cannot be injected with
    monkeypatch; this proxy puts the deterministic 0.15s stall inside the
    timing window measured by the instrumentation.
    """

    def __init__(self, inner: sqlite3.Connection) -> None:
        self._inner = inner

    def execute(self, sql: str, parameters: Sequence[Any] = ()) -> sqlite3.Cursor:
        time.sleep(0.15)
        return self._inner.execute(sql, parameters)

    def executemany(self, sql: str, seq_of_parameters: Iterable[Any]) -> sqlite3.Cursor:
        time.sleep(0.15)
        return self._inner.executemany(sql, seq_of_parameters)

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


def _memory_connection() -> sqlite3.Connection:
    return sqlite3.connect(":memory:", check_same_thread=False)


def _slow_messages(caplog) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if "[SLOW QUERY]" in record.getMessage()
    ]


def test_slow_query_execute_logs(caplog):
    inner = _memory_connection()
    inner.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    wrapped = slow_query_wrapper(_SleepingConn(inner))

    with caplog.at_level(logging.WARNING, logger="AssetsManager.core.database"):
        wrapped.execute("INSERT INTO t (v) VALUES (?)", ("slow",))

    messages = _slow_messages(caplog)
    assert len(messages) == 1
    assert "[SLOW QUERY]" in messages[0]
    assert messages[0].startswith("[SLOW QUERY]")
    assert "INSERT INTO t" in messages[0]
    assert "| caller:" in messages[0]
    assert "test_database.py" in messages[0]


def test_slow_query_executemany_logs(caplog):
    inner = _memory_connection()
    inner.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    wrapped = slow_query_wrapper(_SleepingConn(inner))

    with caplog.at_level(logging.WARNING, logger="AssetsManager.core.database"):
        wrapped.executemany("INSERT INTO t (v) VALUES (?)", [("a",), ("b",)])

    messages = _slow_messages(caplog)
    assert len(messages) == 1
    assert "[SLOW QUERY]" in messages[0]
    assert "INSERT INTO t" in messages[0]
    assert "order_repository.py" not in messages[0]


def test_slow_query_reports_repository_caller(schema_db, caplog, monkeypatch):
    """A real repository query must be attributed to its own caller frame."""
    from AssetsManager.repositories.order_repository import OrderRepository

    # Any statement on an in-memory DB is slower than 0.0001ms, so the
    # repository's SELECT deterministically exceeds the threshold without a
    # timing-fixture sleep.
    monkeypatch.setenv("SLOW_QUERY_THRESHOLD_MS", "0.0001")
    wrapped = slow_query_wrapper(schema_db)
    orders = OrderRepository(wrapped)

    with caplog.at_level(logging.WARNING, logger="AssetsManager.core.database"):
        orders.list_orders()

    messages = _slow_messages(caplog)
    assert messages, "expected at least one [SLOW QUERY] log"
    assert "order_repository.py" in messages[0], messages[0]
    assert "caller:" in messages[0], messages[0]


def test_slow_query_module_execute_function(caplog):
    inner = _memory_connection()
    inner.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")

    with caplog.at_level(logging.WARNING, logger="AssetsManager.core.database"):
        database.execute(
            _SleepingConn(inner), "INSERT INTO t (v) VALUES (?)", ("slow",)
        )

    messages = _slow_messages(caplog)
    assert len(messages) == 1
    assert "[SLOW QUERY]" in messages[0]
    assert "test_database.py" in messages[0]


def test_slow_query_module_executemany_function(caplog):
    inner = _memory_connection()
    inner.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")

    with caplog.at_level(logging.WARNING, logger="AssetsManager.core.database"):
        database.executemany(
            _SleepingConn(inner), "INSERT INTO t (v) VALUES (?)", [("c",)]
        )

    messages = _slow_messages(caplog)
    assert len(messages) == 1
    assert "[SLOW QUERY]" in messages[0]
    assert "test_database.py" in messages[0]


def test_fast_query_not_logged(caplog):
    inner = _memory_connection()
    inner.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    wrapped = slow_query_wrapper(inner)

    with caplog.at_level(logging.WARNING, logger="AssetsManager.core.database"):
        wrapped.execute("INSERT INTO t (v) VALUES (?)", ("fast",))

    assert _slow_messages(caplog) == []


def test_slow_query_threshold_env_override_raises_threshold(monkeypatch, caplog):
    inner = _memory_connection()
    inner.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    wrapped = slow_query_wrapper(_SleepingConn(inner))

    monkeypatch.setenv("SLOW_QUERY_THRESHOLD_MS", "1000")
    with caplog.at_level(logging.WARNING, logger="AssetsManager.core.database"):
        # 150ms stall is below the raised 1000ms threshold: nothing logged.
        wrapped.execute("INSERT INTO t (v) VALUES (?)", ("slow-but-under",))

    assert _slow_messages(caplog) == []


def test_slow_query_threshold_env_lowers_threshold(monkeypatch, caplog):
    inner = _memory_connection()
    inner.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    wrapped = slow_query_wrapper(inner)

    monkeypatch.setenv("SLOW_QUERY_THRESHOLD_MS", "0.0001")
    with caplog.at_level(logging.WARNING, logger="AssetsManager.core.database"):
        wrapped.execute("INSERT INTO t (v) VALUES (?)", ("fast",))

    assert len(_slow_messages(caplog)) == 1


def test_slow_query_threshold_invalid_env_falls_back_to_default(monkeypatch, caplog):
    monkeypatch.setenv("SLOW_QUERY_THRESHOLD_MS", "not-a-number")
    with caplog.at_level(logging.WARNING, logger="AssetsManager.core.database"):
        assert slow_query_threshold_ms() == SLOW_QUERY_THRESHOLD_MS
    assert caplog.records, "the invalid environment value should be warned about"

    monkeypatch.delenv("SLOW_QUERY_THRESHOLD_MS", raising=False)
    assert slow_query_threshold_ms() == SLOW_QUERY_THRESHOLD_MS


def test_slow_query_wrapper_is_idempotent():
    wrapped = slow_query_wrapper(_memory_connection())
    assert isinstance(wrapped, SlowQueryConnection)
    assert slow_query_wrapper(wrapped) is wrapped
