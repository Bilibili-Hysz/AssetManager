from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from AssetsManager.application.free_download_quota_service import (
    FreeDownloadQuotaConfig,
    FreeDownloadQuotaService,
)
from AssetsManager.repositories.free_download_quota_repository import (
    FreeDownloadQuotaRepository,
)


def test_repository_consumes_limit_and_rate_interval_atomically(schema_db):
    repository = FreeDownloadQuotaRepository(schema_db)

    first = repository.consume(
        "ip:127.0.0.1", 1_000, now=1_001.0, limit=2, min_interval_seconds=5,
    )
    assert first == {
        "allowed": True,
        "reason": None,
        "used": 1,
        "remaining": 1,
        "retry_after_seconds": 0,
        "last_download_at": 1_001.0,
    }

    limited = repository.consume(
        "ip:127.0.0.1", 1_000, now=1_003.0, limit=2, min_interval_seconds=5,
    )
    assert limited["allowed"] is False
    assert limited["reason"] == "rate_limited"
    assert limited["used"] == 1
    assert limited["remaining"] == 1
    assert limited["retry_after_seconds"] == 3

    second = repository.consume(
        "ip:127.0.0.1", 1_000, now=1_006.0, limit=2, min_interval_seconds=5,
    )
    assert second["allowed"] is True
    assert second["used"] == 2
    assert second["remaining"] == 0

    exhausted = repository.consume(
        "ip:127.0.0.1", 1_000, now=1_020.0, limit=2, min_interval_seconds=0,
    )
    assert exhausted["allowed"] is False
    assert exhausted["reason"] == "exhausted"
    assert exhausted["used"] == 2


def test_repository_cas_allows_only_one_concurrent_final_slot(schema_db):
    repository = FreeDownloadQuotaRepository(schema_db)

    def consume_once():
        return repository.consume(
            "ip:127.0.0.1", 1_000, now=1_001.0, limit=1, min_interval_seconds=0,
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _index: consume_once(), range(4)))

    assert sum(bool(result["allowed"]) for result in results) == 1
    assert sum(result["reason"] == "exhausted" for result in results) == 3
    assert repository.get_window("ip:127.0.0.1", 1_000)["used"] == 1


def test_repository_prunes_only_current_identity_expired_windows(schema_db):
    repository = FreeDownloadQuotaRepository(schema_db)

    repository.consume(
        "anon:identity-a", 1_000, now=1_001.0, limit=5, min_interval_seconds=0,
    )
    repository.consume(
        "anon:identity-b", 1_000, now=1_001.0, limit=5, min_interval_seconds=0,
    )
    assert repository.get_window("anon:identity-a", 1_000)["used"] == 1
    assert repository.get_window("anon:identity-b", 1_000)["used"] == 1

    # Identity A advancing to a later window must not wipe identity B's rows.
    # Before the identity-scoped DELETE, this simulated one-identity consume
    # reset every other identity's persisted window.
    repository.consume(
        "anon:identity-a", 2_000, now=2_001.0, limit=5, min_interval_seconds=0,
    )
    assert repository.get_window("anon:identity-a", 1_000) is None
    assert repository.get_window("anon:identity-b", 1_000) is not None
    assert repository.get_window("anon:identity-b", 1_000)["used"] == 1


def test_service_exposes_disabled_and_period_scoped_info(schema_db):
    repository = FreeDownloadQuotaRepository(schema_db)
    now = [1_704_067_200.0]  # 2024-01-01 00:00:00 local time in common CI zones
    service = FreeDownloadQuotaService(repository, clock=lambda: now[0])

    disabled = service.info("ip:test", FreeDownloadQuotaConfig(enabled=False))
    assert disabled == {
        "enabled": False,
        "period": "daily",
        "limit": 0,
        "used": 0,
        "remaining": None,
        "reset_at": None,
        "min_interval_seconds": 0,
    }

    config = FreeDownloadQuotaConfig(enabled=True, period="daily", limit=3, min_interval_seconds=0)
    consumed = service.consume("ip:test", config)
    assert consumed["allowed"] is True
    assert consumed["info"]["used"] == 1
    assert consumed["info"]["remaining"] == 2

    now[0] += 24 * 60 * 60
    next_window = service.info("ip:test", config)
    assert next_window["used"] == 0
    assert next_window["remaining"] == 3


def test_repository_prune_windows_deletes_only_strictly_older(schema_db):
    repository = FreeDownloadQuotaRepository(schema_db)
    repository.consume(
        "ip:a", 1_000, now=1_001.0, limit=5, min_interval_seconds=0,
    )
    repository.consume(
        "ip:b", 2_000, now=2_001.0, limit=5, min_interval_seconds=0,
    )
    repository.consume(
        "ip:c", 3_000, now=3_001.0, limit=5, min_interval_seconds=0,
    )

    removed = repository.prune_windows(2_000)

    assert removed == 1
    remaining_starts = sorted(
        row[0]
        for row in schema_db.execute(
            "SELECT window_start FROM free_download_quota_windows"
        )
    )
    assert remaining_starts == [2_000, 3_000]


def test_repository_prune_windows_rejects_negative_cutoff(schema_db):
    repository = FreeDownloadQuotaRepository(schema_db)
    with pytest.raises(ValueError):
        repository.prune_windows(-1)


def test_service_prune_stale_windows_keeps_recent_periods(schema_db):
    fixed_now = 1_700_000_000.0
    repository = FreeDownloadQuotaRepository(schema_db)
    service = FreeDownloadQuotaService(repository, clock=lambda: fixed_now)
    config = FreeDownloadQuotaConfig(enabled=True, period="daily")

    current_start = FreeDownloadQuotaService.period_start(fixed_now, "daily")
    previous_start = FreeDownloadQuotaService.period_start(
        current_start - 1.0, "daily"
    )
    ancient_start = previous_start - 5 * 86_400
    for start in (current_start, previous_start, ancient_start):
        repository.consume(
            "ip:a", start, now=start + 1.0, limit=5, min_interval_seconds=0,
        )

    removed = service.prune_stale_windows(config, periods_to_keep=2)

    assert removed == 1
    surviving_starts = sorted(
        row[0]
        for row in schema_db.execute(
            "SELECT window_start FROM free_download_quota_windows"
        )
    )
    assert surviving_starts == sorted([previous_start, current_start])


def test_service_maintenance_gate_runs_on_cadence_and_retries_after_failure():
    class Repository:
        def prune_windows(self, _before):
            return 1

    def wall_clock():
        return 1_700_000_000.0

    monotonic = [10.0]
    service = FreeDownloadQuotaService(
        Repository(),
        clock=wall_clock,
        monotonic_clock=lambda: monotonic[0],
    )
    config = FreeDownloadQuotaConfig(enabled=True)
    calls = []

    def record_prune(_config, *, now=None, periods_to_keep=2):
        calls.append((now, periods_to_keep))
        return 1

    service.prune_stale_windows = record_prune

    assert service.maybe_prune_stale_windows(config) == 1
    assert service.maybe_prune_stale_windows(config) is None
    assert len(calls) == 1

    monotonic[0] += service.MAINTENANCE_INTERVAL_SECONDS
    assert service.maybe_prune_stale_windows(config) == 1
    assert len(calls) == 2

    def fail_prune(_config, *, now=None, periods_to_keep=2):
        calls.append((now, periods_to_keep))
        raise RuntimeError("locked")

    service.prune_stale_windows = fail_prune
    monotonic[0] += service.MAINTENANCE_INTERVAL_SECONDS
    with pytest.raises(RuntimeError, match="locked"):
        service.maybe_prune_stale_windows(config)
    assert len(calls) == 3
    assert service.maybe_prune_stale_windows(config) is None

    monotonic[0] += service.MAINTENANCE_FAILURE_RETRY_SECONDS
    service.prune_stale_windows = record_prune
    assert service.maybe_prune_stale_windows(config) == 1
    assert len(calls) == 4


class _ConnectionProxy:
    def __init__(self, connection, *, fail_deletes=0):
        self._connection = connection
        self._fail_deletes = fail_deletes

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def execute(self, sql, parameters=()):
        if sql.startswith("DELETE FROM free_download_quota_windows") and self._fail_deletes:
            self._fail_deletes -= 1
            raise sqlite3.OperationalError("database is locked")
        return self._connection.execute(sql, parameters)


class _ConsumeLockProxy(_ConnectionProxy):
    """Fail the first consume-transaction statement with a busy error."""

    def __init__(self, connection):
        super().__init__(connection)
        self.consume_locks_left = 1

    def execute(self, sql, parameters=()):
        if (
            self.consume_locks_left
            and "SAVEPOINT free_download_quota_consume" in str(sql)
        ):
            self.consume_locks_left -= 1
            raise sqlite3.OperationalError("database is locked")
        return self._connection.execute(sql, parameters)


def test_repository_consume_retries_sqlite_busy_then_succeeds(schema_db, monkeypatch):
    connection = _ConsumeLockProxy(schema_db)
    repository = FreeDownloadQuotaRepository(connection)
    monkeypatch.setattr(
        "AssetsManager.repositories._common.time.sleep",
        lambda _delay: None,
    )

    result = repository.consume(
        "ip:a", 1_000, now=1_001.0, limit=1, min_interval_seconds=0,
    )

    assert result["allowed"] is True
    assert result["used"] == 1
    assert connection.consume_locks_left == 0


def test_repository_consume_does_not_retry_inside_outer_transaction(
    schema_db, monkeypatch,
):
    connection = _ConsumeLockProxy(schema_db)
    repository = FreeDownloadQuotaRepository(connection)
    schema_db.execute("BEGIN")
    try:
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            repository.consume(
                "ip:b", 2_000, now=2_001.0, limit=1, min_interval_seconds=0,
            )
        # Exactly one transaction attempt was made (no replay), and no
        # quota row leaked outside the aborted outer transaction.
        assert connection.consume_locks_left == 0
        row = schema_db.execute(
            "SELECT download_count FROM free_download_quota_windows "
            "WHERE identity_key='ip:b'"
        ).fetchone()
        assert row is None
    finally:
        schema_db.rollback()


def test_repository_prune_retries_sqlite_busy_then_succeeds(schema_db, monkeypatch):
    connection = _ConnectionProxy(schema_db, fail_deletes=1)
    repository = FreeDownloadQuotaRepository(connection)
    monkeypatch.setattr(
        "AssetsManager.repositories._common.time.sleep",
        lambda _delay: None,
    )
    assert repository.prune_windows(1_000) == 0
    assert connection._fail_deletes == 0


def test_repository_prune_does_not_retry_inside_outer_transaction(schema_db, monkeypatch):
    connection = _ConnectionProxy(schema_db, fail_deletes=1)
    repository = FreeDownloadQuotaRepository(connection)
    schema_db.execute("BEGIN")
    try:
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            repository.prune_windows(1_000)
        assert connection._fail_deletes == 0
    finally:
        schema_db.rollback()
