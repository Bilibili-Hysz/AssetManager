"""SQLite persistence backend for the reconciliation queue."""
from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
import hashlib
import logging
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
    ReconciliationTaskTransition,
    ReconciliationTransitionOutboxEntry,
    ReconciliationTransitionOutboxDeadLetter,
    ReconciliationTransitionOutboxMetrics,
    ReconciliationTransitionOutboxPruneResult,
    ReconciliationState,
    reconciliation_backoff,
    ReconciliationTask,
    _task_from_json,
    _task_to_json,
    normalize_reconciliation_payload,
)
from AssetsManager.core.database import DatabaseManager, db_write_lock


_log = logging.getLogger(__name__)


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
    "payload",
)

_OUTBOX_DELIVERY_BACKOFF_BASE_SECONDS = 15.0
_OUTBOX_DELIVERY_BACKOFF_MAX_SECONDS = 300.0
_OUTBOX_DELIVERY_BACKOFF_JITTER_FRACTION = 0.2
_DEFAULT_TRANSITION_OUTBOX_MAX_DELIVERY_ATTEMPTS = 8


class _TransitionOutboxDeliveryAttemptsExhausted(RuntimeError):
    """Internal diagnostic recorded when a valid event exhausts delivery retries."""


def _outbox_delivery_backoff(
    *,
    library_root: str,
    event_id: int,
    delivery_attempts: int,
) -> float:
    """Return a bounded, process-stable retry delay for one delivery attempt."""
    if event_id < 1:
        raise ValueError("outbox event_id must be positive")
    if delivery_attempts < 1:
        raise ValueError("outbox delivery attempts must be positive")
    exponent = min(delivery_attempts - 1, 5)
    base = min(
        _OUTBOX_DELIVERY_BACKOFF_MAX_SECONDS,
        _OUTBOX_DELIVERY_BACKOFF_BASE_SECONDS * (2**exponent),
    )
    material = f"{library_root}\x00{event_id}\x00{delivery_attempts}".encode(
        "utf-8",
        "surrogatepass",
    )
    jitter_bits = int.from_bytes(
        hashlib.blake2s(material, digest_size=8).digest(),
        "big",
    )
    jitter_ratio = jitter_bits / ((1 << 64) - 1)
    # The jitter spreads low-attempt retries, but the public contract is a
    # *final* 300-second ceiling rather than a ceiling before jitter.
    return min(
        _OUTBOX_DELIVERY_BACKOFF_MAX_SECONDS,
        base * (1.0 + _OUTBOX_DELIVERY_BACKOFF_JITTER_FRACTION * jitter_ratio),
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
        transition_outbox_max_delivery_attempts: int = (
            _DEFAULT_TRANSITION_OUTBOX_MAX_DELIVERY_ATTEMPTS
        ),
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
        if (
            not isinstance(transition_outbox_max_delivery_attempts, int)
            or isinstance(transition_outbox_max_delivery_attempts, bool)
            or transition_outbox_max_delivery_attempts < 1
        ):
            raise ValueError(
                "transition_outbox_max_delivery_attempts must be a positive integer"
            )
        self.library_root = _canonical_path(library_root)
        self._busy_retry_attempts = busy_retry_attempts
        self._busy_retry_backoff = busy_retry_backoff
        self._transition_outbox_max_delivery_attempts = (
            transition_outbox_max_delivery_attempts
        )
        self._clock = clock
        self._wall_clock = wall_clock
        self.connection = DatabaseManager.validate_connection_owner(
            self.library_root,
            connection,
            allow_unmanaged=allow_unmanaged,
        )
        # Standalone compatibility tests and third-party adapters may still
        # construct this store against a pre-v44 schema.  Keep their existing
        # queue behavior while production bootstrap (which runs migrations)
        # enables the durable transition hand-off automatically.
        self._transition_outbox_enabled = self._table_exists(
            "reconciliation_transition_outbox"
        )
        self._transition_outbox_dead_letters_enabled = self._table_exists(
            "reconciliation_transition_outbox_dead_letters"
        )
        self._transition_outbox_backoff_enabled = (
            self._transition_outbox_enabled
            and self._table_has_column(
                "reconciliation_transition_outbox",
                "next_delivery_at",
            )
        )

    @property
    def transition_outbox_enabled(self) -> bool:
        """Whether this connection has the v44 durable transition outbox."""
        return self._transition_outbox_enabled

    @property
    def transition_outbox_dead_letters_enabled(self) -> bool:
        """Whether the v45 schema can durably terminalize outbox records."""
        return self._transition_outbox_dead_letters_enabled

    @property
    def transition_outbox_backoff_enabled(self) -> bool:
        """Whether transient delivery failures have a durable retry deadline."""
        return self._transition_outbox_backoff_enabled

    @property
    def transition_outbox_max_delivery_attempts(self) -> int:
        """Return the bound before a valid delivery moves to dead letter."""
        return self._transition_outbox_max_delivery_attempts

    def _table_exists(self, table: str) -> bool:
        with db_write_lock(self.connection):
            return (
                self.connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()
                is not None
            )

    def _table_has_column(self, table: str, column: str) -> bool:
        escaped_table = table.replace("'", "''")
        with db_write_lock(self.connection):
            return any(
                str(row[1]) == column
                for row in self.connection.execute(
                    f"PRAGMA table_info('{escaped_table}')"
                ).fetchall()
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
                    previous_rows = self.connection.execute(
                        "SELECT "
                        + ", ".join(_COLUMNS)
                        + " FROM reconciliation_tasks WHERE library_root=? "
                        "ORDER BY created_at ASC, task_id ASC",
                        (self.library_root,),
                    ).fetchall()
                    previous_tasks = tuple(
                        self._row_to_task(
                            row,
                            now_monotonic=now_monotonic,
                            now_wallclock=now_wallclock,
                        )
                        for row in previous_rows
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
                    self._insert_transition_batch_unlocked(
                        queue_generation=next_generation,
                        previous_by_id={task.task_id: task for task in previous_tasks},
                        current_by_id={task.task_id: task for task in tasks},
                        reason="replace",
                        now_monotonic=now_monotonic,
                        now_wallclock=now_wallclock,
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
        kind: ReconciliationKind = ReconciliationKind.ASSET_INDEX_ROOT_RESCAN,
        payload: dict[str, object] | None = None,
        max_tasks: int,
        max_attempts: int,
        now: float,
    ) -> ReconciliationQueueMutationResult:
        """Upsert one task with SQL dedupe and bounded-capacity semantics."""
        if max_tasks < 1 or max_attempts < 1:
            raise ValueError("queue bounds must be positive")
        path_value = _canonical_path(path)
        kind_value = kind.value
        normalized_payload = normalize_reconciliation_payload(
            kind, payload, library_root=self.library_root
        )
        now_wallclock = self._wall_clock()
        try:
            with db_write_lock(self.connection):
                with self._transaction(immediate=True):
                    current_generation = self._read_generation_unlocked()
                    transition_before = self._tasks_snapshot_unlocked(
                        now_monotonic=now,
                        now_wallclock=now_wallclock,
                    )
                    evicted: list[ReconciliationTask] = []
                    existing_row = self.connection.execute(
                        "SELECT "
                        + ", ".join(_COLUMNS)
                        + " FROM reconciliation_tasks WHERE library_root=? "
                        "AND path=? AND kind=?",
                        (self.library_root, path_value, kind_value),
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
                            "observed_revision=COALESCE(?, observed_revision), payload=?, updated_at=? "
                            "WHERE task_id=? AND library_root=? AND path=? AND kind=? "
                            "AND state IN ('pending', 'running', 'retryable')",
                            (
                                reason or existing.reason,
                                json.dumps(operation_ids, ensure_ascii=False),
                                expected_revision,
                                observed_revision,
                                normalized_payload,
                                now,
                                existing.task_id,
                                self.library_root,
                                path_value,
                                kind_value,
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
                            # Preserve the full row before replacing it.  The
                            # queue listener uses this metadata to repair any
                            # manifest that was bound to the finished task.
                            evicted.append(existing)
                            deleted = self.connection.execute(
                                "DELETE FROM reconciliation_tasks WHERE task_id=? "
                                "AND library_root=? AND path=? AND kind=?",
                                (
                                    existing.task_id,
                                    self.library_root,
                                    path_value,
                                    kind_value,
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
                                "SELECT "
                                + ", ".join(_COLUMNS)
                                + " FROM reconciliation_tasks "
                                "WHERE library_root=? AND state IN "
                                "('succeeded', 'terminal', 'cancelled') "
                                "ORDER BY updated_at ASC, created_at ASC, task_id ASC LIMIT 1",
                                (self.library_root,),
                            ).fetchone()
                            if victim is None:
                                raise ReconciliationQueueFull(
                                    f"reconciliation queue is full ({max_tasks})"
                                )
                            victim_task = self._row_to_task(
                                victim,
                                now_monotonic=now,
                                now_wallclock=now_wallclock,
                            )
                            evicted.append(victim_task)
                            self.connection.execute(
                                "DELETE FROM reconciliation_tasks WHERE task_id=? "
                                "AND library_root=?",
                                (victim_task.task_id, self.library_root),
                            )
                        task_id = f"recon-{uuid4().hex}"
                        operation_ids = [operation_id] if operation_id else []
                        self.connection.execute(
                            "INSERT INTO reconciliation_tasks ("
                            + ", ".join(_COLUMNS)
                            + ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                task_id,
                                self.library_root,
                                path_value,
                                kind_value,
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
                                normalized_payload,
                            ),
                        )
                    return self._mutation_result_unlocked(
                        task_id,
                        current_generation=current_generation,
                        now_monotonic=now,
                        now_wallclock=now_wallclock,
                        evicted=tuple(evicted),
                        transition_before=transition_before,
                        transition_reason="enqueue",
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
                    transition_before = self._tasks_snapshot_unlocked(
                        now_monotonic=now,
                        now_wallclock=now_wallclock,
                    )
                    recovered_ids = self._recover_expired_running_unlocked(
                        now_monotonic=now,
                        now_wallclock=now_wallclock,
                    )
                    changed = bool(recovered_ids)
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
                    tasks = self._tasks_snapshot_unlocked(
                        now_monotonic=now,
                        now_wallclock=now_wallclock,
                    )
                    recovered_set = set(recovered_ids)
                    recovered = tuple(
                        task for task in tasks if task.task_id in recovered_set
                    )
                    if changed:
                        self._insert_transition_batch_unlocked(
                            queue_generation=generation,
                            previous_by_id={
                                task.task_id: task for task in transition_before
                            },
                            current_by_id={task.task_id: task for task in tasks},
                            reason="claim",
                            now_monotonic=now,
                            now_wallclock=now_wallclock,
                            recovered=recovered,
                        )
                    snapshot = ReconciliationQueueSnapshot(
                        tasks=tasks,
                        generation=generation,
                    )
            return ReconciliationQueueClaimResult(
                snapshot=snapshot,
                claimed=claimed,
                recovered=recovered,
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
                    transition_before = self._tasks_snapshot_unlocked(
                        now_monotonic=now,
                        now_wallclock=now_wallclock,
                    )
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
                        transition_before=transition_before,
                        transition_reason="succeeded",
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
                    transition_before = self._tasks_snapshot_unlocked(
                        now_monotonic=now,
                        now_wallclock=now_wallclock,
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
                        transition_before=transition_before,
                        transition_reason="retryable",
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

    @_retry_sqlite_busy
    def claim_transition_outbox(
        self,
        *,
        limit: int,
        lease_seconds: float,
    ) -> tuple[ReconciliationTransitionOutboxEntry, ...]:
        """Lease pending committed transitions for one at-least-once consumer."""
        if not self._transition_outbox_enabled:
            return ()
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit < 1
        ):
            raise ValueError("outbox claim limit must be a positive integer")
        if (
            not isinstance(lease_seconds, (int, float))
            or isinstance(lease_seconds, bool)
            or not isfinite(float(lease_seconds))
            or lease_seconds <= 0
        ):
            raise ValueError("outbox delivery lease must be finite and positive")
        now_monotonic = self._clock()
        now_wallclock = self._wall_clock()
        try:
            with db_write_lock(self.connection):
                with self._transaction(immediate=True):
                    entries: list[ReconciliationTransitionOutboxEntry] = []
                    last_seen_event_id = 0
                    # A corrupt run cannot monopolize the SQLite write lock.
                    # ``limit`` applies to usable entries, so allow a bounded
                    # amount of poison scanning beyond it in one claim.
                    scan_limit = max(limit, 64)
                    scanned = 0
                    while len(entries) < limit and scanned < scan_limit:
                        head_columns = (
                            "id, delivery_token, delivery_lease_expires_at, "
                            "next_delivery_at"
                            if self._transition_outbox_backoff_enabled
                            else "id, delivery_token, delivery_lease_expires_at"
                        )
                        head = self.connection.execute(
                            f"SELECT {head_columns} "
                            "FROM reconciliation_transition_outbox "
                            "WHERE library_root=? AND delivered_at IS NULL AND id>? "
                            "ORDER BY id ASC LIMIT 1",
                            (self.library_root, last_seen_event_id),
                        ).fetchone()
                        if head is None:
                            break
                        token = head[1]
                        lease_expires_at = head[2]
                        invalid_delivery_lease = False
                        delivery_lease_expires_at = 0.0
                        if token is not None and lease_expires_at is not None:
                            try:
                                delivery_lease_expires_at = float(
                                    str(lease_expires_at)
                                )
                                if (
                                    not isfinite(delivery_lease_expires_at)
                                    or delivery_lease_expires_at < 0
                                ):
                                    raise ValueError(
                                        "invalid reconciliation transition outbox delivery lease deadline"
                                    )
                            except (TypeError, ValueError, OverflowError):
                                # A malformed lease cannot be safely treated as
                                # either live or expired.  Claim it by its
                                # current token and use the v45 quarantine
                                # transaction below so it cannot block the head
                                # forever.
                                invalid_delivery_lease = True
                        invalid_retry_deadline = False
                        if self._transition_outbox_backoff_enabled:
                            try:
                                next_delivery_at = float(str(head[3]))
                                if (
                                    not isfinite(next_delivery_at)
                                    or next_delivery_at < 0
                                ):
                                    raise ValueError(
                                        "invalid reconciliation transition outbox retry deadline"
                                    )
                            except (TypeError, ValueError, OverflowError):
                                # Claim the corrupt head without a deadline
                                # predicate, then use the same atomic v45
                                # isolation path as malformed snapshots.
                                invalid_retry_deadline = True
                                next_delivery_at = 0.0
                            if (
                                not invalid_retry_deadline
                                and next_delivery_at > now_wallclock
                            ):
                                # Like an active lease, a not-before head is a
                                # strict per-library ordering barrier.
                                break
                        if (
                            token is not None
                            and lease_expires_at is not None
                            and not invalid_delivery_lease
                            and delivery_lease_expires_at > now_wallclock
                        ):
                            # Never skip a leased head record: later state
                            # transitions must not overtake it in another
                            # process.
                            break
                        event_id = int(str(head[0]))
                        last_seen_event_id = event_id
                        scanned += 1
                        delivery_token = uuid4().hex
                        claim_sql = (
                            "UPDATE reconciliation_transition_outbox SET "
                            "delivery_token=?, delivery_lease_expires_at=?, "
                            "delivery_attempts=delivery_attempts + 1 "
                            "WHERE id=? AND library_root=? AND delivered_at IS NULL "
                        )
                        claim_parameters: tuple[object, ...] = (
                            delivery_token,
                            now_wallclock + float(lease_seconds),
                            event_id,
                            self.library_root,
                        )
                        if invalid_delivery_lease:
                            # Keep the source token as the CAS predicate.  It
                            # is the only usable ownership fact on this
                            # malformed row, and it prevents replacing a row
                            # that a concurrent transaction has repaired.
                            claim_sql += "AND delivery_token=?"
                            claim_parameters += (token,)
                        else:
                            claim_sql += (
                                "AND (delivery_token IS NULL "
                                "OR delivery_lease_expires_at IS NULL "
                                "OR delivery_lease_expires_at <= ?)"
                            )
                            claim_parameters += (now_wallclock,)
                        if (
                            self._transition_outbox_backoff_enabled
                            and not invalid_retry_deadline
                        ):
                            claim_sql += " AND next_delivery_at <= ?"
                            claim_parameters += (now_wallclock,)
                        updated = self.connection.execute(
                            claim_sql,
                            claim_parameters,
                        ).rowcount
                        if updated != 1:
                            raise ReconciliationQueuePersistenceConflict(
                                "Reconciliation transition outbox claim lost ownership",
                                retryable=True,
                                operation="transition_outbox_claim",
                            )
                        claimed = self.connection.execute(
                            "SELECT id, task_id, reason, previous_task, current_task, "
                            "operation_ids, delivery_token, delivery_attempts "
                            "FROM reconciliation_transition_outbox "
                            "WHERE id=? AND library_root=?",
                            (event_id, self.library_root),
                        ).fetchone()
                        if claimed is None:
                            raise ReconciliationQueuePersistenceConflict(
                                "Claimed reconciliation transition outbox row disappeared",
                                retryable=True,
                                operation="transition_outbox_claim",
                        )
                        try:
                            if invalid_delivery_lease:
                                raise ValueError(
                                    "invalid reconciliation transition outbox delivery lease deadline"
                                )
                            if invalid_retry_deadline:
                                raise ValueError(
                                    "invalid reconciliation transition outbox retry deadline"
                                )
                            entry = self._outbox_row_to_entry(
                                claimed,
                                now_monotonic=now_monotonic,
                                now_wallclock=now_wallclock,
                            )
                        except (TypeError, ValueError, json.JSONDecodeError, OverflowError) as exc:
                            if not self._transition_outbox_dead_letters_enabled:
                                # v44 stores cannot safely discard their only
                                # durable copy.  Keep the old fail-closed
                                # behavior until the v45 isolation table is
                                # present.
                                raise
                            self._dead_letter_transition_outbox_unlocked(
                                event_id,
                                delivery_token=delivery_token,
                                error=exc,
                                dead_lettered_at=now_wallclock,
                            )
                            continue
                        entries.append(entry)
                    return tuple(entries)
        except ReconciliationQueuePersistenceError:
            raise
        except (sqlite3.Error, TypeError, ValueError, OverflowError) as exc:
            raise ReconciliationQueuePersistenceError(
                "Cannot claim reconciliation transition outbox entries in SQLite"
            ) from exc

    @_retry_sqlite_busy
    def renew_transition_outbox_lease(
        self,
        event_id: int,
        *,
        delivery_token: str,
        lease_seconds: float,
    ) -> bool:
        """Extend an active outbox delivery lease with token ownership CAS."""
        if not self._transition_outbox_enabled:
            return False
        if not isinstance(event_id, int) or isinstance(event_id, bool) or event_id < 1:
            raise ValueError("outbox event_id must be a positive integer")
        if not isinstance(delivery_token, str) or not delivery_token:
            raise ValueError("outbox delivery_token is required")
        if (
            not isinstance(lease_seconds, (int, float))
            or isinstance(lease_seconds, bool)
            or not isfinite(float(lease_seconds))
            or lease_seconds <= 0
        ):
            raise ValueError("outbox delivery lease must be finite and positive")
        now_wallclock = self._wall_clock()
        try:
            with db_write_lock(self.connection):
                with self._transaction(immediate=True):
                    claimed = self.connection.execute(
                        "SELECT delivery_lease_expires_at "
                        "FROM reconciliation_transition_outbox "
                        "WHERE id=? AND library_root=? AND delivered_at IS NULL "
                        "AND delivery_token=?",
                        (event_id, self.library_root, delivery_token),
                    ).fetchone()
                    if claimed is None:
                        return False
                    try:
                        expires_at = float(str(claimed[0]))
                    except (TypeError, ValueError, OverflowError):
                        return False
                    if not isfinite(expires_at) or expires_at <= now_wallclock:
                        return False
                    return bool(
                        self.connection.execute(
                            "UPDATE reconciliation_transition_outbox SET "
                            "delivery_lease_expires_at=? "
                            "WHERE id=? AND library_root=? AND delivered_at IS NULL "
                            "AND delivery_token=?",
                            (
                                now_wallclock + float(lease_seconds),
                                event_id,
                                self.library_root,
                                delivery_token,
                            ),
                        ).rowcount
                    )
        except (sqlite3.Error, TypeError, ValueError, OverflowError) as exc:
            raise ReconciliationQueuePersistenceError(
                "Cannot renew reconciliation transition outbox lease in SQLite"
            ) from exc

    @_retry_sqlite_busy
    def acknowledge_transition_outbox(
        self,
        event_id: int,
        *,
        delivery_token: str,
    ) -> bool:
        """Durably acknowledge one still-current transition delivery lease."""
        if not self._transition_outbox_enabled:
            return False
        if not isinstance(event_id, int) or isinstance(event_id, bool) or event_id < 1:
            raise ValueError("outbox event_id must be a positive integer")
        if not isinstance(delivery_token, str) or not delivery_token:
            raise ValueError("outbox delivery_token is required")
        now_wallclock = self._wall_clock()
        try:
            with db_write_lock(self.connection):
                with self._transaction(immediate=True):
                    acknowledge_sql = (
                        "UPDATE reconciliation_transition_outbox SET "
                        "delivered_at=?, delivery_token=NULL, "
                        "delivery_lease_expires_at=NULL, last_error_type=NULL, "
                        "last_error=NULL"
                    )
                    if self._transition_outbox_backoff_enabled:
                        acknowledge_sql += ", next_delivery_at=0"
                    acknowledge_sql += (
                        " WHERE id=? AND library_root=? "
                        "AND delivered_at IS NULL AND delivery_token=?"
                    )
                    return bool(
                        self.connection.execute(
                            acknowledge_sql,
                            (
                                now_wallclock,
                                event_id,
                                self.library_root,
                                delivery_token,
                            ),
                        ).rowcount
                    )
        except (sqlite3.Error, TypeError, ValueError, OverflowError) as exc:
            raise ReconciliationQueuePersistenceError(
                "Cannot acknowledge reconciliation transition outbox entry in SQLite"
            ) from exc

    @_retry_sqlite_busy
    def fail_transition_outbox(
        self,
        event_id: int,
        *,
        delivery_token: str,
        error: BaseException,
    ) -> bool:
        """Persist a retry deadline or terminal dead letter for one failure."""
        if not self._transition_outbox_enabled:
            return False
        if not isinstance(event_id, int) or isinstance(event_id, bool) or event_id < 1:
            raise ValueError("outbox event_id must be a positive integer")
        if not isinstance(delivery_token, str) or not delivery_token:
            raise ValueError("outbox delivery_token is required")
        error_type = type(error).__name__ or "Exception"
        try:
            error_message = str(error)
        except Exception:
            error_message = "unable to render transition listener failure"
        now_wallclock = self._wall_clock()
        try:
            with db_write_lock(self.connection):
                with self._transaction(immediate=True):
                    claimed = self.connection.execute(
                        "SELECT delivery_attempts FROM reconciliation_transition_outbox "
                        "WHERE id=? AND library_root=? AND delivered_at IS NULL "
                        "AND delivery_token=?",
                        (event_id, self.library_root, delivery_token),
                    ).fetchone()
                    if claimed is None:
                        return False
                    delivery_attempts = int(str(claimed[0]))
                    if (
                        self._transition_outbox_dead_letters_enabled
                        and delivery_attempts
                        >= self._transition_outbox_max_delivery_attempts
                    ):
                        exhausted = _TransitionOutboxDeliveryAttemptsExhausted(
                            "Reconciliation transition outbox delivery exhausted "
                            f"{self._transition_outbox_max_delivery_attempts} attempts "
                            f"after {error_type}: {error_message[:1000]}"
                        )
                        self._dead_letter_transition_outbox_unlocked(
                            event_id,
                            delivery_token=delivery_token,
                            error=exhausted,
                            dead_lettered_at=now_wallclock,
                        )
                        return True
                    if not self._transition_outbox_backoff_enabled:
                        return bool(
                            self.connection.execute(
                                "UPDATE reconciliation_transition_outbox SET "
                                "delivery_token=NULL, delivery_lease_expires_at=NULL, "
                                "last_error_type=?, last_error=? "
                                "WHERE id=? AND library_root=? AND delivered_at IS NULL "
                                "AND delivery_token=?",
                                (
                                    error_type,
                                    error_message[:4000],
                                    event_id,
                                    self.library_root,
                                    delivery_token,
                                ),
                            ).rowcount
                        )
                    next_delivery_at = now_wallclock + _outbox_delivery_backoff(
                        library_root=self.library_root,
                        event_id=event_id,
                        delivery_attempts=delivery_attempts,
                    )
                    return bool(
                        self.connection.execute(
                            "UPDATE reconciliation_transition_outbox SET "
                            "delivery_token=NULL, delivery_lease_expires_at=NULL, "
                            "last_error_type=?, last_error=?, next_delivery_at=? "
                            "WHERE id=? AND library_root=? AND delivered_at IS NULL "
                            "AND delivery_token=?",
                            (
                                error_type,
                                error_message[:4000],
                                next_delivery_at,
                                event_id,
                                self.library_root,
                                delivery_token,
                            ),
                        ).rowcount
                    )
        except (sqlite3.Error, TypeError, ValueError, OverflowError) as exc:
            raise ReconciliationQueuePersistenceError(
                "Cannot release reconciliation transition outbox entry in SQLite"
            ) from exc

    @_retry_sqlite_busy
    def list_transition_outbox_dead_letters(
        self,
        *,
        limit: int = 100,
        before_event_id: int | None = None,
    ) -> tuple[ReconciliationTransitionOutboxDeadLetter, ...]:
        """List immutable dead-letter rows newest first.

        Decoding is deliberately fail-closed: an operator must see a
        persistence error for a damaged dead-letter row rather than receiving
        a partial list that could hide an unreplayable event.
        """
        if not self._transition_outbox_dead_letters_enabled:
            return ()
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("dead-letter list limit must be a positive integer")
        if before_event_id is not None and (
            not isinstance(before_event_id, int)
            or isinstance(before_event_id, bool)
            or before_event_id < 1
        ):
            raise ValueError("dead-letter cursor must be a positive integer")
        try:
            with db_write_lock(self.connection):
                with self._read_transaction():
                    sql = (
                        "SELECT event_id, library_root, queue_generation, task_id, reason, "
                        "previous_task, current_task, operation_ids, created_at, "
                        "delivery_attempts, dead_lettered_at, error_type, error "
                        "FROM reconciliation_transition_outbox_dead_letters "
                        "WHERE library_root=?"
                    )
                    parameters: list[object] = [self.library_root]
                    if before_event_id is not None:
                        sql += " AND event_id < ?"
                        parameters.append(before_event_id)
                    sql += " ORDER BY event_id DESC LIMIT ?"
                    parameters.append(limit)
                    rows = self.connection.execute(sql, tuple(parameters)).fetchall()
            return tuple(self._dead_letter_row_to_record(row) for row in rows)
        except ReconciliationQueuePersistenceError:
            raise
        except (sqlite3.Error, TypeError, ValueError, json.JSONDecodeError, OverflowError) as exc:
            raise ReconciliationQueuePersistenceError(
                "Cannot list reconciliation transition outbox dead letters"
            ) from exc

    @_retry_sqlite_busy
    def replay_transition_outbox_dead_letter(
        self,
        event_id: int,
        *,
        expected_dead_lettered_at: float | None = None,
    ) -> bool:
        """Restore one dead letter to the live outbox with an event-id CAS.

        The source dead-letter row is immutable and remains in place as the
        audit record.  The original event id is reused so strict head ordering
        is preserved; an existing live row with the same id makes a repeated
        replay request an idempotent no-op.  A conflicting live row fails
        closed instead of being overwritten.
        """
        if not self._transition_outbox_dead_letters_enabled:
            return False
        if not isinstance(event_id, int) or isinstance(event_id, bool) or event_id < 1:
            raise ValueError("outbox event_id must be a positive integer")
        if expected_dead_lettered_at is not None and (
            not isinstance(expected_dead_lettered_at, (int, float))
            or isinstance(expected_dead_lettered_at, bool)
            or not isfinite(float(expected_dead_lettered_at))
            or float(expected_dead_lettered_at) < 0
        ):
            raise ValueError("expected dead-letter timestamp must be finite and non-negative")
        try:
            with db_write_lock(self.connection):
                with self._transaction(immediate=True):
                    row = self.connection.execute(
                        "SELECT event_id, library_root, queue_generation, task_id, reason, "
                        "previous_task, current_task, operation_ids, created_at, "
                        "delivery_attempts, dead_lettered_at, error_type, error "
                        "FROM reconciliation_transition_outbox_dead_letters "
                        "WHERE event_id=? AND library_root=?",
                        (event_id, self.library_root),
                    ).fetchone()
                    if row is None:
                        return False
                    record = self._dead_letter_row_to_record(row)
                    if (
                        expected_dead_lettered_at is not None
                        and float(record.dead_lettered_at)
                        != float(expected_dead_lettered_at)
                    ):
                        return False

                    existing = self.connection.execute(
                        "SELECT library_root, queue_generation, task_id, reason, "
                        "previous_task, current_task, operation_ids, created_at "
                        "FROM reconciliation_transition_outbox WHERE id=?",
                        (event_id,),
                    ).fetchone()
                    if existing is not None:
                        expected_live = (
                            self.library_root,
                            int(str(row[2])),
                            str(row[3]),
                            str(row[4]),
                            row[5],
                            row[6],
                            str(row[7]),
                            float(row[8]),
                        )
                        actual_live = tuple(existing)
                        if actual_live != expected_live:
                            raise ReconciliationQueuePersistenceConflict(
                                "Reconciliation transition outbox replay event id collision",
                                operation="transition_outbox_replay",
                            )
                        _log.info(
                            "Reconciliation transition dead-letter replay already exists "
                            "(library_root=%s, event_id=%s)",
                            self.library_root,
                            event_id,
                        )
                        return False

                    # Reusing an older event id is only safe while every
                    # later event in this library is still untouched.  A
                    # later ACK, lease, or attempted delivery may already
                    # have produced an external side effect; restoring the
                    # older event after that point would violate the
                    # per-library head ordering promised by the outbox.
                    later_live = self.connection.execute(
                        "SELECT id FROM reconciliation_transition_outbox "
                        "WHERE library_root=? AND id>? AND "
                        "(delivered_at IS NOT NULL OR delivery_token IS NOT NULL "
                        "OR delivery_attempts > 0) "
                        "ORDER BY id ASC LIMIT 1",
                        (self.library_root, event_id),
                    ).fetchone()
                    if later_live is not None:
                        raise ReconciliationQueuePersistenceConflict(
                            "ORDER_BLOCKED: reconciliation transition dead-letter "
                            f"event {event_id} has a later live event "
                            f"{int(str(later_live[0]))} with delivery progress",
                            operation="transition_outbox_replay_order",
                        )
                    if self._transition_outbox_dead_letters_enabled:
                        later_dead_letter = self.connection.execute(
                            "SELECT event_id FROM "
                            "reconciliation_transition_outbox_dead_letters "
                            "WHERE library_root=? AND event_id>? "
                            "ORDER BY event_id ASC LIMIT 1",
                            (self.library_root, event_id),
                        ).fetchone()
                        if later_dead_letter is not None:
                            raise ReconciliationQueuePersistenceConflict(
                                "ORDER_BLOCKED: reconciliation transition dead-letter "
                                f"event {event_id} has a later dead-letter event "
                                f"{int(str(later_dead_letter[0]))}",
                                operation="transition_outbox_replay_order",
                            )

                    columns = [
                        "id", "library_root", "queue_generation", "task_id", "reason",
                        "previous_task", "current_task", "operation_ids", "created_at",
                        "delivery_token", "delivery_lease_expires_at", "delivery_attempts",
                        "delivered_at", "last_error_type", "last_error",
                    ]
                    values: list[object] = [
                        event_id,
                        self.library_root,
                        int(str(row[2])),
                        str(row[3]),
                        str(row[4]),
                        row[5],
                        row[6],
                        str(row[7]),
                        float(row[8]),
                        None,
                        None,
                        # Keep the historical delivery count.  An explicit
                        # replay is a new delivery opportunity, not a reset
                        # of the retry/dead-letter policy; the next claim
                        # increments this value before invoking the consumer.
                        record.delivery_attempts,
                        None,
                        None,
                        None,
                    ]
                    if self._transition_outbox_backoff_enabled:
                        columns.append("next_delivery_at")
                        values.append(0.0)
                    placeholders = ", ".join("?" for _ in columns)
                    self.connection.execute(
                        "INSERT INTO reconciliation_transition_outbox ("
                        + ", ".join(columns)
                        + ") VALUES ("
                        + placeholders
                        + ")",
                        tuple(values),
                    )
                    _log.info(
                        "Replayed reconciliation transition dead letter "
                        "(library_root=%s, event_id=%s, previous_attempts=%s)",
                        self.library_root,
                        event_id,
                        record.delivery_attempts,
                    )
                    return True
        except ReconciliationQueuePersistenceError:
            raise
        except (sqlite3.Error, TypeError, ValueError, json.JSONDecodeError, OverflowError) as exc:
            raise ReconciliationQueuePersistenceError(
                "Cannot replay reconciliation transition outbox dead letter"
            ) from exc

    @_retry_sqlite_busy
    def transition_outbox_metrics(
        self,
        *,
        now: float | None = None,
    ) -> ReconciliationTransitionOutboxMetrics:
        """Collect bounded delivery metrics without decoding payloads."""
        if not self._transition_outbox_enabled:
            return ReconciliationTransitionOutboxMetrics()
        timestamp = self._wall_clock() if now is None else float(now)
        if not isfinite(timestamp) or timestamp < 0:
            raise ValueError("outbox metrics timestamp must be finite and non-negative")
        try:
            with db_write_lock(self.connection):
                with self._read_transaction():
                    live = self.connection.execute(
                        "SELECT "
                        "COALESCE(SUM(CASE WHEN delivered_at IS NULL THEN 1 ELSE 0 END), 0), "
                        "COALESCE(SUM(CASE WHEN delivered_at IS NOT NULL THEN 1 ELSE 0 END), 0), "
                        "MIN(CASE WHEN delivered_at IS NULL THEN created_at END), "
                        "COALESCE(SUM(CASE WHEN delivered_at IS NULL AND delivery_token IS NOT NULL THEN 1 ELSE 0 END), 0), "
                        "COALESCE(SUM(CASE WHEN delivered_at IS NULL AND delivery_token IS NOT NULL "
                        "AND (delivery_lease_expires_at IS NULL OR delivery_lease_expires_at <= ?) "
                        "THEN 1 ELSE 0 END), 0), "
                        "COALESCE(SUM(delivery_attempts), 0), "
                        "COALESCE(MAX(delivery_attempts), 0) "
                        "FROM reconciliation_transition_outbox WHERE library_root=?",
                        (timestamp, self.library_root),
                    ).fetchone()
                    dead = (0, None, 0, 0)
                    if self._transition_outbox_dead_letters_enabled:
                        dead = self.connection.execute(
                            "SELECT COUNT(*), MIN(dead_lettered_at), "
                            "COALESCE(SUM(delivery_attempts), 0), "
                            "COALESCE(MAX(delivery_attempts), 0) "
                            "FROM reconciliation_transition_outbox_dead_letters "
                            "WHERE library_root=?",
                            (self.library_root,),
                        ).fetchone()
            oldest_pending = self._age_seconds(timestamp, live[2])
            oldest_dead = self._age_seconds(timestamp, dead[1])
            return ReconciliationTransitionOutboxMetrics(
                pending_count=int(live[0]),
                acknowledged_count=int(live[1]),
                dead_letter_count=int(dead[0]),
                leased_count=int(live[3]),
                expired_lease_count=int(live[4]),
                delivery_attempts_total=int(live[5]) + int(dead[2]),
                max_delivery_attempts=max(int(live[6]), int(dead[3])),
                oldest_pending_age_seconds=oldest_pending,
                oldest_dead_letter_age_seconds=oldest_dead,
            )
        except ReconciliationQueuePersistenceError:
            raise
        except (sqlite3.Error, TypeError, ValueError, OverflowError) as exc:
            raise ReconciliationQueuePersistenceError(
                "Cannot collect reconciliation transition outbox metrics"
            ) from exc

    @_retry_sqlite_busy
    def prune_transition_outbox(
        self,
        *,
        acknowledged_before: float | None = None,
        dead_letter_before: float | None = None,
        limit: int = 1000,
    ) -> ReconciliationTransitionOutboxPruneResult:
        """Delete only explicitly expired ACK/dead-letter rows in one batch.

        Pending and leased rows are never eligible.  The caller supplies
        absolute wall-clock cutoffs so retention policy stays outside the
        persistence layer and can be audited/configured by the application.
        """
        if acknowledged_before is None and dead_letter_before is None:
            raise ValueError("at least one outbox retention cutoff is required")
        for name, cutoff in (
            ("acknowledged_before", acknowledged_before),
            ("dead_letter_before", dead_letter_before),
        ):
            if cutoff is not None and (
                not isinstance(cutoff, (int, float))
                or isinstance(cutoff, bool)
                or not isfinite(float(cutoff))
                or float(cutoff) < 0
            ):
                raise ValueError(f"{name} must be finite and non-negative")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("outbox prune limit must be a positive integer")
        if not self._transition_outbox_enabled:
            return ReconciliationTransitionOutboxPruneResult()
        try:
            with db_write_lock(self.connection):
                with self._transaction(immediate=True):
                    acknowledged_deleted = 0
                    if acknowledged_before is not None:
                        ids = self.connection.execute(
                            "SELECT id FROM reconciliation_transition_outbox "
                            "WHERE library_root=? AND delivered_at IS NOT NULL "
                            "AND delivered_at < ? ORDER BY delivered_at ASC, id ASC LIMIT ?",
                            (self.library_root, float(acknowledged_before), limit),
                        ).fetchall()
                        if ids:
                            placeholders = ", ".join("?" for _ in ids)
                            parameters: list[object] = [int(row[0]) for row in ids]
                            parameters.append(self.library_root)
                            acknowledged_deleted = self.connection.execute(
                                "DELETE FROM reconciliation_transition_outbox "
                                "WHERE id IN (" + placeholders + ") AND library_root=?",
                                tuple(parameters),
                            ).rowcount
                    dead_letters_deleted = 0
                    if (
                        dead_letter_before is not None
                        and self._transition_outbox_dead_letters_enabled
                    ):
                        ids = self.connection.execute(
                            "SELECT event_id FROM reconciliation_transition_outbox_dead_letters "
                            "WHERE library_root=? AND dead_lettered_at < ? "
                            "ORDER BY dead_lettered_at ASC, event_id ASC LIMIT ?",
                            (self.library_root, float(dead_letter_before), limit),
                        ).fetchall()
                        if ids:
                            placeholders = ", ".join("?" for _ in ids)
                            parameters = [int(row[0]) for row in ids]
                            parameters.append(self.library_root)
                            dead_letters_deleted = self.connection.execute(
                                "DELETE FROM reconciliation_transition_outbox_dead_letters "
                                "WHERE event_id IN (" + placeholders + ") AND library_root=?",
                                tuple(parameters),
                            ).rowcount
                    result = ReconciliationTransitionOutboxPruneResult(
                        acknowledged_deleted=max(0, int(acknowledged_deleted)),
                        dead_letters_deleted=max(0, int(dead_letters_deleted)),
                    )
                    if result.acknowledged_deleted or result.dead_letters_deleted:
                        _log.info(
                            "Pruned reconciliation transition outbox rows "
                            "(library_root=%s, acknowledged=%s, dead_letters=%s)",
                            self.library_root,
                            result.acknowledged_deleted,
                            result.dead_letters_deleted,
                        )
                    return result
        except ReconciliationQueuePersistenceError:
            raise
        except (sqlite3.Error, TypeError, ValueError, OverflowError) as exc:
            raise ReconciliationQueuePersistenceError(
                "Cannot prune reconciliation transition outbox rows"
            ) from exc

    @staticmethod
    def _age_seconds(now: float, timestamp: object) -> float | None:
        """Convert one stored timestamp into a non-negative observation."""
        if timestamp is None:
            return None
        try:
            value = float(str(timestamp))
        except (TypeError, ValueError, OverflowError):
            return None
        if not isfinite(value):
            return None
        return max(0.0, now - value)

    def _dead_letter_transition_outbox_unlocked(
        self,
        event_id: int,
        *,
        delivery_token: str,
        error: BaseException,
        dead_lettered_at: float,
    ) -> None:
        """Atomically preserve and remove one terminal leased outbox row.

        This helper runs inside the caller's ``BEGIN IMMEDIATE`` transaction.
        The delivery-token predicate prevents an expired owner from removing a
        row which another process has already reclaimed.
        """
        try:
            error_message = str(error)
        except Exception:
            error_message = "unable to render corrupt transition outbox record"
        source = self.connection.execute(
            "SELECT id, library_root, queue_generation, task_id, reason, "
            "previous_task, current_task, operation_ids, created_at, "
            "delivery_attempts "
            "FROM reconciliation_transition_outbox "
            "WHERE id=? AND library_root=? AND delivered_at IS NULL "
            "AND delivery_token=?",
            (event_id, self.library_root, delivery_token),
        ).fetchone()
        if source is None:
            raise ReconciliationQueuePersistenceConflict(
                "Reconciliation transition outbox dead-letter lost ownership",
                retryable=True,
                operation="transition_outbox_dead_letter",
            )

        # A replay of an already dead-lettered event can exhaust again.  The
        # dead-letter table intentionally keeps one audit anchor per event id,
        # so make that copy operation idempotent instead of allowing the
        # primary-key violation to roll back the source delete and strand the
        # live row.  Transition payload fields remain immutable; only the
        # monotonic attempts summary may advance after a replay.
        existing = self.connection.execute(
            "SELECT event_id, library_root, queue_generation, task_id, reason, "
            "previous_task, current_task, operation_ids, created_at, "
            "delivery_attempts "
            "FROM reconciliation_transition_outbox_dead_letters "
            "WHERE event_id=?",
            (event_id,),
        ).fetchone()
        if existing is None:
            copied = self.connection.execute(
                "INSERT INTO reconciliation_transition_outbox_dead_letters ("
                "event_id, library_root, queue_generation, task_id, reason, "
                "previous_task, current_task, operation_ids, created_at, "
                "delivery_attempts, dead_lettered_at, error_type, error"
                ") SELECT id, library_root, queue_generation, task_id, reason, "
                "previous_task, current_task, operation_ids, created_at, "
                "delivery_attempts, ?, ?, ? "
                "FROM reconciliation_transition_outbox "
                "WHERE id=? AND library_root=? AND delivered_at IS NULL "
                "AND delivery_token=?",
                (
                    dead_lettered_at,
                    type(error).__name__ or "ValueError",
                    error_message[:4000],
                    event_id,
                    self.library_root,
                    delivery_token,
                ),
            ).rowcount
            if copied != 1:
                raise ReconciliationQueuePersistenceConflict(
                    "Reconciliation transition outbox dead-letter lost ownership",
                    retryable=True,
                    operation="transition_outbox_dead_letter",
                )
        else:
            source_payload = tuple(source[:9])
            existing_payload = tuple(existing[:9])
            if existing_payload != source_payload:
                raise ReconciliationQueuePersistenceConflict(
                    "Reconciliation transition outbox dead-letter event id collision",
                    operation="transition_outbox_dead_letter",
                )
            existing_attempts = int(str(existing[9]))
            source_attempts = int(str(source[9]))
            if source_attempts > existing_attempts:
                self.connection.execute(
                    "UPDATE reconciliation_transition_outbox_dead_letters SET "
                    "delivery_attempts=? WHERE event_id=?",
                    (source_attempts, event_id),
                )
        deleted = self.connection.execute(
            "DELETE FROM reconciliation_transition_outbox "
            "WHERE id=? AND library_root=? AND delivered_at IS NULL "
            "AND delivery_token=?",
            (event_id, self.library_root, delivery_token),
        ).rowcount
        if deleted != 1:
            raise ReconciliationQueuePersistenceConflict(
                "Reconciliation transition outbox dead-letter lost source row",
                retryable=True,
                operation="transition_outbox_dead_letter",
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
                        # Token-less administrative terminal/cancel of a
                        # running task is a forced stop: the admin is
                        # authoritative over a live worker lease, so no
                        # attempt/lease CAS applies.  The update below clears
                        # the lease, after which the running worker's own
                        # completion CAS fails — the intended outcome of an
                        # admin termination.
                        predicate = "state='running'"
                        predicate_params = ()
                    else:
                        predicate = "state IN ('pending', 'retryable')"
                        predicate_params = ()
                    transition_before = self._tasks_snapshot_unlocked(
                        now_monotonic=now,
                        now_wallclock=now_wallclock,
                    )
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
                        transition_before=transition_before,
                        transition_reason=target_state,
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
        evicted: tuple[ReconciliationTask, ...] = (),
        transition_before: tuple[ReconciliationTask, ...] = (),
        transition_reason: str | None = None,
        recovered: tuple[ReconciliationTask, ...] = (),
    ) -> ReconciliationQueueMutationResult:
        generation = (
            self._advance_generation_unlocked(
                current_generation,
                updated_at=now_wallclock,
            )
            if changed
            else current_generation
        )
        tasks = self._tasks_snapshot_unlocked(
            now_monotonic=now_monotonic,
            now_wallclock=now_wallclock,
        )
        if changed and transition_reason is not None:
            self._insert_transition_batch_unlocked(
                queue_generation=generation,
                previous_by_id={task.task_id: task for task in transition_before},
                current_by_id={task.task_id: task for task in tasks},
                reason=transition_reason,
                now_monotonic=now_monotonic,
                now_wallclock=now_wallclock,
                evicted=evicted,
                recovered=recovered,
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
            evicted=tuple(evicted),
        )

    def _tasks_snapshot_unlocked(
        self,
        *,
        now_monotonic: float,
        now_wallclock: float,
    ) -> tuple[ReconciliationTask, ...]:
        rows = self.connection.execute(
            "SELECT "
            + ", ".join(_COLUMNS)
            + " FROM reconciliation_tasks WHERE library_root=? "
            "ORDER BY created_at ASC, task_id ASC",
            (self.library_root,),
        ).fetchall()
        return tuple(
            self._row_to_task(
                row,
                now_monotonic=now_monotonic,
                now_wallclock=now_wallclock,
            )
            for row in rows
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
                    transition_before = self._tasks_snapshot_unlocked(
                        now_monotonic=now,
                        now_wallclock=now_wallclock,
                    )
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
                    if recovered:
                        self._insert_transition_batch_unlocked(
                            queue_generation=generation,
                            previous_by_id={
                                task.task_id: task for task in transition_before
                            },
                            current_by_id={task.task_id: task for task in tasks},
                            reason="lease_expired",
                            now_monotonic=now,
                            now_wallclock=now_wallclock,
                            recovered=recovered,
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

    def _outbox_row_to_entry(
        self,
        row: sqlite3.Row | tuple[object, ...],
        *,
        now_monotonic: float,
        now_wallclock: float,
    ) -> ReconciliationTransitionOutboxEntry:
        """Decode a claimed immutable outbox row, failing closed on corruption."""
        if len(row) != 8:
            raise ValueError("invalid reconciliation transition outbox row shape")
        event_id = int(str(row[0]))
        task_id = str(row[1])
        reason = str(row[2])
        if event_id < 1 or not task_id or not reason:
            raise ValueError("invalid reconciliation transition outbox identity")

        def decode_task(value: object) -> ReconciliationTask | None:
            if value is None:
                return None
            payload = json.loads(str(value))
            task = _task_from_json(
                payload,
                version=2,
                now_monotonic=now_monotonic,
                now_wallclock=now_wallclock,
            )
            if task.library_root != self.library_root:
                raise ValueError("transition outbox task belongs to another library")
            return task

        previous = decode_task(row[3])
        current = decode_task(row[4])
        if previous is not None and previous.task_id != task_id:
            raise ValueError("transition outbox previous snapshot does not match task id")
        if current is not None and current.task_id != task_id:
            raise ValueError("transition outbox current snapshot does not match task id")
        task = current or previous
        if task is None or task.task_id != task_id:
            raise ValueError("transition outbox task snapshot does not match task id")
        operation_ids_raw = json.loads(str(row[5]))
        if not isinstance(operation_ids_raw, list | tuple) or not all(
            isinstance(operation_id, str) and operation_id
            for operation_id in operation_ids_raw
        ):
            raise ValueError("transition outbox operation_ids must be non-empty strings")
        expected_operation_ids = tuple(
            dict.fromkeys(
                tuple(previous.operation_ids if previous is not None else ())
                + tuple(current.operation_ids if current is not None else ())
            )
        )
        if tuple(operation_ids_raw) != expected_operation_ids:
            raise ValueError(
                "transition outbox operation_ids do not match task snapshot scope"
            )
        delivery_token = str(row[6]) if row[6] is not None else ""
        delivery_attempts = int(str(row[7]))
        if not delivery_token or delivery_attempts < 1:
            raise ValueError("invalid reconciliation transition outbox lease")
        return ReconciliationTransitionOutboxEntry(
            event_id=event_id,
            transition=ReconciliationTaskTransition(
                previous=previous,
                current=current,
                reason=reason,
                operation_ids=tuple(operation_ids_raw),
            ),
            delivery_token=delivery_token,
            delivery_attempts=delivery_attempts,
        )

    def _dead_letter_row_to_record(
        self,
        row: sqlite3.Row | tuple[object, ...],
    ) -> ReconciliationTransitionOutboxDeadLetter:
        """Validate and decode one immutable dead-letter row."""
        if len(row) != 13:
            raise ValueError("invalid reconciliation transition dead-letter row shape")
        event_id = int(str(row[0]))
        library_root = _canonical_path(str(row[1]))
        if event_id < 1 or library_root != self.library_root:
            raise ValueError("invalid reconciliation transition dead-letter identity")
        queue_generation = int(str(row[2]))
        if queue_generation < 0:
            raise ValueError("invalid reconciliation transition dead-letter generation")
        task_id = str(row[3])
        reason = str(row[4])
        if not task_id or not reason:
            raise ValueError("invalid reconciliation transition dead-letter task")
        created_at = float(str(row[8]))
        dead_lettered_at = float(str(row[10]))
        if (
            not isfinite(created_at)
            or created_at < 0
            or not isfinite(dead_lettered_at)
            or dead_lettered_at < 0
        ):
            raise ValueError("invalid reconciliation transition dead-letter timestamp")
        delivery_attempts = int(str(row[9]))
        if delivery_attempts < 1:
            raise ValueError("invalid reconciliation transition dead-letter attempts")
        error_type = str(row[11])
        error = str(row[12])
        if not error_type or not error:
            raise ValueError("invalid reconciliation transition dead-letter diagnostic")

        # Reuse the live-row decoder so snapshot identity, operation scope and
        # payload version checks stay identical for list and replay paths.
        entry = self._outbox_row_to_entry(
            (
                event_id,
                task_id,
                reason,
                row[5],
                row[6],
                row[7],
                "dead-letter-validation",
                delivery_attempts,
            ),
            now_monotonic=0.0,
            now_wallclock=dead_lettered_at,
        )
        return ReconciliationTransitionOutboxDeadLetter(
            event_id=event_id,
            transition=entry.transition,
            created_at=created_at,
            delivery_attempts=delivery_attempts,
            dead_lettered_at=dead_lettered_at,
            error_type=error_type,
            error=error,
        )

    def _insert_transition_outbox_unlocked(
        self,
        *,
        queue_generation: int,
        previous: ReconciliationTask | None,
        current: ReconciliationTask | None,
        reason: str,
        now_monotonic: float,
        now_wallclock: float,
    ) -> None:
        """Append one immutable event inside the caller's queue transaction."""
        if not self._transition_outbox_enabled:
            return
        task = current or previous
        if task is None:
            return
        operation_ids = tuple(
            dict.fromkeys(
                tuple(previous.operation_ids if previous is not None else ())
                + tuple(current.operation_ids if current is not None else ())
            )
        )

        def encode(value: ReconciliationTask | None) -> str | None:
            if value is None:
                return None
            return json.dumps(
                _task_to_json(value, now_monotonic, now_wallclock),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )

        self.connection.execute(
            "INSERT INTO reconciliation_transition_outbox ("
            "library_root, queue_generation, task_id, reason, previous_task, "
            "current_task, operation_ids, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                self.library_root,
                queue_generation,
                task.task_id,
                reason,
                encode(previous),
                encode(current),
                json.dumps(list(operation_ids), ensure_ascii=False),
                now_wallclock,
            ),
        )

    def _insert_transition_batch_unlocked(
        self,
        *,
        queue_generation: int,
        previous_by_id: dict[str, ReconciliationTask],
        current_by_id: dict[str, ReconciliationTask],
        reason: str,
        now_monotonic: float,
        now_wallclock: float,
        evicted: tuple[ReconciliationTask, ...] = (),
        recovered: tuple[ReconciliationTask, ...] = (),
    ) -> None:
        """Record exact previous/current snapshots for one committed mutation."""
        if not self._transition_outbox_enabled:
            return
        seen: set[tuple[str, str]] = set()
        explicit_ids = {task.task_id for task in (*evicted, *recovered)}

        def append(
            previous: ReconciliationTask | None,
            current: ReconciliationTask | None,
            event_reason: str,
        ) -> None:
            task = current or previous
            if task is None:
                return
            key = (task.task_id, event_reason)
            if key in seen:
                return
            seen.add(key)
            self._insert_transition_outbox_unlocked(
                queue_generation=queue_generation,
                previous=previous,
                current=current,
                reason=event_reason,
                now_monotonic=now_monotonic,
                now_wallclock=now_wallclock,
            )

        for task in evicted:
            append(previous_by_id.get(task.task_id) or task, None, "evicted")
        for task in recovered:
            append(
                previous_by_id.get(task.task_id),
                current_by_id.get(task.task_id) or task,
                "lease_expired",
            )
        for task_id in sorted(set(previous_by_id) | set(current_by_id)):
            previous = previous_by_id.get(task_id)
            current = current_by_id.get(task_id)
            if previous != current and task_id not in explicit_ids:
                append(previous, current, reason)

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
            task.payload,
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
        payload = str(row[18]) if row[18] is not None else "{}"
        try:
            parsed_payload = json.loads(payload)
            normalized_payload = normalize_reconciliation_payload(
                ReconciliationKind(str(row[3])),
                parsed_payload,
                library_root=str(row[1]),
            )
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError("invalid reconciliation task payload") from exc
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
            payload=normalized_payload,
        )
