"""SQLite persistence backend for the reconciliation queue."""
from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
from math import isfinite
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Iterator
from uuid import uuid4

from AssetsManager.application.reconciliation_queue import (
    ReconciliationKind,
    ReconciliationQueuePersistenceConflict,
    ReconciliationQueuePersistenceError,
    ReconciliationQueueClaimResult,
    ReconciliationQueueFull,
    ReconciliationQueueMutationResult,
    ReconciliationQueueRecoveryResult,
    ReconciliationQueueSnapshot,
    ReconciliationState,
    reconciliation_backoff,
    ReconciliationTask,
)
from AssetsManager.core.database import DatabaseManager, db_write_lock


def _is_sqlite_busy_error(error: BaseException) -> bool:
    """Return whether an exception chain represents a transient SQLite lock."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, sqlite3.OperationalError):
            message = str(current).lower()
            if "locked" in message or "busy" in message:
                return True
        current = current.__cause__ or current.__context__
    return False


def _retry_sqlite_busy(method: Callable[..., Any]) -> Callable[..., Any]:
    """Retry a whole store operation only for bounded transient lock errors."""
    @wraps(method)
    def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
        for retry in range(self._busy_retry_attempts + 1):
            try:
                return method(self, *args, **kwargs)
            except BaseException as error:
                if (
                    not _is_sqlite_busy_error(error)
                    or retry >= self._busy_retry_attempts
                ):
                    raise
                delay = self._busy_retry_backoff * (2**retry)
                if delay > 0:
                    time.sleep(delay)
        raise AssertionError("unreachable busy retry loop")

    return wrapped


_COLUMNS = (
    "task_id",
    "library_root",
    "path",
    "kind",
    "reason",
    "state",
    "attempts",
    "next_attempt_at_wallclock",
    "operation_ids",
    "last_error_type",
    "last_error",
    "expected_revision",
    "observed_revision",
    "created_at",
    "updated_at",
    "lease_expires_at_wallclock",
    "lease_token",
    "max_attempts",
)


def _canonical_path(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.abspath(os.path.normpath(os.fspath(path))))


class SQLiteReconciliationQueueStore:
    """Durably store one library-scoped queue through a managed SQLite connection.

    The store owns no connection lifecycle. It validates the connection's
    library-root ownership at construction and uses the connection's write gate
    for every read/write. Each replacement is committed independently when no
    caller transaction exists, or enclosed in a savepoint when an outer
    transaction is already active.
    """

    def __init__(
        self,
        *,
        connection: sqlite3.Connection,
        library_root: str | Path,
        allow_unmanaged: bool = False,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        busy_retry_attempts: int = 3,
        busy_retry_backoff: float = 0.05,
    ) -> None:
        if (
            not isinstance(busy_retry_attempts, int)
            or isinstance(busy_retry_attempts, bool)
            or busy_retry_attempts < 0
        ):
            raise ValueError("busy_retry_attempts must be a non-negative integer")
        if (
            not isinstance(busy_retry_backoff, (int, float))
            or isinstance(busy_retry_backoff, bool)
            or not isfinite(float(busy_retry_backoff))
            or busy_retry_backoff < 0
            or busy_retry_backoff >= 60.0
        ):
            raise ValueError(
                "busy_retry_backoff must be finite, non-negative, and less than 60 seconds"
            )
        self.library_root = _canonical_path(library_root)
        self._busy_retry_attempts = busy_retry_attempts
        self._busy_retry_backoff = busy_retry_backoff
        self._clock = clock
        self._wall_clock = wall_clock
        self.connection = DatabaseManager.validate_connection_owner(
            self.library_root,
            connection,
            allow_unmanaged=allow_unmanaged,
        )

    def load(self) -> tuple[ReconciliationTask, ...]:
        """Load all persisted tasks for this library, failing closed on corruption."""
        return self.load_snapshot().tasks

    @_retry_sqlite_busy
    def load_snapshot(self) -> ReconciliationQueueSnapshot:
        """Load tasks and generation from one SQLite read transaction."""
        now_monotonic = self._clock()
        now_wallclock = self._wall_clock()
        try:
            with db_write_lock(self.connection):
                with self._read_transaction():
                    generation = self._read_generation_unlocked()
                    rows = self.connection.execute(
                        "SELECT "
                        + ", ".join(_COLUMNS)
                        + " FROM reconciliation_tasks "
                        "WHERE library_root=? "
                        "ORDER BY created_at ASC, task_id ASC",
                        (self.library_root,),
                    ).fetchall()
        except sqlite3.Error as exc:
            raise ReconciliationQueuePersistenceError(
                "Cannot load reconciliation queue snapshot from SQLite"
            ) from exc
        try:
            tasks = tuple(
                self._row_to_task(
                    row,
                    now_monotonic=now_monotonic,
                    now_wallclock=now_wallclock,
                )
                for row in rows
            )
            return ReconciliationQueueSnapshot(tasks=tasks, generation=generation)
        except (TypeError, ValueError, json.JSONDecodeError, OverflowError) as exc:
            raise ReconciliationQueuePersistenceError(
                "Invalid reconciliation task row in SQLite"
            ) from exc

    @_retry_sqlite_busy
    def replace(
        self,
        tasks: tuple[ReconciliationTask, ...],
        *,
        expected_generation: int | None = None,
    ) -> int:
        """Atomically replace the durable snapshot with optional generation CAS."""
        if any(task.library_root != self.library_root for task in tasks):
            raise ValueError("Reconciliation task belongs to a different library root")
        now_monotonic = self._clock()
        now_wallclock = self._wall_clock()
        values = [
            self._task_values(task, now_monotonic=now_monotonic, now_wallclock=now_wallclock)
            for task in tasks
        ]
        next_generation = 0
        try:
            with db_write_lock(self.connection):
                with self._transaction(immediate=True):
                    current_generation = self._read_generation_unlocked()
                    if (
                        expected_generation is not None
                        and current_generation != expected_generation
                    ):
                        raise ReconciliationQueuePersistenceConflict(
                            "Reconciliation queue generation conflict: "
                            f"expected {expected_generation}, found {current_generation}",
                            retryable=True,
                            operation="replace",
                        )
                    self.connection.execute(
                        "DELETE FROM reconciliation_tasks WHERE library_root=?",
                        (self.library_root,),
                    )
                    if values:
                        placeholders = ", ".join("?" for _ in _COLUMNS)
                        self.connection.executemany(
                            "INSERT INTO reconciliation_tasks ("
                            + ", ".join(_COLUMNS)
                            + ") VALUES ("
                            + placeholders
                            + ")",
                            values,
                        )
                    next_generation = self._advance_generation_unlocked(
                        current_generation,
                        updated_at=now_wallclock,
                    )
        except ReconciliationQueuePersistenceError:
            raise
        except (sqlite3.Error, TypeError, ValueError, OverflowError) as exc:
            raise ReconciliationQueuePersistenceError(
                "Cannot persist reconciliation queue snapshot to SQLite"
            ) from exc
        return next_generation

    @_retry_sqlite_busy
    def enqueue_or_merge(
        self,
        *,
        path: str | Path,
        reason: str,
        operation_id: str | None,
        expected_revision: int | None,
        observed_revision: int | None,
        max_tasks: int,
        max_attempts: int,
        now: float,
    ) -> ReconciliationQueueMutationResult:
        """Upsert one task with SQL dedupe and bounded-capacity semantics."""
        if max_tasks < 1 or max_attempts < 1:
            raise ValueError("queue bounds must be positive")
        path_value = _canonical_path(path)
        kind = ReconciliationKind.ASSET_INDEX_ROOT_RESCAN.value
        now_wallclock = self._wall_clock()
        try:
            with db_write_lock(self.connection):
                with self._transaction(immediate=True):
                    current_generation = self._read_generation_unlocked()
                    existing_row = self.connection.execute(
                        "SELECT "
                        + ", ".join(_COLUMNS)
                        + " FROM reconciliation_tasks WHERE library_root=? "
                        "AND path=? AND kind=?",
                        (self.library_root, path_value, kind),
                    ).fetchone()
                    existing = (
                        None
                        if existing_row is None
                        else self._row_to_task(
                            existing_row,
                            now_monotonic=now,
                            now_wallclock=now_wallclock,
                        )
                    )
                    if existing is not None and existing.state in {
                        ReconciliationState.PENDING,
                        ReconciliationState.RUNNING,
                        ReconciliationState.RETRYABLE,
                    }:
                        operation_ids = list(existing.operation_ids)
                        if operation_id and operation_id not in operation_ids:
                            operation_ids.append(operation_id)
                        updated = self.connection.execute(
                            "UPDATE reconciliation_tasks SET reason=?, "
                            "operation_ids=?, expected_revision=COALESCE(?, expected_revision), "
                            "observed_revision=COALESCE(?, observed_revision), updated_at=? "
                            "WHERE task_id=? AND library_root=? AND path=? AND kind=? "
                            "AND state IN ('pending', 'running', 'retryable')",
                            (
                                reason or existing.reason,
                                json.dumps(operation_ids, ensure_ascii=False),
                                expected_revision,
                                observed_revision,
                                now,
                                existing.task_id,
                                self.library_root,
                                path_value,
                                kind,
                            ),
                        ).rowcount
                        if updated != 1:
                            raise ReconciliationQueuePersistenceConflict(
                                "Reconciliation task enqueue merge lost ownership",
                                retryable=True,
                                operation="enqueue",
                            )
                        task_id = existing.task_id
                    else:
                        if existing is not None:
                            deleted = self.connection.execute(
                                "DELETE FROM reconciliation_tasks WHERE task_id=? "
                                "AND library_root=? AND path=? AND kind=?",
                                (
                                    existing.task_id,
                                    self.library_root,
                                    path_value,
                                    kind,
                                ),
                            ).rowcount
                            if deleted != 1:
                                raise ReconciliationQueuePersistenceConflict(
                                    "Finished reconciliation task replacement lost ownership",
                                    retryable=True,
                                    operation="enqueue",
                                )
                        count = self.connection.execute(
                            "SELECT COUNT(*) FROM reconciliation_tasks WHERE library_root=?",
                            (self.library_root,),
                        ).fetchone()[0]
                        if int(str(count)) >= max_tasks:
                            victim = self.connection.execute(
                                "SELECT task_id FROM reconciliation_tasks "
                                "WHERE library_root=? AND state IN "
                                "('succeeded', 'terminal', 'cancelled') "
                                "ORDER BY updated_at ASC, created_at ASC, task_id ASC LIMIT 1",
                                (self.library_root,),
                            ).fetchone()
                            if victim is None:
                                raise ReconciliationQueueFull(
                                    f"reconciliation queue is full ({max_tasks})"
                                )
                            self.connection.execute(
                                "DELETE FROM reconciliation_tasks WHERE task_id=? "
                                "AND library_root=?",
                                (str(victim[0]), self.library_root),
                            )
                        task_id = f"recon-{uuid4().hex}"
                        operation_ids = [operation_id] if operation_id else []
                        self.connection.execute(
                            "INSERT INTO reconciliation_tasks ("
                            + ", ".join(_COLUMNS)
                            + ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                task_id,
                                self.library_root,
                                path_value,
                                kind,
                                reason,
                                ReconciliationState.PENDING.value,
                                0,
                                now_wallclock,
                                json.dumps(operation_ids, ensure_ascii=False),
                                None,
                                None,
                                expected_revision,
                                observed_revision,
                                now,
                                now,
                                None,
                                None,
                                max_attempts,
                            ),
                        )
                    return self._mutation_result_unlocked(
                        task_id,
                        current_generation=current_generation,
                        now_monotonic=now,
                        now_wallclock=now_wallclock,
                    )
        except (ReconciliationQueueFull, ReconciliationQueuePersistenceError):
            raise
        except (sqlite3.Error, TypeError, ValueError, OverflowError) as exc:
            raise ReconciliationQueuePersistenceError(
                "Cannot atomically enqueue reconciliation task in SQLite"
            ) from exc

    @_retry_sqlite_busy
    def claim_next(
        self,
        *,
        now: float,
        lease_seconds: float,
    ) -> ReconciliationQueueClaimResult:
        """Claim one due task with a SQLite transaction-level single-writer CAS."""
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        now_wallclock = self._wall_clock()
        try:
            with db_write_lock(self.connection):
                with self._transaction(immediate=True):
                    current_generation = self._read_generation_unlocked()
                    changed = self._recover_expired_running_unlocked(
                        now_monotonic=now,
                        now_wallclock=now_wallclock,
                    )
                    candidate = self.connection.execute(
                        "SELECT task_id FROM reconciliation_tasks "
                        "WHERE library_root=? "
                        "AND state IN ('pending', 'retryable') "
                        "AND attempts < max_attempts "
                        "AND next_attempt_at_wallclock <= ? "
                        "ORDER BY next_attempt_at_wallclock ASC, created_at ASC, task_id ASC "
                        "LIMIT 1",
                        (self.library_root, now_wallclock),
                    ).fetchone()
                    claimed: ReconciliationTask | None = None
                    if candidate is not None:
                        task_id = str(candidate[0])
                        lease_token = uuid4().hex
                        updated = self.connection.execute(
                            "UPDATE reconciliation_tasks SET "
                            "state='running', attempts=attempts + 1, "
                            "lease_expires_at_wallclock=?, lease_token=?, updated_at=? "
                            "WHERE task_id=? AND library_root=? "
                            "AND state IN ('pending', 'retryable') "
                            "AND attempts < max_attempts "
                            "AND next_attempt_at_wallclock <= ?",
                            (
                                now_wallclock + lease_seconds,
                                lease_token,
                                now,
                                task_id,
                                self.library_root,
                                now_wallclock,
                            ),
                        ).rowcount
                        if updated != 1:
                            raise ReconciliationQueuePersistenceConflict(
                                "Reconciliation task claim lost ownership",
                                retryable=True,
                                operation="claim",
                            )
                        changed = True
                        row = self.connection.execute(
                            "SELECT "
                            + ", ".join(_COLUMNS)
                            + " FROM reconciliation_tasks WHERE task_id=?",
                            (task_id,),
                        ).fetchone()
                        if row is None:
                            raise ReconciliationQueuePersistenceConflict(
                                "Claimed reconciliation task disappeared",
                                retryable=True,
                                operation="claim",
                            )
                        claimed = self._row_to_task(
                            row,
                            now_monotonic=now,
                            now_wallclock=now_wallclock,
                        )
                    if changed:
                        generation = self._advance_generation_unlocked(
                            current_generation,
                            updated_at=now_wallclock,
                        )
                    else:
                        generation = current_generation
                    rows = self.connection.execute(
                        "SELECT "
                        + ", ".join(_COLUMNS)
                        + " FROM reconciliation_tasks WHERE library_root=? "
                        "ORDER BY created_at ASC, task_id ASC",
                        (self.library_root,),
                    ).fetchall()
                    tasks = tuple(
                        self._row_to_task(
                            row,
                            now_monotonic=now,
                            now_wallclock=now_wallclock,
                        )
                        for row in rows
                    )
                    snapshot = ReconciliationQueueSnapshot(
                        tasks=tasks,
                        generation=generation,
                    )
            return ReconciliationQueueClaimResult(
                snapshot=snapshot,
                claimed=claimed,
            )
        except ReconciliationQueuePersistenceError:
            raise
        except (sqlite3.Error, TypeError, ValueError, OverflowError) as exc:
            raise ReconciliationQueuePersistenceError(
                "Cannot atomically claim reconciliation task in SQLite"
            ) from exc

    @_retry_sqlite_busy
    def renew_lease(
        self,
        task_id: str,
        *,
        expected_attempts: int,
        lease_token: str | None,
        lease_seconds: float,
        now: float,
    ) -> ReconciliationQueueMutationResult:
        """Extend a running lease with task/attempt/token CAS."""
        if (
            not isinstance(lease_seconds, (int, float))
            or isinstance(lease_seconds, bool)
            or not isfinite(float(lease_seconds))
            or lease_seconds <= 0
        ):
            raise ValueError("lease_seconds must be finite and positive")
        now_wallclock = self._wall_clock()
        try:
            with db_write_lock(self.connection):
                with self._transaction(immediate=True):
                    current_generation = self._read_generation_unlocked()
                    updated = self.connection.execute(
                        "UPDATE reconciliation_tasks SET lease_expires_at_wallclock=?, "
                        "updated_at=? WHERE task_id=? AND library_root=? "
                        "AND state='running' AND attempts=? "
                        "AND lease_expires_at_wallclock > ? AND lease_token=?",
                        (
                            now_wallclock + float(lease_seconds),
                            now,
                            task_id,
                            self.library_root,
                            expected_attempts,
                            now_wallclock,
                            lease_token,
                        ),
                    ).rowcount
                    if updated != 1:
                        raise ReconciliationQueuePersistenceConflict(
                            "Reconciliation task lease renewal lost ownership",
                            stale_worker_completion=True,
                            operation="renew",
                        )
                    return self._mutation_result_unlocked(
                        task_id,
                        current_generation=current_generation,
                        now_monotonic=now,
                        now_wallclock=now_wallclock,
                    )
        except ReconciliationQueuePersistenceError:
            raise
        except (sqlite3.Error, TypeError, ValueError, OverflowError) as exc:
            raise ReconciliationQueuePersistenceError(
                "Cannot renew reconciliation task lease in SQLite"
            ) from exc

    @_retry_sqlite_busy
    def mark_succeeded(
        self,
        task_id: str,
        *,
        revision: int | None,
        expected_attempts: int,
        lease_token: str | None,
        now: float,
    ) -> ReconciliationQueueMutationResult:
        """Complete a running task with task-id/attempt/lease CAS."""
        now_wallclock = self._wall_clock()
        try:
            with db_write_lock(self.connection):
                with self._transaction(immediate=True):
                    current_generation = self._read_generation_unlocked()
                    updated = self.connection.execute(
                        "UPDATE reconciliation_tasks SET state='succeeded', "
                        "observed_revision=COALESCE(?, observed_revision), "
                        "last_error_type=NULL, last_error=NULL, "
                        "lease_expires_at_wallclock=NULL, lease_token=NULL, updated_at=? "
                        "WHERE task_id=? AND library_root=? AND state='running' "
                        "AND attempts=? AND lease_expires_at_wallclock > ? AND lease_token=?",
                        (
                            revision,
                            now,
                            task_id,
                            self.library_root,
                            expected_attempts,
                            now_wallclock,
                            lease_token,
                        ),
                    ).rowcount
                    if updated != 1:
                        raise ReconciliationQueuePersistenceConflict(
                            "Reconciliation task completion lost lease ownership",
                            stale_worker_completion=True,
                            operation="completion",
                        )
                    return self._mutation_result_unlocked(
                        task_id,
                        current_generation=current_generation,
                        now_monotonic=now,
                        now_wallclock=now_wallclock,
                    )
        except ReconciliationQueuePersistenceError:
            raise
        except (sqlite3.Error, TypeError, ValueError, OverflowError) as exc:
            raise ReconciliationQueuePersistenceError(
                "Cannot mark reconciliation task succeeded in SQLite"
            ) from exc

    @_retry_sqlite_busy
    def mark_retryable(
        self,
        task_id: str,
        *,
        error_type: str | None,
        error: str | None,
        reason: str | None,
        next_attempt_at: float | None,
        expected_attempts: int,
        lease_token: str | None,
        now: float,
    ) -> ReconciliationQueueMutationResult:
        """Retry or exhaust a running task with task-id/attempt/lease CAS."""
        now_wallclock = self._wall_clock()
        try:
            with db_write_lock(self.connection):
                with self._transaction(immediate=True):
                    current_generation = self._read_generation_unlocked()
                    current = self._task_by_id_unlocked(
                        task_id,
                        now_monotonic=now,
                        now_wallclock=now_wallclock,
                    )
                    if current is None:
                        raise ReconciliationQueuePersistenceConflict(
                            f"Reconciliation task disappeared: {task_id}",
                            stale_worker_completion=True,
                            operation="completion",
                        )
                    if current.state is not ReconciliationState.RUNNING:
                        raise ReconciliationQueuePersistenceConflict(
                            f"Reconciliation task is no longer running: {task_id}",
                            stale_worker_completion=True,
                            operation="completion",
                        )
                    retry_reason = reason or current.reason
                    if current.attempts >= current.max_attempts:
                        state = ReconciliationState.TERMINAL.value
                        retry_at_wallclock = None
                    else:
                        state = ReconciliationState.RETRYABLE.value
                        retry_at_wallclock = (
                            now_wallclock + max(0.0, next_attempt_at - now)
                            if next_attempt_at is not None
                            else now_wallclock
                            + reconciliation_backoff(retry_reason, current.attempts)
                        )
                    updated = self.connection.execute(
                        "UPDATE reconciliation_tasks SET state=?, reason=?, "
                        "next_attempt_at_wallclock=COALESCE(?, next_attempt_at_wallclock), "
                        "last_error_type=?, last_error=?, lease_expires_at_wallclock=NULL, lease_token=NULL, "
                        "updated_at=? WHERE task_id=? AND library_root=? "
                        "AND state='running' AND attempts=? "
                        "AND lease_expires_at_wallclock > ? AND lease_token=?",
                        (
                            state,
                            retry_reason,
                            retry_at_wallclock,
                            error_type,
                            error,
                            now,
                            task_id,
                            self.library_root,
                            expected_attempts,
                            now_wallclock,
                            lease_token,
                        ),
                    ).rowcount
                    if updated != 1:
                        raise ReconciliationQueuePersistenceConflict(
                            "Reconciliation task retry lost lease ownership",
                            stale_worker_completion=True,
                            operation="completion",
                        )
                    return self._mutation_result_unlocked(
                        task_id,
                        current_generation=current_generation,
                        now_monotonic=now,
                        now_wallclock=now_wallclock,
                    )
        except ReconciliationQueuePersistenceError:
            raise
        except (sqlite3.Error, TypeError, ValueError, OverflowError) as exc:
            raise ReconciliationQueuePersistenceError(
                "Cannot mark reconciliation task retryable in SQLite"
            ) from exc

    @_retry_sqlite_busy
    def mark_terminal(
        self,
        task_id: str,
        *,
        error_type: str | None,
        error: str | None,
        expected_attempts: int | None,
        lease_token: str | None,
        now: float,
    ) -> ReconciliationQueueMutationResult:
        """Terminally resolve a task with active-state/lease CAS."""
        return self._mark_nonretryable(
            task_id,
            target_state=ReconciliationState.TERMINAL.value,
            error_type=error_type,
            error=error,
            expected_attempts=expected_attempts,
            lease_token=lease_token,
            now=now,
        )

    @_retry_sqlite_busy
    def cancel(
        self,
        task_id: str,
        *,
        expected_attempts: int | None,
        lease_token: str | None,
        now: float,
    ) -> ReconciliationQueueMutationResult:
        """Cancel a task with active-state/lease CAS."""
        return self._mark_nonretryable(
            task_id,
            target_state=ReconciliationState.CANCELLED.value,
            error_type=None,
            error=None,
            expected_attempts=expected_attempts,
            lease_token=lease_token,
            now=now,
        )

    def _mark_nonretryable(
        self,
        task_id: str,
        *,
        target_state: str,
        error_type: str | None,
        error: str | None,
        expected_attempts: int | None,
        lease_token: str | None,
        now: float,
    ) -> ReconciliationQueueMutationResult:
        now_wallclock = self._wall_clock()
        try:
            with db_write_lock(self.connection):
                with self._transaction(immediate=True):
                    current_generation = self._read_generation_unlocked()
                    current = self._task_by_id_unlocked(
                        task_id,
                        now_monotonic=now,
                        now_wallclock=now_wallclock,
                    )
                    if current is None:
                        raise ReconciliationQueuePersistenceConflict(
                            f"Reconciliation task disappeared: {task_id}",
                            stale_worker_completion=expected_attempts is not None,
                            operation="state_mutation",
                        )
                    if current.state in {
                        ReconciliationState.SUCCEEDED,
                        ReconciliationState.TERMINAL,
                        ReconciliationState.CANCELLED,
                    }:
                        return self._mutation_result_unlocked(
                            task_id,
                            current_generation=current_generation,
                            now_monotonic=now,
                            now_wallclock=now_wallclock,
                            changed=False,
                        )
                    if expected_attempts is not None:
                        if not lease_token or current.lease_token != lease_token:
                            raise ReconciliationQueuePersistenceConflict(
                                "Reconciliation task lease token does not match current ownership",
                                stale_worker_completion=True,
                                operation="state_mutation",
                            )
                        # A worker-scoped terminal/cancel mutation must retain
                        # the same running lease predicate even if recovery has
                        # already moved the row to retryable.  Never let an
                        # expired worker terminalize a newer queue state.
                        if current.state is not ReconciliationState.RUNNING:
                            raise ReconciliationQueuePersistenceConflict(
                                "Reconciliation task is no longer running for worker state mutation",
                                stale_worker_completion=True,
                                operation="state_mutation",
                            )
                        predicate = (
                            "state='running' AND attempts=? "
                            "AND lease_expires_at_wallclock > ? AND lease_token=?"
                        )
                        predicate_params: tuple[object, ...] = (
                            expected_attempts,
                            now_wallclock,
                            lease_token,
                        )
                    elif current.state is ReconciliationState.RUNNING:
                        raise ReconciliationQueuePersistenceConflict(
                            "Running reconciliation task requires attempt CAS",
                            operation="state_mutation",
                        )
                    else:
                        predicate = "state IN ('pending', 'retryable')"
                        predicate_params = ()
                    updated = self.connection.execute(
                        "UPDATE reconciliation_tasks SET state=?, "
                        "last_error_type=?, last_error=?, lease_expires_at_wallclock=NULL, lease_token=NULL, "
                        "updated_at=? WHERE task_id=? AND library_root=? AND "
                        + predicate,
                        (
                            target_state,
                            error_type,
                            error,
                            now,
                            task_id,
                            self.library_root,
                            *predicate_params,
                        ),
                    ).rowcount
                    if updated != 1:
                        raise ReconciliationQueuePersistenceConflict(
                            "Reconciliation task terminal/cancel CAS lost ownership",
                            stale_worker_completion=expected_attempts is not None,
                            operation="state_mutation",
                        )
                    return self._mutation_result_unlocked(
                        task_id,
                        current_generation=current_generation,
                        now_monotonic=now,
                        now_wallclock=now_wallclock,
                    )
        except ReconciliationQueuePersistenceError:
            raise
        except (sqlite3.Error, TypeError, ValueError, OverflowError) as exc:
            raise ReconciliationQueuePersistenceError(
                "Cannot mutate reconciliation task state in SQLite"
            ) from exc

    def _mutation_result_unlocked(
        self,
        task_id: str,
        *,
        current_generation: int,
        now_monotonic: float,
        now_wallclock: float,
        changed: bool = True,
    ) -> ReconciliationQueueMutationResult:
        generation = (
            self._advance_generation_unlocked(
                current_generation,
                updated_at=now_wallclock,
            )
            if changed
            else current_generation
        )
        rows = self.connection.execute(
            "SELECT "
            + ", ".join(_COLUMNS)
            + " FROM reconciliation_tasks WHERE library_root=? "
            "ORDER BY created_at ASC, task_id ASC",
            (self.library_root,),
        ).fetchall()
        tasks = tuple(
            self._row_to_task(
                row,
                now_monotonic=now_monotonic,
                now_wallclock=now_wallclock,
            )
            for row in rows
        )
        task = next((item for item in tasks if item.task_id == task_id), None)
        if task is None:
            raise ReconciliationQueuePersistenceConflict(
                f"Reconciliation task disappeared after mutation: {task_id}",
                operation="mutation_result",
            )
        return ReconciliationQueueMutationResult(
            snapshot=ReconciliationQueueSnapshot(
                tasks=tasks,
                generation=generation,
            ),
            task=task,
        )

    def _task_by_id_unlocked(
        self,
        task_id: str,
        *,
        now_monotonic: float,
        now_wallclock: float,
    ) -> ReconciliationTask | None:
        row = self.connection.execute(
            "SELECT "
            + ", ".join(_COLUMNS)
            + " FROM reconciliation_tasks WHERE task_id=? AND library_root=?",
            (task_id, self.library_root),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_task(
            row,
            now_monotonic=now_monotonic,
            now_wallclock=now_wallclock,
        )

    @_retry_sqlite_busy
    def recover_expired_running(
        self,
        *,
        now: float,
    ) -> ReconciliationQueueRecoveryResult:
        """Recover expired leases using one per-task SQL transaction."""
        now_wallclock = self._wall_clock()
        try:
            with db_write_lock(self.connection):
                with self._transaction(immediate=True):
                    current_generation = self._read_generation_unlocked()
                    recovered_ids = self._recover_expired_running_unlocked(
                        now_monotonic=now,
                        now_wallclock=now_wallclock,
                    )
                    generation = (
                        self._advance_generation_unlocked(
                            current_generation,
                            updated_at=now_wallclock,
                        )
                        if recovered_ids
                        else current_generation
                    )
                    rows = self.connection.execute(
                        "SELECT "
                        + ", ".join(_COLUMNS)
                        + " FROM reconciliation_tasks WHERE library_root=? "
                        "ORDER BY created_at ASC, task_id ASC",
                        (self.library_root,),
                    ).fetchall()
                    tasks = tuple(
                        self._row_to_task(
                            row,
                            now_monotonic=now,
                            now_wallclock=now_wallclock,
                        )
                        for row in rows
                    )
                    recovered_set = set(recovered_ids)
                    recovered = tuple(
                        task for task in tasks if task.task_id in recovered_set
                    )
                    return ReconciliationQueueRecoveryResult(
                        snapshot=ReconciliationQueueSnapshot(
                            tasks=tasks,
                            generation=generation,
                        ),
                        recovered=recovered,
                    )
        except ReconciliationQueuePersistenceError:
            raise
        except (sqlite3.Error, TypeError, ValueError, OverflowError) as exc:
            raise ReconciliationQueuePersistenceError(
                "Cannot recover expired reconciliation leases in SQLite"
            ) from exc

    def _recover_expired_running_unlocked(
        self,
        *,
        now_monotonic: float,
        now_wallclock: float,
    ) -> tuple[str, ...]:
        rows = self.connection.execute(
            "SELECT task_id, reason, attempts, max_attempts "
            "FROM reconciliation_tasks WHERE library_root=? AND state='running' "
            "AND (lease_token IS NULL OR lease_expires_at_wallclock IS NULL "
            "OR lease_expires_at_wallclock <= ?)",
            (self.library_root, now_wallclock),
        ).fetchall()
        recovered_ids: list[str] = []
        for row in rows:
            task_id = str(row[0])
            reason = str(row[1])
            attempts = int(str(row[2]))
            max_attempts = int(str(row[3]))
            if attempts >= max_attempts:
                self.connection.execute(
                    "UPDATE reconciliation_tasks SET state='terminal', "
                    "last_error_type='LeaseExpired', last_error='worker lease expired', "
                    "lease_expires_at_wallclock=NULL, lease_token=NULL, updated_at=? "
                    "WHERE task_id=? AND library_root=? AND state='running'",
                    (now_monotonic, task_id, self.library_root),
                )
            else:
                next_attempt = now_wallclock + reconciliation_backoff(
                    reason,
                    max(1, attempts),
                )
                self.connection.execute(
                    "UPDATE reconciliation_tasks SET state='retryable', "
                    "next_attempt_at_wallclock=?, last_error_type='LeaseExpired', "
                    "last_error='worker lease expired', lease_expires_at_wallclock=NULL, lease_token=NULL, "
                    "updated_at=? WHERE task_id=? AND library_root=? AND state='running'",
                    (
                        next_attempt,
                        now_monotonic,
                        task_id,
                        self.library_root,
                    ),
                )
            recovered_ids.append(task_id)
        return tuple(recovered_ids)

    @contextmanager
    def _read_transaction(self) -> Iterator[None]:
        """Read tasks and generation from one consistent connection snapshot."""
        outer_transaction = self.connection.in_transaction
        owns_transaction = False
        try:
            if not outer_transaction:
                self.connection.execute("BEGIN")
                owns_transaction = True
            yield
            if owns_transaction:
                self.connection.commit()
                owns_transaction = False
        except BaseException:
            if owns_transaction and self.connection.in_transaction:
                self.connection.rollback()
            raise

    @contextmanager
    def _transaction(self, *, immediate: bool = False) -> Iterator[None]:
        """Commit independently or preserve an existing caller transaction."""
        outer_transaction = self.connection.in_transaction
        savepoint = f"rq_store_{uuid4().hex}"
        active_savepoint = False
        owns_transaction = False
        try:
            if outer_transaction:
                self.connection.execute(f"SAVEPOINT {savepoint}")
                active_savepoint = True
            else:
                self.connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
                owns_transaction = True
            yield
            if active_savepoint:
                self.connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                active_savepoint = False
            elif owns_transaction:
                self.connection.commit()
                owns_transaction = False
        except BaseException:
            if active_savepoint:
                try:
                    self.connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                finally:
                    self.connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            elif owns_transaction and self.connection.in_transaction:
                self.connection.rollback()
            raise

    def _advance_generation_unlocked(
        self,
        current_generation: int,
        *,
        updated_at: float,
    ) -> int:
        next_generation = current_generation + 1
        if current_generation == 0 and not self._state_row_exists_unlocked():
            self.connection.execute(
                "INSERT INTO reconciliation_queue_state "
                "(library_root, generation, updated_at) VALUES (?, ?, ?)",
                (self.library_root, next_generation, updated_at),
            )
            return next_generation
        updated = self.connection.execute(
            "UPDATE reconciliation_queue_state SET generation=?, updated_at=? "
            "WHERE library_root=? AND generation=?",
            (
                next_generation,
                updated_at,
                self.library_root,
                current_generation,
            ),
        ).rowcount
        if updated != 1:
            raise ReconciliationQueuePersistenceConflict(
                "Reconciliation queue generation update lost ownership",
                retryable=True,
                operation="generation",
            )
        return next_generation

    def _state_row_exists_unlocked(self) -> bool:
        return (
            self.connection.execute(
                "SELECT 1 FROM reconciliation_queue_state WHERE library_root=?",
                (self.library_root,),
            ).fetchone()
            is not None
        )

    def _read_generation_unlocked(self) -> int:
        row = self.connection.execute(
            "SELECT generation FROM reconciliation_queue_state WHERE library_root=?",
            (self.library_root,),
        ).fetchone()
        if row is None:
            return 0
        generation = int(str(row[0]))
        if generation < 0:
            raise ValueError("invalid reconciliation queue generation")
        return generation

    def _task_values(
        self,
        task: ReconciliationTask,
        *,
        now_monotonic: float,
        now_wallclock: float,
    ) -> tuple[object, ...]:
        next_attempt_at_wallclock = now_wallclock + max(
            0.0,
            task.next_attempt_at - now_monotonic,
        )
        lease_expires_at_wallclock = (
            now_wallclock + max(0.0, task.lease_expires_at - now_monotonic)
            if task.lease_expires_at is not None
            else None
        )
        return (
            task.task_id,
            task.library_root,
            task.path,
            task.kind.value,
            task.reason,
            task.state.value,
            task.attempts,
            next_attempt_at_wallclock,
            json.dumps(list(task.operation_ids), ensure_ascii=False),
            task.last_error_type,
            task.last_error,
            task.expected_revision,
            task.observed_revision,
            task.created_at,
            task.updated_at,
            lease_expires_at_wallclock,
            task.lease_token,
            task.max_attempts,
        )

    @staticmethod
    def _row_to_task(
        row: sqlite3.Row | tuple[object, ...],
        *,
        now_monotonic: float,
        now_wallclock: float,
    ) -> ReconciliationTask:
        if len(row) != len(_COLUMNS):
            raise ValueError("invalid reconciliation task row shape")
        operation_ids = json.loads(str(row[8]))
        if not isinstance(operation_ids, list | tuple):
            raise ValueError("operation_ids must be a list")
        max_attempts = int(str(row[17]))
        attempts = int(str(row[6]))
        if max_attempts < 1 or attempts < 0:
            raise ValueError("invalid reconciliation attempt bounds")
        return ReconciliationTask(
            task_id=str(row[0]),
            library_root=_canonical_path(str(row[1])),
            path=_canonical_path(str(row[2])),
            kind=ReconciliationKind(str(row[3])),
            reason=str(row[4]),
            state=ReconciliationState(str(row[5])),
            attempts=attempts,
            next_attempt_at=(
                now_monotonic
                if row[7] is None
                else now_monotonic + max(0.0, float(str(row[7])) - now_wallclock)
            ),
            operation_ids=tuple(str(value) for value in operation_ids),
            last_error_type=str(row[9]) if row[9] is not None else None,
            last_error=str(row[10]) if row[10] is not None else None,
            expected_revision=(
                int(str(row[11])) if row[11] is not None else None
            ),
            observed_revision=(
                int(str(row[12])) if row[12] is not None else None
            ),
            created_at=float(str(row[13])),
            updated_at=float(str(row[14])),
            lease_expires_at=(
                None
                if row[15] is None
                else now_monotonic + max(0.0, float(str(row[15])) - now_wallclock)
            ),
            lease_token=str(row[16]) if row[16] is not None else None,
            max_attempts=max_attempts,
        )
