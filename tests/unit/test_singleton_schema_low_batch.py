"""Low-batch regression tests for core.singleton and core.schema_defs.

Covers:
  - Bug 25: ThreadSafeSingleton usable as a class decorator
            (@ThreadSafeSingleton and @ThreadSafeSingleton() forms)
  - Bug 26: get() never returns an instance already cleared by a
            concurrent reset() (fast path removed, always locked)
  - Bug 24: CHECK-constraint validation compares SQL at token level so an
            equivalent table rebuilt with different whitespace does not
            raise a false "missing checks" error
"""
import sqlite3
import threading

import pytest

from AssetsManager.core.schema_defs import (
    InvalidSchemaError,
    SchemaObjectContract,
    validate_schema_object,
)
from AssetsManager.core.singleton import ThreadSafeSingleton


# ── Bug 25: decorator usage ─────────────────────────────────────


def test_decorator_bare_form_returns_same_instance():
    @ThreadSafeSingleton
    class DecoratedService:
        pass

    assert DecoratedService.instance() is DecoratedService.instance()


def test_decorator_parenthesized_form_returns_same_instance():
    @ThreadSafeSingleton()
    class ParenthesizedService:
        pass

    assert ParenthesizedService.instance() is ParenthesizedService.instance()


def test_decorator_reset_creates_new_instance():
    @ThreadSafeSingleton
    class ResetService:
        pass

    first = ResetService.instance()
    ResetService.reset()
    second = ResetService.instance()
    assert second is not first
    assert ResetService.instance() is second


def test_decorator_rejects_non_class():
    with pytest.raises(TypeError):
        ThreadSafeSingleton(42)
    with pytest.raises(TypeError):
        ThreadSafeSingleton()(42)


# ── Bug 26: get() vs reset() ────────────────────────────────────


def test_get_after_reset_returns_new_instance():
    class Service:
        pass

    first = ThreadSafeSingleton.get(Service)
    ThreadSafeSingleton.reset(Service)
    second = ThreadSafeSingleton.get(Service)
    assert second is not first


def test_get_concurrent_with_reset_returns_live_instance():
    """Concurrent get/reset stress: no torn reads, no exceptions, and a
    get that runs after a reset completed always yields a fresh instance.""" 

    class Service:
        pass

    errors: list[BaseException] = []

    def worker():
        try:
            for _ in range(200):
                instance = ThreadSafeSingleton.get(Service)
                if instance is None:
                    raise AssertionError("get() returned None")
                ThreadSafeSingleton.reset(Service)
        except BaseException as exc:  # noqa: BLE001 - captured for the main thread
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    # The stress left the singleton in reset state; the next get must
    # create (or observe) a live instance, never a cleared one.
    final = ThreadSafeSingleton.get(Service)
    assert final is not None
    assert final is Service._singleton_instance
    ThreadSafeSingleton.reset(Service)


# ── Bug 24: token-level CHECK matching ──────────────────────────

_TABLE_SQL = "CREATE TABLE sample_table (id INTEGER PRIMARY KEY, revision INTEGER CHECK (revision >= 0))"


def _contract_with_check(check: str) -> SchemaObjectContract:
    return {
        "columns": ("id", "revision"),
        "primary_key": ("id",),
        "unique_constraints": (),
        "checks": (check,),
    }


def test_check_whitespace_equivalent_rebuild_not_reported_missing():
    """CHECK(revision>=0) must satisfy a CHECK (revision >= 0) contract."""
    conn = sqlite3.connect(":memory:")
    contract = _contract_with_check("CHECK (revision >= 0)")

    conn.execute(_TABLE_SQL)
    validate_schema_object(conn, "sample_table", contract)

    # Equivalent rebuild with no whitespace around the CHECK tokens.
    conn.execute("DROP TABLE sample_table")
    conn.execute(
        "CREATE TABLE sample_table (id INTEGER PRIMARY KEY, "
        "revision INTEGER CHECK(revision>=0))"
    )
    validate_schema_object(conn, "sample_table", contract)
    conn.close()


def test_check_without_check_keyword_matches_table_sql():
    """A bare expression contract matches the CHECK (...) in table SQL."""
    conn = sqlite3.connect(":memory:")
    conn.execute(_TABLE_SQL)
    validate_schema_object(conn, "sample_table", _contract_with_check("revision >= 0"))
    conn.close()


def test_check_multiline_layout_matches():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE sample_table (
            id       INTEGER PRIMARY KEY,
            revision INTEGER CHECK (
                revision >= 0
            )
        )
        """
    )
    validate_schema_object(conn, "sample_table", _contract_with_check("revision >= 0"))
    conn.close()


def test_changed_check_still_reported_missing():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE sample_table (id INTEGER PRIMARY KEY, "
        "revision INTEGER CHECK (revision >= 1))"
    )
    with pytest.raises(InvalidSchemaError) as excinfo:
        validate_schema_object(conn, "sample_table", _contract_with_check("revision >= 0"))
    assert excinfo.value.missing_checks == ("revision >= 0",)
    conn.close()
