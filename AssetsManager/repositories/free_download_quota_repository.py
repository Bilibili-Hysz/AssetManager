"""SQLite persistence for ordinary (non-commerce-delivery) download quotas."""
from __future__ import annotations

import math
import time
from typing import Any

from AssetsManager.core.database import (
    SQLITE_BUSY_RETRY_ATTEMPTS,
    is_sqlite_busy_error,
    sqlite_busy_retry_delay,
)
from AssetsManager.core.schema_defs import (
    FREE_DOWNLOAD_QUOTA_SCHEMA,
    SCHEMA_OBJECT_CONTRACT,
    validate_schema_object,
    validate_schema_objects,
)
from AssetsManager.repositories.shop_repository import (
    _CommerceRepository,
    _repository_operation,
    _transaction,
    locked_read,
)


_TABLE = "free_download_quota_windows"


def _validate_identity(identity_key: str) -> str:
    value = str(identity_key).strip()
    if not value:
        raise ValueError("identity_key is required")
    if len(value) > 512:
        raise ValueError("identity_key is too long")
    return value


class FreeDownloadQuotaRepository(_CommerceRepository):
    """Atomically consume one ordinary download quota unit per request.

    This repository intentionally does not reuse ``QuotaRepository``: that
    repository owns shop delivery-token limits, while these rows describe a
    principal/IP's free-download window for normal library downloads.
    """

    @staticmethod
    def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "identity_key": str(row[0]),
            "window_start": int(row[1]),
            "used": int(row[2]),
            "last_download_at": float(row[3]),
        }

    @_repository_operation
    def init_tables(self) -> None:
        """Compatibility ensure for raw connections; migration v10 owns DDL."""
        with _transaction(self._conn, "free_download_quota_init"):
            exists = self._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (_TABLE,)
            ).fetchone()
            if exists is not None:
                contract = dict(SCHEMA_OBJECT_CONTRACT[_TABLE])
                contract.pop("indexes", None)
                validate_schema_object(self._conn, _TABLE, contract)  # type: ignore[arg-type]
            for statement in FREE_DOWNLOAD_QUOTA_SCHEMA.split(";"):
                if sql := statement.strip():
                    self._conn.execute(sql)
            validate_schema_objects(self._conn, (_TABLE,))

    @_repository_operation
    @locked_read
    def get_window(self, identity_key: str, window_start: int) -> dict[str, Any] | None:
        identity = _validate_identity(identity_key)
        row = self._conn.execute(
            "SELECT identity_key, window_start, download_count, last_download_at "
            f"FROM {_TABLE} WHERE identity_key=? AND window_start=?",
            (identity, int(window_start)),
        ).fetchone()
        return None if row is None else self._row_to_dict(row)

    @_repository_operation
    def consume(
        self,
        identity_key: str,
        window_start: int,
        *,
        now: float,
        limit: int,
        min_interval_seconds: int,
    ) -> dict[str, Any]:
        """Atomically check interval/limit and consume one request unit.

        The result uses ``allowed`` / ``reason`` instead of raising for a
        normal policy rejection, keeping HTTP error translation out of this
        storage boundary.  The conditional UPDATE is the concurrency boundary
        even if callers use distinct managed SQLite connections.

        SQLite lock contention gets the same bounded full-transaction retry
        as :meth:`prune_windows`; a busy error can only occur before or at
        commit time, and each retry replays the complete idempotent CAS from
        a clean transaction, so no partial state is observable.
        """
        identity = _validate_identity(identity_key)
        start = int(window_start)
        if start < 0:
            raise ValueError("window_start must be non-negative")
        if float(now) < 0:
            raise ValueError("now must be non-negative")
        quota_limit = int(limit)
        interval = int(min_interval_seconds)
        if quota_limit <= 0:
            raise ValueError("limit must be positive")
        if interval < 0:
            raise ValueError("min_interval_seconds must be non-negative")

        def _consume_once() -> dict[str, Any]:
            with _transaction(self._conn, "free_download_quota_consume"):
                # Rows for prior periods have no future value for this
                # identity. Only the current identity's expired windows are
                # pruned so a system clock rollback (or a stale peer) cannot
                # reset every identity's bucket while one identity advances
                # its window.
                self._conn.execute(
                    f"DELETE FROM {_TABLE} WHERE identity_key = ? AND window_start < ?",
                    (identity, start),
                )
                self._conn.execute(
                    f"INSERT OR IGNORE INTO {_TABLE} "
                    "(identity_key, window_start, download_count, last_download_at) "
                    "VALUES (?, ?, 0, 0)",
                    (identity, start),
                )
                row = self._conn.execute(
                    "SELECT download_count, last_download_at "
                    f"FROM {_TABLE} WHERE identity_key=? AND window_start=?",
                    (identity, start),
                ).fetchone()
                if row is None:  # Defensive: INSERT OR IGNORE cannot do this.
                    raise RuntimeError("free download quota row was not created")

                used = int(row[0])
                last_download_at = float(row[1])
                remaining = max(0, quota_limit - used)
                if used >= quota_limit:
                    return {
                        "allowed": False,
                        "reason": "exhausted",
                        "used": used,
                        "remaining": remaining,
                        "retry_after_seconds": 0,
                        "last_download_at": last_download_at,
                    }

                retry_after = 0
                if last_download_at > 0 and interval > 0:
                    retry_after = max(0, math.ceil(last_download_at + interval - float(now)))
                if retry_after > 0:
                    return {
                        "allowed": False,
                        "reason": "rate_limited",
                        "used": used,
                        "remaining": remaining,
                        "retry_after_seconds": retry_after,
                        "last_download_at": last_download_at,
                    }

                updated = self._conn.execute(
                    f"UPDATE {_TABLE} SET download_count=download_count + 1, last_download_at=? "
                    "WHERE identity_key=? AND window_start=? "
                    "AND download_count=? AND download_count < ? "
                    "AND (last_download_at=0 OR last_download_at <= ?)",
                    (
                        float(now), identity, start, used, quota_limit,
                        float(now) - interval,
                    ),
                )
                if updated.rowcount == 1:
                    return {
                        "allowed": True,
                        "reason": None,
                        "used": used + 1,
                        "remaining": max(0, quota_limit - used - 1),
                        "retry_after_seconds": 0,
                        "last_download_at": float(now),
                    }

                # A concurrent writer won the CAS. Read the new state while
                # the savepoint is still active to report it precisely.
                next_row = self._conn.execute(
                    "SELECT download_count, last_download_at "
                    f"FROM {_TABLE} WHERE identity_key=? AND window_start=?",
                    (identity, start),
                ).fetchone()
                next_used = int(next_row[0]) if next_row is not None else used
                next_last = float(next_row[1]) if next_row is not None else last_download_at
                next_remaining = max(0, quota_limit - next_used)
                next_retry = 0
                if next_last > 0 and interval > 0:
                    next_retry = max(0, math.ceil(next_last + interval - float(now)))
                return {
                    "allowed": False,
                    "reason": "exhausted" if next_used >= quota_limit else "rate_limited",
                    "used": next_used,
                    "remaining": next_remaining,
                    "retry_after_seconds": next_retry,
                    "last_download_at": next_last,
                }

        outer_transaction = self._conn.in_transaction
        attempts = 1 if outer_transaction else SQLITE_BUSY_RETRY_ATTEMPTS
        for attempt in range(attempts):
            try:
                return _consume_once()
            except Exception as error:
                if (
                    not is_sqlite_busy_error(error)
                    or outer_transaction
                    or attempt + 1 >= attempts
                ):
                    raise
                try:
                    self._conn.rollback()
                except Exception:
                    pass
                time.sleep(sqlite_busy_retry_delay(attempt))
        raise AssertionError("unreachable free-download quota consume retry state")

    def prune_windows(self, before_window_start: int) -> int:
        """Delete every quota row whose window started before the cutoff.

        Deliberately separate from :meth:`consume`: that path keeps its
        delete identity-scoped so a clock rollback or stale peer is
        contained to one bucket, while this maintenance entry accepts a
        conservative caller-supplied cutoff (at least two full periods
        back) and reports how many rows it removed.
        """
        start = int(before_window_start)
        if start < 0:
            raise ValueError("before_window_start must be non-negative")
        outer_transaction = self._conn.in_transaction
        attempts = 1 if outer_transaction else SQLITE_BUSY_RETRY_ATTEMPTS
        for attempt in range(attempts):
            try:
                with _transaction(self._conn, "free_download_quota_prune"):
                    cursor = self._conn.execute(
                        f"DELETE FROM {_TABLE} WHERE window_start < ?", (start,)
                    )
                    return cursor.rowcount
            except Exception as error:
                if (
                    not is_sqlite_busy_error(error)
                    or outer_transaction
                    or attempt + 1 >= attempts
                ):
                    raise
                try:
                    self._conn.rollback()
                except Exception:
                    pass
                time.sleep(sqlite_busy_retry_delay(attempt))
        raise AssertionError("unreachable free-download quota prune retry state")
