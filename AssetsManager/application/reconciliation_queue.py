"""Bounded, session-scoped reconciliation task queue.

The queue is deliberately independent from ``FileOperationService``'s UI
warning channel.  Warnings can be destructively drained by a caller, while
reconciliation tasks remain pending until a worker claims and resolves them.
The first implementation is limited to idempotent asset-index rescans; the
executor and cross-projection generation work remain follow-up phases.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import Enum
from functools import wraps
from math import isfinite
import json
import logging
import os
from pathlib import Path
import tempfile
import threading
import time
from typing import Callable, Mapping, Protocol, cast
from uuid import uuid4

_log = logging.getLogger(__name__)

IMPORT_MANIFEST_RECOVERY_CONSUMER_ID = "import_manifest_recovery"
_TRANSITION_OUTBOX_CALLBACK_MAX_AGE_SECONDS = 300.0


def _same_listener(
    left: Callable[["ReconciliationTaskTransition"], object],
    right: Callable[["ReconciliationTaskTransition"], object],
) -> bool:
    """Compare callbacks without duplicating freshly-created bound methods."""
    if left is right:
        return True
    try:
        return bool(left == right)
    except Exception:
        return False


class ReconciliationKind(str, Enum):
    """Repair action represented by a reconciliation task."""

    ASSET_INDEX_ROOT_RESCAN = "asset_index_root_rescan"
    FILESYSTEM_PROJECTION_REPAIR = "filesystem_projection_repair"


_FILESYSTEM_REPAIR_PROJECTION_SET = (
    "asset_index",
    "tags",
    "metadata",
    "favorites",
    "thumbnail_rows",
    "thumbnail_bytes",
)
_RESTORE_REPAIR_PROJECTION_SET = ("asset_index", "tags", "metadata", "favorites")
_RESTORE_SNAPSHOT_MAX_BYTES = 256 * 1024
_RESTORE_SNAPSHOT_MAX_ROWS = 10_000


def _validate_restore_snapshot(snapshot: object, *, root: Path) -> dict[str, object]:
    if not isinstance(snapshot, Mapping):
        raise ValueError("restore snapshot must be an object")
    data = dict(snapshot)
    if data.get("format") != "assetsmanager.undo-projection" or data.get("version") != 1:
        raise ValueError("restore snapshot format/version is invalid")
    base = data.get("base")
    if not isinstance(base, str) or not base:
        raise ValueError("restore snapshot base is required")
    base_path = Path(base).resolve()
    if not base_path.is_relative_to(root):
        raise ValueError("restore snapshot base escapes library root")
    for field, width in (("file_tags", 2), ("file_meta", 6), ("library_favorites", 3)):
        rows = data.get(field, [])
        if not isinstance(rows, list) or len(rows) > _RESTORE_SNAPSHOT_MAX_ROWS:
            raise ValueError(f"restore snapshot {field} is invalid")
        for row in rows:
            if not isinstance(row, list | tuple) or len(row) != width:
                raise ValueError(f"restore snapshot {field} row is invalid")
            if not all(value is None or isinstance(value, (str, int, float, bool)) for value in row):
                raise ValueError(f"restore snapshot {field} scalar is invalid")
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > _RESTORE_SNAPSHOT_MAX_BYTES:
        raise ValueError("restore snapshot is too large")
    return data


def normalize_reconciliation_payload(
    kind: ReconciliationKind,
    payload: Mapping[str, object] | None,
    *,
    library_root: str | Path,
) -> str:
    """Validate and canonicalize a durable task payload."""
    if kind is ReconciliationKind.ASSET_INDEX_ROOT_RESCAN:
        return "{}"
    if kind is not ReconciliationKind.FILESYSTEM_PROJECTION_REPAIR:
        raise ValueError(f"unsupported reconciliation kind: {kind.value}")
    if not isinstance(payload, Mapping):
        raise ValueError("filesystem repair payload must be an object")
    data = dict(payload)
    if data.get("payload_version") != 1:
        raise ValueError("unsupported filesystem repair payload version")
    operation_kind = data.get("operation_kind")
    if operation_kind not in {"move", "delete", "restore"}:
        raise ValueError("filesystem repair operation_kind must be move, delete, or restore")
    operation_id = data.get("operation_id")
    if not isinstance(operation_id, str) or not operation_id:
        raise ValueError("filesystem repair operation_id is required")
    projection_set = data.get("projection_set")
    expected_projection_set = (
        list(_RESTORE_REPAIR_PROJECTION_SET)
        if operation_kind == "restore"
        else list(_FILESYSTEM_REPAIR_PROJECTION_SET)
    )
    if projection_set != expected_projection_set:
        raise ValueError("filesystem repair projection_set is invalid")
    root = Path(library_root).resolve()

    def canonical_path(value: object, field: str) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError(f"filesystem repair {field} is required")
        path = Path(value).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"filesystem repair {field} escapes library root")
        return str(path)

    data["scope_path"] = canonical_path(data.get("scope_path"), "scope_path")
    if operation_kind == "move":
        data["source_path"] = canonical_path(data.get("source_path"), "source_path")
        data["destination_path"] = canonical_path(
            data.get("destination_path"), "destination_path"
        )
        if not isinstance(data.get("is_directory"), bool):
            raise ValueError("filesystem repair is_directory must be boolean")
        if data.get("expected_state") != {
            "source_absent": True,
            "destination_present": True,
        }:
            raise ValueError("filesystem repair move expected_state is invalid")
    elif operation_kind == "delete":
        data["target_path"] = canonical_path(data.get("target_path"), "target_path")
        if data.get("delete_mode") not in {"permanent", "trash"}:
            raise ValueError("filesystem repair delete_mode is invalid")
        if data.get("expected_state") != {"target_absent": True}:
            raise ValueError("filesystem repair delete expected_state is invalid")
    else:
        data["target_path"] = canonical_path(data.get("target_path"), "target_path")
        if not isinstance(data.get("is_directory"), bool):
            raise ValueError("filesystem repair restore is_directory must be boolean")
        if data.get("expected_state") != {"target_present": True}:
            raise ValueError("filesystem repair restore expected_state is invalid")
        data["snapshot"] = _validate_restore_snapshot(data.get("snapshot"), root=root)
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ReconciliationState(str, Enum):
    """Lifecycle state of a reconciliation task."""

    PENDING = "pending"
    RUNNING = "running"
    RETRYABLE = "retryable"
    SUCCEEDED = "succeeded"
    TERMINAL = "terminal"
    CANCELLED = "cancelled"


class ReconciliationTransitionDisposition(str, Enum):
    """A durable transition consumer's acknowledgement decision.

    ``APPLIED`` means the dependent durable state was written.  ``STALE``
    means the consumer proved that the event is irrelevant or already covered
    by a newer durable state.  Only those two dispositions permit the shared
    outbox record to be acknowledged.  ``RETRY`` retains it for at-least-once
    redelivery.
    """

    APPLIED = "applied"
    STALE = "stale"
    RETRY = "retry"


class _ReconciliationTransitionRetryRequested(RuntimeError):
    """Internal signal used to return a leased outbox event to pending."""


class ReconciliationQueueFull(RuntimeError):
    """Raised when a bounded queue has no completed task available to evict."""


class ReconciliationQueuePersistenceError(RuntimeError):
    """Raised when a durable queue marker cannot be read or written."""


class ReconciliationQueuePersistenceConflict(ReconciliationQueuePersistenceError):
    """Raised when another process published a newer queue generation.

    The conflict classification attributes are intentionally public so callers can make
    retry decisions without parsing the exception message.  Unknown conflicts
    remain non-retryable by default for backward compatibility.
    """

    def __init__(
        self,
        message: str = "reconciliation queue persistence conflict",
        *,
        retryable: bool = False,
        retry_after_refresh: bool | None = None,
        stale_worker_completion: bool = False,
        operation: str = "unknown",
    ) -> None:
        super().__init__(message)
        resolved_retryable = (
            bool(retryable)
            if retry_after_refresh is None
            else bool(retry_after_refresh)
        )
        self.retryable = resolved_retryable
        # Keep the descriptive alias for callers that classify a conflict as
        # safe only after a durable snapshot refresh.
        self.retry_after_refresh = resolved_retryable
        self.stale_worker_completion = bool(stale_worker_completion)
        self.operation = str(operation)


_ACTIVE_STATES = {
    ReconciliationState.PENDING,
    ReconciliationState.RUNNING,
    ReconciliationState.RETRYABLE,
}
_FINISHED_STATES = {
    ReconciliationState.SUCCEEDED,
    ReconciliationState.TERMINAL,
    ReconciliationState.CANCELLED,
}

# Durable JSON marker format version.  Module-level so the migration module
# can accept the same marker versions without constructing a queue.
_FORMAT_VERSION = 2


@dataclass(frozen=True, slots=True)
class ReconciliationTask:
    """One deduplicated repair request.

    ``attempts`` counts claims, not the retry count reported by the originating
    asset-index operation.  The two values are intentionally kept separate:
    the former belongs to this queue, while the latter describes one publish
    attempt that has already completed.
    """

    task_id: str
    library_root: str
    path: str
    kind: ReconciliationKind
    reason: str
    state: ReconciliationState = ReconciliationState.PENDING
    attempts: int = 0
    next_attempt_at: float = 0.0
    operation_ids: tuple[str, ...] = ()
    last_error_type: str | None = None
    last_error: str | None = None
    expected_revision: int | None = None
    observed_revision: int | None = None
    created_at: float = 0.0
    updated_at: float = 0.0
    lease_expires_at: float | None = None
    lease_token: str | None = None
    max_attempts: int = 5
    payload: str = "{}"

    @property
    def repair_key(self) -> tuple[str, str, ReconciliationKind]:
        """Return the stable key used for deduplication."""
        return (
            _canonical_path(self.library_root),
            _canonical_path(self.path),
            self.kind,
        )

    def is_due(self, now: float) -> bool:
        """Return whether the task is eligible at the supplied clock value."""
        return (
            self.state in {ReconciliationState.PENDING, ReconciliationState.RETRYABLE}
            and self.next_attempt_at <= now
        )


@dataclass(frozen=True, slots=True)
class ReconciliationQueueSnapshot:
    """Durable tasks plus the generation read with the same snapshot."""

    tasks: tuple[ReconciliationTask, ...]
    generation: int


@dataclass(frozen=True, slots=True)
class ReconciliationQueueClaimResult:
    """Result of a store-level atomic claim and the refreshed snapshot."""

    snapshot: ReconciliationQueueSnapshot
    claimed: ReconciliationTask | None
    # Expired running rows may be moved to retryable/terminal as part of the
    # same claim transaction.  Returning them lets the queue listener observe
    # those transitions instead of waiting for a best-effort sweeper pass.
    recovered: tuple[ReconciliationTask, ...] = ()


@dataclass(frozen=True, slots=True)
class ReconciliationQueueRecoveryResult:
    """Result of an atomic expired-lease recovery mutation."""

    snapshot: ReconciliationQueueSnapshot
    recovered: tuple[ReconciliationTask, ...]


@dataclass(frozen=True, slots=True)
class ReconciliationQueueMutationResult:
    """Result of one atomic per-task store mutation."""

    snapshot: ReconciliationQueueSnapshot
    task: ReconciliationTask
    # Tasks removed while inserting/replacing a row are returned explicitly so
    # observers can reconcile durable side effects (for example an import
    # manifest bound to an evicted task).  The field is optional for backwards
    # compatible persistence adapters that predate eviction reporting.
    evicted: tuple[ReconciliationTask, ...] = ()


@dataclass(frozen=True, slots=True)
class ReconciliationTaskTransition:
    """One committed queue transition delivered to an optional listener.

    ``current`` is ``None`` for an eviction/removal.  ``operation_ids`` is
    copied into the event rather than inferred by consumers so a task that has
    already disappeared still carries the audit references needed to repair
    dependent records.  Listeners are invoked only after the queue mutation
    commits and after its lock is released.
    """

    previous: ReconciliationTask | None
    current: ReconciliationTask | None
    reason: str
    operation_ids: tuple[str, ...] = ()

    @property
    def task_id(self) -> str:
        task = self.current or self.previous
        return "" if task is None else task.task_id


@dataclass(frozen=True, slots=True)
class ReconciliationTransitionOutboxEntry:
    """One leased durable transition awaiting listener acknowledgement."""

    event_id: int
    transition: ReconciliationTaskTransition
    delivery_token: str
    delivery_attempts: int


@dataclass(frozen=True, slots=True)
class ReconciliationTransitionOutboxDeadLetter:
    """One immutable transition delivery retained after dead-lettering.

    The original event id and transition snapshots remain stable across an
    explicit replay.  Keeping this record separate from the live outbox row
    gives operators an audit anchor even after a replay is acknowledged.
    """

    event_id: int
    transition: ReconciliationTaskTransition
    created_at: float
    delivery_attempts: int
    dead_lettered_at: float
    error_type: str
    error: str


@dataclass(frozen=True, slots=True)
class ReconciliationTransitionOutboxMetrics:
    """Bounded point-in-time delivery metrics for one library outbox."""

    pending_count: int = 0
    acknowledged_count: int = 0
    dead_letter_count: int = 0
    leased_count: int = 0
    expired_lease_count: int = 0
    delivery_attempts_total: int = 0
    max_delivery_attempts: int = 0
    oldest_pending_age_seconds: float | None = None
    oldest_dead_letter_age_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class ReconciliationTransitionOutboxPruneResult:
    """Rows removed by one explicit outbox retention pass."""

    acknowledged_deleted: int = 0
    dead_letters_deleted: int = 0


@dataclass(frozen=True, slots=True)
class _TransitionBacklogEntry:
    """One failed transition delivery and the listeners that still need it."""

    transition: ReconciliationTaskTransition
    # ``None`` means that no listener was available and any future listener may
    # consume the event.  A tuple records only callbacks that failed; callbacks
    # which already accepted the event are not replayed.
    listeners: tuple[Callable[[ReconciliationTaskTransition], object], ...] | None = None


def _notify_task_transitions(reason: str):
    """Decorate queue mutations with post-commit transition notifications."""

    def decorator(method):
        @wraps(method)
        def wrapped(self, *args, **kwargs):
            # Serialize the before/mutation/after window per queue instance.
            # The queue methods use their own state lock, but taking snapshots
            # outside a mutation-wide lock would let a concurrent local
            # mutation be attributed to the wrong reason.
            durable_outbox = self._uses_durable_transition_outbox()
            events: tuple[ReconciliationTaskTransition, ...] = ()
            with self._transition_mutation_lock:
                self._clear_transition_metadata()
                if durable_outbox:
                    # The SQLite store appends exact before/current snapshots
                    # inside its task transaction. Deliver only from that log
                    # so a process crash cannot lose the queue-to-manifest
                    # hand-off.
                    result = method(self, *args, **kwargs)
                    self._take_transition_metadata()
                else:
                    before = self._snapshot_for_transition()
                    result = method(self, *args, **kwargs)
                    after = self._snapshot_for_transition()
                    # Store-backed mutations can evict a finished row that was not
                    # in this process's last snapshot. Include the explicit result
                    # metadata in addition to the before/after diff so the
                    # dependent manifest can always observe the removal.
                    metadata = self._take_transition_metadata()
                    evicted = tuple(
                        getattr(result, "evicted", ()) or ()
                    ) + tuple(metadata.get("evicted", ()) or ())
                    recovered = tuple(
                        getattr(result, "recovered", ()) or ()
                    ) + tuple(metadata.get("recovered", ()) or ())
                    events = self._transition_events(
                        before,
                        after,
                        reason,
                        evicted=evicted,
                        recovered=recovered,
                    )
            if durable_outbox:
                self.drain_transition_outbox()
            elif events:
                self._dispatch_transitions(events)
            return result

        return wrapped

    return decorator


def _serialize_transition_mutation(method):
    """Serialize a queue mutation that intentionally emits no event."""

    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._transition_mutation_lock:
            return method(self, *args, **kwargs)

    return wrapped


class ReconciliationQueueStore(Protocol):
    """Persistence contract used by a queue instance."""

    def load(self) -> tuple[ReconciliationTask, ...]:
        """Load the durable task snapshot for one library."""
        ...

    def load_snapshot(self) -> ReconciliationQueueSnapshot:
        """Load tasks and the cross-process generation atomically."""
        ...

    def replace(
        self,
        tasks: tuple[ReconciliationTask, ...],
        *,
        expected_generation: int | None = None,
    ) -> int:
        """Replace tasks using an optional compare-and-swap generation."""
        ...

    def enqueue_or_merge(
        self,
        *,
        path: str | Path,
        reason: str,
        operation_id: str | None,
        expected_revision: int | None,
        observed_revision: int | None,
        kind: ReconciliationKind = ReconciliationKind.ASSET_INDEX_ROOT_RESCAN,
        payload: Mapping[str, object] | None = None,
        max_tasks: int,
        max_attempts: int,
        now: float,
    ) -> ReconciliationQueueMutationResult:
        """Upsert one task and return a refreshed durable snapshot."""
        ...

    def claim_next(
        self,
        *,
        now: float,
        lease_seconds: float,
    ) -> ReconciliationQueueClaimResult:
        """Atomically claim a due task and return a refreshed snapshot."""
        ...

    def renew_lease(
        self,
        task_id: str,
        *,
        expected_attempts: int,
        lease_token: str | None,
        lease_seconds: float,
        now: float,
    ) -> ReconciliationQueueMutationResult:
        """Extend one running lease with task/attempt/token CAS."""
        ...

    def recover_expired_running(
        self,
        *,
        now: float,
    ) -> ReconciliationQueueRecoveryResult:
        """Recover expired running tasks with one per-task SQL transaction."""
        ...

    def mark_succeeded(
        self,
        task_id: str,
        *,
        revision: int | None,
        expected_attempts: int,
        lease_token: str | None,
        now: float,
    ) -> ReconciliationQueueMutationResult:
        """Complete a running task with state/lease CAS."""
        ...

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
        """Retry or terminally exhaust a running task with state/lease CAS."""
        ...

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
        """Terminally resolve a task with state/lease CAS."""
        ...

    def cancel(
        self,
        task_id: str,
        *,
        expected_attempts: int | None,
        lease_token: str | None,
        now: float,
    ) -> ReconciliationQueueMutationResult:
        """Cancel a task with state/lease CAS."""
        ...

    def claim_transition_outbox(
        self,
        *,
        limit: int,
        lease_seconds: float,
    ) -> tuple[ReconciliationTransitionOutboxEntry, ...]:
        """Lease committed transition records for at-least-once delivery."""
        ...

    def renew_transition_outbox_lease(
        self,
        event_id: int,
        *,
        delivery_token: str,
        lease_seconds: float,
    ) -> bool:
        """Extend one active transition-delivery lease with token CAS."""
        ...

    def acknowledge_transition_outbox(
        self,
        event_id: int,
        *,
        delivery_token: str,
    ) -> bool:
        """Mark a successfully delivered transition durable."""
        ...

    def fail_transition_outbox(
        self,
        event_id: int,
        *,
        delivery_token: str,
        error: BaseException,
    ) -> bool:
        """Persist a failed delivery retry or terminal dead-letter decision."""
        ...

    def list_transition_outbox_dead_letters(
        self,
        *,
        limit: int = 100,
        before_event_id: int | None = None,
    ) -> tuple[ReconciliationTransitionOutboxDeadLetter, ...]:
        """List immutable dead-letter records newest first."""
        ...

    def replay_transition_outbox_dead_letter(
        self,
        event_id: int,
        *,
        expected_dead_lettered_at: float | None = None,
    ) -> bool:
        """Restore one dead-letter event to the live outbox with CAS semantics."""
        ...

    def transition_outbox_metrics(
        self,
        *,
        now: float | None = None,
    ) -> ReconciliationTransitionOutboxMetrics:
        """Return queue age, lease, attempt and dead-letter observations."""
        ...

    def prune_transition_outbox(
        self,
        *,
        acknowledged_before: float | None = None,
        dead_letter_before: float | None = None,
        limit: int = 1000,
    ) -> ReconciliationTransitionOutboxPruneResult:
        """Apply explicit bounded retention to ACKed and dead-letter rows."""
        ...


class ReconciliationQueue:
    """Thread-safe bounded queue with pluggable durable persistence.

    The queue is scoped by the caller that constructs it (currently one
    ``LibraryScopedServices`` bundle per library session). Tasks are
    deduplicated by ``(library_root, path, kind)``. ``persistence_path`` keeps
    the existing atomic JSON marker contract; ``persistence_store`` can provide
    a transactional backend such as SQLite. The queue itself remains the owner
    of in-process state transitions and condition notification.
    """

    def __init__(
        self,
        *,
        library_root: str | Path,
        max_tasks: int = 200,
        max_attempts: int = 5,
        persistence_path: str | Path | None = None,
        persistence_store: ReconciliationQueueStore | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        cross_process_poll_interval: float = 0.5,
        transition_listener: Callable[[ReconciliationTaskTransition], object] | None = None,
    ) -> None:
        if max_tasks < 1:
            raise ValueError("max_tasks must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if persistence_path is not None and persistence_store is not None:
            raise ValueError("persistence_path and persistence_store are mutually exclusive")
        if (
            not isinstance(cross_process_poll_interval, (int, float))
            or isinstance(cross_process_poll_interval, bool)
            or not float(cross_process_poll_interval) > 0.0
            or not float(cross_process_poll_interval) < 60.0
        ):
            raise ValueError(
                "cross_process_poll_interval must be finite, positive, and less than 60 seconds"
            )
        self.library_root = _canonical_path(library_root)
        self.max_tasks = max_tasks
        self.max_attempts = max_attempts
        self._clock = clock
        self._wall_clock = wall_clock
        self._path = Path(persistence_path) if persistence_path is not None else None
        self._store = persistence_store
        self.cross_process_poll_interval = float(cross_process_poll_interval)
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._transition_mutation_lock = threading.RLock()
        # A global ``delivered_at`` represents only the canonical
        # import-manifest consumer.  Generic callbacks remain observers so
        # dynamic registration cannot redefine durable completion.
        self._durable_transition_consumer_id: str | None = None
        self._durable_transition_consumer: (
            Callable[[ReconciliationTaskTransition], object] | None
        ) = None
        self._transition_listener = transition_listener
        self._transition_listeners: list[
            Callable[[ReconciliationTaskTransition], object]
        ] = []
        # A stop/wake signal must not depend on acquiring the queue lock,
        # because store-backed mutations may hold it across bounded DB I/O.
        self._wake_event = threading.Event()
        self._tasks: dict[tuple[str, str, ReconciliationKind], ReconciliationTask] = {}
        self._generation = 0
        self._transition_local = threading.local()
        # A listener is normally registered after bootstrap constructs the
        # manifest recovery service.  Keep a bounded hand-off buffer so lease
        # recovery performed during queue construction is not silently lost.
        self._transition_backlog: list[_TransitionBacklogEntry] = []
        self._transition_backlog_limit = 1024
        self._transition_backlog_overflow_count = 0
        self._transition_dispatch_lock = threading.RLock()
        self._load()
        startup_recovered: tuple[ReconciliationTask, ...] = ()
        durable_outbox = self._uses_durable_transition_outbox()
        with self._lock:
            if durable_outbox:
                try:
                    assert self._store is not None
                    result = self._store.recover_expired_running(now=self._clock())
                    self._set_store_snapshot_unlocked(result.snapshot)
                    startup_recovered = tuple(result.recovered)
                except ReconciliationQueuePersistenceConflict as conflict:
                    # Another process took over the durable generation while
                    # this process was recovering expired leases.  Degrade to
                    # a read-only load of the newer durable snapshot instead
                    # of failing the library open; the owning process applies
                    # whatever recovery is still required.
                    try:
                        assert self._store is not None
                        snapshot = self._store.load_snapshot()
                        self._set_store_snapshot_unlocked(snapshot)
                    except Exception:
                        # A failed reload keeps the newest state this queue
                        # has seen rather than failing startup.
                        pass
                    _log.warning(
                        "Reconciliation queue startup recovery lost a cross-process "
                        "generation race; continuing with the newer durable snapshot: %s",
                        conflict,
                    )
                    # The transitions computed from the losing snapshot are
                    # no longer authoritative.  Do not dispatch a stale
                    # lease-expiry event after another process has published
                    # the winner; its current snapshot (and a later recovery
                    # pass) is the only safe source for dependent bookkeeping.
                    startup_recovered = ()
            else:
                recovered = self._recover_expired_running_unlocked(self._clock())
                startup_recovered = tuple(recovered)
                if recovered:
                    try:
                        self._persist_and_notify_unlocked()
                    except ReconciliationQueuePersistenceConflict as conflict:
                        # Another process took over the durable generation while
                        # this process was recovering expired leases.  Degrade to
                        # a read-only load of the newer durable snapshot instead
                        # of failing the library open; the owning process applies
                        # whatever recovery is still required.
                        try:
                            assert self._store is not None
                            snapshot = self._store.load_snapshot()
                            self._set_store_snapshot_unlocked(snapshot)
                        except Exception:
                            # ``_persist_unlocked`` already refreshed the
                            # in-memory snapshot when the conflict was raised; a
                            # failed reload keeps the newest state this queue has
                            # seen rather than failing startup.
                            pass
                        _log.warning(
                            "Reconciliation queue startup recovery lost a cross-process "
                            "generation race; continuing with the newer durable snapshot: %s",
                            conflict,
                        )
                        # The transitions computed from the losing snapshot are
                        # no longer authoritative. Do not dispatch a stale
                        # lease-expiry event after another process has published
                        # the winner; its current snapshot (and a later recovery
                        # pass) is the only safe source for dependent bookkeeping.
                        startup_recovered = ()
        # Queue construction can recover an expired lease before the manifest
        # recovery service exists.  Buffer the transition (or deliver it to a
        # constructor-supplied listener) only after releasing the queue lock.
        if durable_outbox:
            self.drain_transition_outbox()
        elif startup_recovered:
            self._dispatch_transitions(
                tuple(
                    self._transition(
                        None,
                        task,
                        "lease_expired",
                        operation_ids=task.operation_ids,
                    )
                    for task in startup_recovered
                )
            )

    def add_transition_listener(
        self,
        listener: Callable[[ReconciliationTaskTransition], object],
    ) -> None:
        """Register a best-effort observer for committed task transitions.

        With the SQLite durable outbox, observers run only after the one
        durable consumer has ACKed a transition.  Their return values and
        failures never change the durable ACK condition.  Memory-backed queues
        retain their historical advisory listener behavior.
        """
        if not callable(listener):
            raise TypeError("transition listener must be callable")
        with self._lock:
            if all(
                not _same_listener(existing, listener)
                for existing in self._transition_listeners
            ):
                self._transition_listeners.append(listener)
        if not self._uses_durable_transition_outbox():
            self.retry_transition_backlog()

    def set_durable_transition_consumer(
        self,
        consumer_id: str,
        listener: Callable[[ReconciliationTaskTransition], object],
    ) -> None:
        """Set the sole consumer whose disposition may acknowledge outbox rows.

        The physical outbox has one ``delivered_at`` marker, so its consumer
        identity is fixed to import-manifest recovery.  Re-registering the
        same bound callback is idempotent; a different callback or consumer id
        is rejected rather than making pending history registration-dependent.
        """
        if consumer_id != IMPORT_MANIFEST_RECOVERY_CONSUMER_ID:
            raise ValueError(
                "the reconciliation transition outbox only supports "
                f"{IMPORT_MANIFEST_RECOVERY_CONSUMER_ID!r}"
            )
        if not callable(listener):
            raise TypeError("durable transition consumer must be callable")
        with self._lock:
            current = self._durable_transition_consumer
            if (
                current is not None
                and (
                    self._durable_transition_consumer_id != consumer_id
                    or not _same_listener(current, listener)
                )
            ):
                raise ValueError("a durable transition consumer is already registered")
            self._durable_transition_consumer_id = consumer_id
            self._durable_transition_consumer = listener
        if self._uses_durable_transition_outbox():
            self.drain_transition_outbox()
        else:
            self.retry_transition_backlog()

    def remove_transition_listener(
        self,
        listener: Callable[[ReconciliationTaskTransition], object],
    ) -> None:
        """Remove a transition callback if it is currently registered."""
        with self._lock:
            self._transition_listeners = [
                existing
                for existing in self._transition_listeners
                if not _same_listener(existing, listener)
            ]

    def _snapshot_for_transition(self) -> tuple[ReconciliationTask, ...]:
        """Take a local snapshot without forcing a cross-process refresh."""
        with self._lock:
            return tuple(sorted(self._tasks.values(), key=lambda task: task.task_id))

    def _clear_transition_metadata(self) -> None:
        self._transition_local.metadata = {}

    def _remember_transition_metadata(
        self,
        *,
        evicted: tuple[ReconciliationTask, ...] = (),
        recovered: tuple[ReconciliationTask, ...] = (),
    ) -> None:
        metadata = getattr(self._transition_local, "metadata", None)
        if not isinstance(metadata, dict):
            metadata = {}
        if evicted:
            metadata["evicted"] = tuple(evicted)
        if recovered:
            metadata["recovered"] = tuple(recovered)
        self._transition_local.metadata = metadata

    def _take_transition_metadata(self) -> dict[str, tuple[ReconciliationTask, ...]]:
        metadata = getattr(self._transition_local, "metadata", {})
        self._transition_local.metadata = {}
        return metadata if isinstance(metadata, dict) else {}

    @staticmethod
    def _transition_events(
        before: tuple[ReconciliationTask, ...],
        after: tuple[ReconciliationTask, ...],
        reason: str,
        *,
        evicted: tuple[ReconciliationTask, ...] = (),
        recovered: tuple[ReconciliationTask, ...] = (),
    ) -> tuple[ReconciliationTaskTransition, ...]:
        """Build deterministic events for one committed queue mutation."""
        before_by_id = {task.task_id: task for task in before}
        after_by_id = {task.task_id: task for task in after}
        events: list[ReconciliationTaskTransition] = []
        seen: set[tuple[str, str]] = set()
        explicit_ids = {
            task.task_id for task in (*evicted, *recovered)
        }

        def add(
            previous: ReconciliationTask | None,
            current: ReconciliationTask | None,
            event_reason: str,
        ) -> None:
            task = current or previous
            if task is None:
                return
            ids = tuple(
                dict.fromkeys(
                    tuple(getattr(previous, "operation_ids", ()) or ())
                    + tuple(getattr(current, "operation_ids", ()) or ())
                )
            )
            key = (task.task_id, event_reason)
            if key in seen:
                return
            seen.add(key)
            events.append(
                ReconciliationTaskTransition(
                    previous=previous,
                    current=current,
                    reason=event_reason,
                    operation_ids=ids,
                )
            )

        for task in evicted:
            add(before_by_id.get(task.task_id) or task, None, "evicted")
        for task in recovered:
            add(before_by_id.get(task.task_id), after_by_id.get(task.task_id) or task, "lease_expired")
        for task_id in sorted(set(before_by_id) | set(after_by_id)):
            previous = before_by_id.get(task_id)
            current = after_by_id.get(task_id)
            if previous != current and task_id not in explicit_ids:
                add(previous, current, reason)
        return tuple(events)

    def _emit_transition_events(
        self,
        before: tuple[ReconciliationTask, ...],
        after: tuple[ReconciliationTask, ...],
        reason: str,
    ) -> None:
        """Dispatch changed task identities after a public mutation commits."""
        events = self._transition_events(before, after, reason)
        if events:
            self._dispatch_transitions(events)

    @property
    def persistence_path(self) -> Path | None:
        return self._path

    @property
    def persistence_generation(self) -> int:
        """Return the durable snapshot generation known by this queue."""
        with self._lock:
            return self._generation

    def set_transition_listener(
        self,
        listener: Callable[[ReconciliationTaskTransition], object] | None,
    ) -> None:
        """Set the legacy primary observer for committed transitions.

        It cannot acknowledge a SQLite outbox row.  Durable integrations must
        register the canonical import-manifest consumer explicitly through
        :meth:`set_durable_transition_consumer`.
        """
        if listener is not None and not callable(listener):
            raise TypeError("transition listener must be callable")
        with self._lock:
            self._transition_listener = listener
        if listener is not None:
            self.retry_transition_backlog()

    def _uses_durable_transition_outbox(self) -> bool:
        """Whether this store owns durable transition delivery for this queue."""
        return bool(
            self._store is not None
            and getattr(self._store, "transition_outbox_enabled", False)
            and callable(getattr(self._store, "claim_transition_outbox", None))
            and callable(getattr(self._store, "acknowledge_transition_outbox", None))
            and callable(getattr(self._store, "fail_transition_outbox", None))
        )

    @property
    def durable_transition_outbox_enabled(self) -> bool:
        """Expose whether committed transitions use the durable delivery path."""
        return self._uses_durable_transition_outbox()

    @staticmethod
    def _deliver_transition_to_listener(
        listener: Callable[[ReconciliationTaskTransition], object],
        transition: ReconciliationTaskTransition,
    ) -> None:
        """Invoke an advisory observer and preserve its local retry signal."""
        disposition = listener(transition)
        # ``None`` preserves the original observer contract.  A ``RETRY`` is
        # retained only in the bounded local observer backlog; it never updates
        # the durable outbox's retry state.
        if disposition is None or disposition in {
            ReconciliationTransitionDisposition.APPLIED,
            ReconciliationTransitionDisposition.STALE,
        }:
            return
        if disposition is ReconciliationTransitionDisposition.RETRY:
            raise _ReconciliationTransitionRetryRequested(
                f"transition consumer requested retry for task {transition.task_id}"
            )
        raise TypeError(
            "transition listener must return None or a "
            "ReconciliationTransitionDisposition"
        )

    @staticmethod
    def _deliver_durable_transition_to_consumer(
        consumer: Callable[[ReconciliationTaskTransition], object],
        transition: ReconciliationTaskTransition,
    ) -> None:
        """Invoke the canonical consumer and require an explicit disposition."""
        disposition = consumer(transition)
        if disposition in {
            ReconciliationTransitionDisposition.APPLIED,
            ReconciliationTransitionDisposition.STALE,
        }:
            return
        if disposition is ReconciliationTransitionDisposition.RETRY:
            raise _ReconciliationTransitionRetryRequested(
                f"transition consumer requested retry for task {transition.task_id}"
            )
        raise TypeError(
            "durable transition consumer must return a "
            "ReconciliationTransitionDisposition"
        )

    def _run_transition_outbox_lease_heartbeat(
        self,
        *,
        event_id: int,
        delivery_token: str,
        lease_seconds: float,
        renew_until: float,
        stop_event: threading.Event,
        errors: list[BaseException],
    ) -> None:
        """Renew an active delivery lease while a durable callback is running.

        The callback itself cannot be safely interrupted.  Renewal therefore
        stops at ``renew_until`` so a stuck callback eventually loses
        ownership and another process can replay the immutable event.
        """
        assert self._store is not None
        renew = getattr(self._store, "renew_transition_outbox_lease", None)
        if not callable(renew):
            return
        interval = max(min(lease_seconds / 3.0, 5.0), 0.01)
        while not stop_event.wait(interval):
            if time.monotonic() >= renew_until:
                return
            try:
                renewed = renew(
                    event_id,
                    delivery_token=delivery_token,
                    lease_seconds=lease_seconds,
                )
            except BaseException as exc:
                if not stop_event.is_set():
                    errors.append(exc)
                return
            if stop_event.is_set():
                return
            if not renewed:
                errors.append(
                    ReconciliationQueuePersistenceConflict(
                        "Reconciliation transition outbox lease renewal lost ownership",
                        retryable=True,
                        operation="transition_outbox_renew",
                    )
                )
                return

    def drain_transition_outbox(
        self,
        *,
        limit: int = 64,
        lease_seconds: float = 30.0,
        callback_max_age: float = _TRANSITION_OUTBOX_CALLBACK_MAX_AGE_SECONDS,
    ) -> int:
        """Deliver committed SQLite transitions and ACK each accepted event.

        A leased row is retried after process loss or callback failure.  The
        canonical consumer is renewed while it runs, but renewal is bounded
        by ``callback_max_age`` so a stuck callback eventually becomes
        replayable by another process.  Generic observers run only after a
        successful durable acknowledgement.
        """
        if not self._uses_durable_transition_outbox():
            return self.retry_transition_backlog()
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit < 1
        ):
            raise ValueError("transition outbox drain limit must be a positive integer")
        if (
            not isinstance(lease_seconds, (int, float))
            or isinstance(lease_seconds, bool)
            or not isfinite(float(lease_seconds))
            or lease_seconds <= 0
        ):
            raise ValueError("transition outbox delivery lease must be finite and positive")
        if (
            not isinstance(callback_max_age, (int, float))
            or isinstance(callback_max_age, bool)
            or not isfinite(float(callback_max_age))
            or callback_max_age <= 0
        ):
            raise ValueError("transition outbox callback_max_age must be finite and positive")
        assert self._store is not None
        with self._transition_dispatch_lock:
            consumer = self._durable_transition_consumer_snapshot()
            if consumer is None:
                return 0
            delivered = 0
            for _ in range(limit):
                try:
                    claimed = self._store.claim_transition_outbox(
                        limit=1,
                        lease_seconds=float(lease_seconds),
                    )
                except Exception:
                    _log.exception("Could not claim reconciliation transition outbox entry")
                    break
                if not claimed:
                    break
                entry = claimed[0]
                heartbeat_stop = threading.Event()
                heartbeat_errors: list[BaseException] = []
                callback_started_at = time.monotonic()
                callback_deadline = callback_started_at + float(callback_max_age)
                heartbeat: threading.Thread | None = None
                heartbeat_started = False
                if callable(
                    getattr(self._store, "renew_transition_outbox_lease", None)
                ):
                    heartbeat = threading.Thread(
                        target=self._run_transition_outbox_lease_heartbeat,
                        kwargs={
                            "event_id": entry.event_id,
                            "delivery_token": entry.delivery_token,
                            "lease_seconds": float(lease_seconds),
                            "renew_until": callback_deadline,
                            "stop_event": heartbeat_stop,
                            "errors": heartbeat_errors,
                        },
                        name=f"reconciliation-transition-outbox-lease-{entry.event_id}",
                        daemon=True,
                    )
                delivery_error: BaseException | None = None
                try:
                    if heartbeat is not None:
                        heartbeat.start()
                        heartbeat_started = True
                    self._deliver_durable_transition_to_consumer(consumer, entry.transition)
                except Exception as exc:
                    delivery_error = exc
                finally:
                    heartbeat_stop.set()
                    if heartbeat_started and heartbeat is not None:
                        heartbeat.join()
                if delivery_error is None and heartbeat_errors:
                    delivery_error = heartbeat_errors[0]
                if delivery_error is None and time.monotonic() >= callback_deadline:
                    delivery_error = TimeoutError(
                        "Reconciliation transition durable callback exceeded its age budget"
                    )
                if delivery_error is not None:
                    try:
                        self._store.fail_transition_outbox(
                            entry.event_id,
                            delivery_token=entry.delivery_token,
                            error=delivery_error,
                        )
                    except Exception:
                        _log.exception(
                            "Could not release failed reconciliation transition outbox entry %s",
                            entry.event_id,
                        )
                    _log.error(
                        "Reconciliation task transition durable delivery failed for event %s",
                        entry.event_id,
                        exc_info=(
                            type(delivery_error),
                            delivery_error,
                            delivery_error.__traceback__,
                        ),
                    )
                    # Do not deliver a later transition while this event is
                    # pending; its next claim retains the per-library order.
                    break
                try:
                    acknowledged = self._store.acknowledge_transition_outbox(
                        entry.event_id,
                        delivery_token=entry.delivery_token,
                    )
                except Exception:
                    _log.exception(
                        "Could not acknowledge reconciliation transition outbox entry %s",
                        entry.event_id,
                    )
                    break
                if acknowledged:
                    delivered += 1
                    # Generic observers are intentionally post-ACK: their
                    # lifecycle cannot redefine the manifest consumer's
                    # durable completion contract.
                    self._dispatch_transitions((entry.transition,))
                else:
                    _log.warning(
                        "Reconciliation transition outbox lease was lost before acknowledgement: %s",
                        entry.event_id,
                    )
                    break
        return delivered

    def list_transition_outbox_dead_letters(
        self,
        *,
        limit: int = 100,
        before_event_id: int | None = None,
    ) -> tuple[ReconciliationTransitionOutboxDeadLetter, ...]:
        """Read durable delivery dead letters for an operator-facing view.

        Persistence adapters predating v45 expose no dead-letter table; those
        adapters return an empty result so the queue remains backwards
        compatible.
        """
        store = self._store
        method = getattr(store, "list_transition_outbox_dead_letters", None)
        if store is None or not callable(method):
            return ()
        return cast(
            tuple[ReconciliationTransitionOutboxDeadLetter, ...],
            method(limit=limit, before_event_id=before_event_id),
        )

    def replay_transition_outbox_dead_letter(
        self,
        event_id: int,
        *,
        expected_dead_lettered_at: float | None = None,
    ) -> bool:
        """Request one explicit, audited replay of a durable dead letter.

        The store restores the original event id in one SQLite transaction and
        leaves the dead-letter row untouched.  A successful restore is then
        eligible for the canonical consumer; a repeated request is a no-op
        once the live event already exists.
        """
        store = self._store
        method = getattr(store, "replay_transition_outbox_dead_letter", None)
        if store is None or not callable(method):
            return False
        replayed = bool(
            method(
                event_id,
                expected_dead_lettered_at=expected_dead_lettered_at,
            )
        )
        if replayed:
            self._wake_event.set()
            # A caller with a registered canonical consumer gets the same
            # bounded synchronous opportunity as a normal queue mutation.  If
            # no consumer is registered, the restored row remains durable.
            self.drain_transition_outbox()
        return replayed

    def transition_outbox_metrics(
        self,
        *,
        now: float | None = None,
    ) -> ReconciliationTransitionOutboxMetrics:
        """Return durable outbox delivery observations when supported."""
        store = self._store
        method = getattr(store, "transition_outbox_metrics", None)
        if store is None or not callable(method):
            return ReconciliationTransitionOutboxMetrics()
        return cast(ReconciliationTransitionOutboxMetrics, method(now=now))

    def prune_transition_outbox(
        self,
        *,
        acknowledged_before: float | None = None,
        dead_letter_before: float | None = None,
        limit: int = 1000,
    ) -> ReconciliationTransitionOutboxPruneResult:
        """Run an explicit bounded retention pass through the persistence store."""
        store = self._store
        method = getattr(store, "prune_transition_outbox", None)
        if store is None or not callable(method):
            return ReconciliationTransitionOutboxPruneResult()
        return cast(
            ReconciliationTransitionOutboxPruneResult,
            method(
                acknowledged_before=acknowledged_before,
                dead_letter_before=dead_letter_before,
                limit=limit,
            ),
        )

    @property
    def transition_backlog_size(self) -> int:
        """Return the number of transition deliveries awaiting retry."""
        with self._lock:
            return len(self._transition_backlog)

    @property
    def transition_backlog_overflow_count(self) -> int:
        """Return the number of hand-off entries lost at the bounded limit."""
        with self._lock:
            return self._transition_backlog_overflow_count

    def retry_transition_backlog(self) -> int:
        """Retry failed transition deliveries once.

        Queue mutations call this implicitly before delivering new events.  A
        recovery service may call it explicitly after restoring a listener.
        Failed callbacks remain queued; the durable queue mutation is never
        rolled back because bookkeeping is advisory.
        """
        if self._uses_durable_transition_outbox():
            delivered = self.drain_transition_outbox()
            return delivered + self._retry_transition_backlog_once()
        return self._retry_transition_backlog_once()

    def _retry_transition_backlog_once(self) -> int:
        """Retry the bounded advisory callback backlog once."""
        with self._transition_dispatch_lock:
            with self._lock:
                if not self._transition_backlog:
                    return 0
                backlog = tuple(self._transition_backlog)
                self._transition_backlog.clear()
            self._dispatch_backlog_entries(backlog)
            return len(backlog)

    @property
    def transition_listener(
        self,
    ) -> Callable[[ReconciliationTaskTransition], object] | None:
        with self._lock:
            return self._transition_listener

    def _dispatch_transitions(
        self,
        transitions: tuple[ReconciliationTaskTransition, ...],
    ) -> None:
        """Invoke transition listeners outside the queue lock.

        A callback is advisory bookkeeping: the queue's own durable mutation
        has already committed.  Failed callbacks are retained in a bounded
        backlog and retried on the next mutation or explicit recovery pass.
        """
        if not transitions:
            return
        with self._transition_dispatch_lock:
            # A previously failed callback gets a chance before the newly
            # produced event.  This makes recovery progress even when no new
            # task is generated after the callback comes back online.
            with self._lock:
                backlog = tuple(self._transition_backlog)
                self._transition_backlog.clear()
            entries = backlog + tuple(
                _TransitionBacklogEntry(transition)
                for transition in transitions
            )
            self._dispatch_backlog_entries(entries)

    def _listeners_snapshot(
        self,
    ) -> tuple[Callable[[ReconciliationTaskTransition], object], ...]:
        durable_outbox = self._uses_durable_transition_outbox()
        with self._lock:
            listeners: list[Callable[[ReconciliationTaskTransition], object]] = []
            if (
                not durable_outbox
                and self._durable_transition_consumer is not None
            ):
                listeners.append(self._durable_transition_consumer)
            if self._transition_listener is not None:
                listeners.append(self._transition_listener)
            listeners.extend(self._transition_listeners)
            return tuple(
                listener
                for index, listener in enumerate(listeners)
                if not any(
                    _same_listener(listener, prior)
                    for prior in listeners[:index]
                )
            )

    def _durable_transition_consumer_snapshot(
        self,
    ) -> Callable[[ReconciliationTaskTransition], object] | None:
        """Read the one durable consumer without holding it during delivery."""
        with self._lock:
            return self._durable_transition_consumer

    @staticmethod
    def _listener_matches_any(
        listener: Callable[[ReconciliationTaskTransition], object],
        candidates: tuple[Callable[[ReconciliationTaskTransition], object], ...],
    ) -> bool:
        return any(_same_listener(listener, candidate) for candidate in candidates)

    def _append_transition_backlog(self, entry: _TransitionBacklogEntry) -> None:
        """Retain a failed delivery while making bounded overflow observable."""
        with self._lock:
            # Coalesce repeated notifications for the same task and listener
            # scope.  Only the latest durable state is needed by an idempotent
            # bookkeeping consumer.
            for index, existing in enumerate(self._transition_backlog):
                if existing.transition.task_id != entry.transition.task_id:
                    continue
                old_targets = existing.listeners
                new_targets = entry.listeners
                if old_targets is None or new_targets is None:
                    same_scope = old_targets is None and new_targets is None
                else:
                    same_scope = len(old_targets) == len(new_targets) and all(
                        self._listener_matches_any(listener, new_targets)
                        for listener in old_targets
                    )
                if same_scope:
                    self._transition_backlog[index] = entry
                    return
            if len(self._transition_backlog) >= self._transition_backlog_limit:
                self._transition_backlog.pop(0)
                self._transition_backlog_overflow_count += 1
                _log.error(
                    "Reconciliation transition backlog overflow; oldest delivery "
                    "was dropped (task=%s, overflow_count=%d)",
                    entry.transition.task_id,
                    self._transition_backlog_overflow_count,
                )
            self._transition_backlog.append(entry)

    def _dispatch_backlog_entries(
        self,
        entries: tuple[_TransitionBacklogEntry, ...],
    ) -> None:
        for entry in entries:
            listeners = self._listeners_snapshot()
            if entry.listeners is None:
                targets = listeners
            else:
                targets = tuple(
                    listener
                    for listener in listeners
                    if self._listener_matches_any(listener, entry.listeners)
                )
                # A listener may have been replaced after a failure.  Let the
                # replacement observe the durable event rather than pinning
                # the entry to a dead callback forever.
                if not targets and listeners:
                    targets = listeners
            if not targets:
                self._append_transition_backlog(entry)
                continue
            failed: list[Callable[[ReconciliationTaskTransition], object]] = []
            for listener in targets:
                try:
                    self._deliver_transition_to_listener(
                        listener,
                        entry.transition,
                    )
                except Exception:
                    failed.append(listener)
                    _log.exception(
                        "Reconciliation task transition listener failed for %s",
                        entry.transition.task_id,
                    )
            if failed:
                self._append_transition_backlog(
                    _TransitionBacklogEntry(entry.transition, tuple(failed))
                )

    @staticmethod
    def _transition(
        previous: ReconciliationTask | None,
        current: ReconciliationTask | None,
        reason: str,
        *,
        operation_ids: tuple[str, ...] | None = None,
    ) -> ReconciliationTaskTransition:
        ids = operation_ids
        if ids is None:
            task = current or previous
            ids = () if task is None else task.operation_ids
        return ReconciliationTaskTransition(
            previous=previous,
            current=current,
            reason=reason,
            operation_ids=tuple(ids),
        )


    def __len__(self) -> int:
        with self._lock:
            return len(self._tasks)

    def snapshot(self) -> tuple[ReconciliationTask, ...]:
        """Return tasks in deterministic creation order without consuming them."""
        with self._lock:
            return tuple(sorted(self._tasks.values(), key=lambda task: (task.created_at, task.task_id)))

    def get(self, task_id: str) -> ReconciliationTask | None:
        with self._lock:
            return next((task for task in self._tasks.values() if task.task_id == task_id), None)

    def wait_for_change(self, timeout: float | None = None) -> bool:
        """Wait until a queue mutation, wake signal, or timeout occurs."""
        # Consume an already-published wake before entering Condition.wait();
        # otherwise a wake that happened just before this call could be lost.
        if self._wake_event.is_set():
            self._wake_event.clear()
            return True
        with self._condition:
            if self._wake_event.is_set():
                self._wake_event.clear()
                return True
            changed = self._condition.wait(timeout)
        if self._wake_event.is_set():
            self._wake_event.clear()
            return True
        return changed

    def wait_for_ready(
        self,
        *,
        now: float,
        timeout: float | None = None,
    ) -> bool:
        """Wait for ready work without losing cross-process queue changes.

        The SQLite generation is a durable change sequence.  A condition
        notification is only an in-process fast path; store-backed queues also
        refresh a complete ``load_snapshot()`` at a bounded poll interval.
        The timeout is an overall deadline, not the timeout of each poll.
        ``False`` means the deadline expired or an explicit ``wake()`` was
        consumed; an ordinary queue notification without due work is not a
        terminal result and continues waiting.
        """
        if timeout is not None:
            if (
                not isinstance(timeout, (int, float))
                or isinstance(timeout, bool)
                or not float(timeout) >= 0.0
                or not float(timeout) < float("inf")
            ):
                raise ValueError("timeout must be finite and non-negative")
        deadline = None if timeout is None else time.monotonic() + float(timeout)

        # A zero timeout is a local, non-blocking check.  It must not enter a
        # synchronous DB read after the caller's deadline has already elapsed.
        if timeout == 0:
            with self._lock:
                return any(task.is_due(now) for task in self._tasks.values())

        # This initial refresh closes the enqueue-before-wait window.  It is
        # deliberately outside the Condition lock because SQLite I/O can block.
        if self._store is not None and (deadline is None or time.monotonic() < deadline):
            self._refresh_store_snapshot()

        current_now = now
        while True:
            # Refresh the due clock from the queue's own clock on every
            # iteration.  A caller-supplied ``now`` can be stale by the time
            # the loop runs (the caller's clock may lag or have been captured
            # before this wait); a fixed value would make an already-due task
            # wait one full poll round before it is recognized.
            current_now = self._clock()
            with self._condition:
                if self._wake_event.is_set():
                    self._wake_event.clear()
                    return False
                if any(task.is_due(current_now) for task in self._tasks.values()):
                    return True
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0.0:
                    return False
                next_due = min(
                    (
                        task.next_attempt_at
                        for task in self._tasks.values()
                        if task.state
                        in {ReconciliationState.PENDING, ReconciliationState.RETRYABLE}
                    ),
                    default=None,
                )
                wait_for = remaining
                if next_due is not None:
                    due_wait = max(0.0, next_due - current_now)
                    wait_for = due_wait if wait_for is None else min(wait_for, due_wait)
                if self._store is not None:
                    poll = self.cross_process_poll_interval
                    wait_for = poll if wait_for is None else min(wait_for, poll)
                self._condition.wait(wait_for)

            # Explicit wake is checked before DB refresh so stop is not delayed
            # by a read/retry operation that began after the condition wake.
            if self._wake_event.is_set():
                self._wake_event.clear()
                return False
            if deadline is not None and time.monotonic() >= deadline:
                return False
            if self._store is not None:
                self._refresh_store_snapshot()

    def wake(self) -> None:
        """Wake a worker without waiting for a queue/DB mutation lock."""
        self._wake_event.set()
        if self._condition.acquire(blocking=False):
            try:
                self._condition.notify_all()
            finally:
                self._condition.release()

    def next_due_at(self) -> float | None:
        """Return the earliest due timestamp among pending tasks."""
        with self._lock:
            due = [
                task.next_attempt_at
                for task in self._tasks.values()
                if task.state in {ReconciliationState.PENDING, ReconciliationState.RETRYABLE}
            ]
            return min(due) if due else None

    @_notify_task_transitions("enqueue")
    def enqueue_or_merge(
        self,
        *,
        path: str | Path,
        reason: str,
        operation_id: str | None = None,
        expected_revision: int | None = None,
        observed_revision: int | None = None,
        kind: ReconciliationKind = ReconciliationKind.ASSET_INDEX_ROOT_RESCAN,
        payload: Mapping[str, object] | None = None,
        now: float | None = None,
    ) -> ReconciliationTask:
        """Add a task or merge a new warning into its active task.

        ``operation_id`` is audit metadata only and is never part of the
        deduplication key.  A completed task is replaced when a later warning
        requests the same repair scope.
        """
        timestamp = self._now(now)
        path_value = _canonical_path(path)
        normalized_payload = normalize_reconciliation_payload(
            kind, payload, library_root=self.library_root
        )
        key = (self.library_root, path_value, kind)
        if self._store is not None:
            with self._lock:
                try:
                    result = self._store.enqueue_or_merge(
                        path=path_value,
                        reason=reason,
                        operation_id=operation_id,
                        expected_revision=expected_revision,
                        observed_revision=observed_revision,
                        kind=kind,
                        payload=json.loads(normalized_payload),
                        max_tasks=self.max_tasks,
                        max_attempts=self.max_attempts,
                        now=timestamp,
                    )
                    self._set_store_snapshot_unlocked(result.snapshot)
                except ReconciliationQueuePersistenceConflict as conflict:
                    self._refresh_after_persistence_conflict_unlocked(conflict)
                    raise
                except ReconciliationQueueFull:
                    raise
                except ReconciliationQueuePersistenceError:
                    raise
                except Exception as exc:
                    raise ReconciliationQueuePersistenceError(
                        "Cannot atomically enqueue reconciliation task in persistence store"
                    ) from exc
                self._remember_transition_metadata(evicted=tuple(result.evicted))
                self._condition.notify_all()
                return result.task
        with self._lock:
            existing = self._tasks.get(key)
            if existing is not None and existing.state in _ACTIVE_STATES:
                operation_ids = _merge_operation_ids(existing.operation_ids, operation_id)
                merged = replace(
                    existing,
                    reason=reason or existing.reason,
                    operation_ids=operation_ids,
                    expected_revision=(
                        expected_revision
                        if expected_revision is not None
                        else existing.expected_revision
                    ),
                    observed_revision=(
                        observed_revision
                        if observed_revision is not None
                        else existing.observed_revision
                    ),
                    payload=normalized_payload,
                    updated_at=timestamp,
                )
                self._tasks[key] = merged
                self._persist_and_notify_unlocked()
                return merged

            evicted: list[ReconciliationTask] = []
            if existing is not None:
                del self._tasks[key]
                evicted.append(existing)
            evicted.extend(self._ensure_capacity_unlocked())
            task = ReconciliationTask(
                task_id=f"recon-{uuid4().hex}",
                library_root=self.library_root,
                path=path_value,
                kind=kind,
                reason=reason,
                operation_ids=_merge_operation_ids((), operation_id),
                next_attempt_at=timestamp,
                created_at=timestamp,
                updated_at=timestamp,
                max_attempts=self.max_attempts,
                expected_revision=expected_revision,
                observed_revision=observed_revision,
                payload=normalized_payload,
            )
            self._tasks[key] = task
            self._persist_and_notify_unlocked()
            self._remember_transition_metadata(evicted=tuple(evicted))
            return task

    @_notify_task_transitions("claim")
    def claim_next(
        self,
        *,
        now: float | None = None,
        lease_seconds: float = 30.0,
    ) -> ReconciliationTask | None:
        """Atomically claim the oldest due task for a worker."""
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        timestamp = self._now(now)
        if self._store is not None:
            with self._lock:
                try:
                    result = self._store.claim_next(
                        now=timestamp,
                        lease_seconds=lease_seconds,
                    )
                    self._set_store_snapshot_unlocked(result.snapshot)
                except ReconciliationQueuePersistenceConflict as conflict:
                    self._refresh_after_persistence_conflict_unlocked(conflict)
                    raise
                except ReconciliationQueuePersistenceError:
                    raise
                except Exception as exc:
                    raise ReconciliationQueuePersistenceError(
                        "Cannot atomically claim reconciliation task from persistence store"
                    ) from exc
                if result.claimed is not None:
                    self._condition.notify_all()
                self._remember_transition_metadata(recovered=tuple(result.recovered))
                return result.claimed
        with self._lock:
            changed = self._recover_expired_running_unlocked(timestamp)
            candidates = [
                task
                for task in self._tasks.values()
                if task.state in {ReconciliationState.PENDING, ReconciliationState.RETRYABLE}
                and task.next_attempt_at <= timestamp
            ]
            if not candidates:
                if changed:
                    self._persist_and_notify_unlocked()
                    self._remember_transition_metadata(recovered=tuple(changed))
                return None
            current = min(candidates, key=lambda task: (task.next_attempt_at, task.created_at, task.task_id))
            claimed = replace(
                current,
                state=ReconciliationState.RUNNING,
                attempts=current.attempts + 1,
                lease_expires_at=timestamp + lease_seconds,
                lease_token=uuid4().hex,
                updated_at=timestamp,
            )
            self._tasks[current.repair_key] = claimed
            self._persist_and_notify_unlocked()
            self._remember_transition_metadata(recovered=tuple(changed))
            return claimed

    @_serialize_transition_mutation
    def renew_lease(
        self,
        task_id: str,
        *,
        expected_attempts: int | None = None,
        lease_token: str | None = None,
        lease_seconds: float = 30.0,
        now: float | None = None,
    ) -> ReconciliationTask:
        """Extend a running task lease without changing its ownership token."""
        if (
            not isinstance(lease_seconds, (int, float))
            or isinstance(lease_seconds, bool)
            or not isfinite(float(lease_seconds))
            or lease_seconds <= 0
        ):
            raise ValueError("lease_seconds must be finite and positive")
        timestamp = self._now(now)
        if self._store is not None:
            with self._lock:
                task = self._require(task_id)
                claimed_attempts = _resolve_expected_attempts(
                    task,
                    expected_attempts,
                    task_id=task_id,
                )
                try:
                    result = self._store.renew_lease(
                        task_id,
                        expected_attempts=claimed_attempts,
                        lease_token=lease_token,
                        lease_seconds=float(lease_seconds),
                        now=timestamp,
                    )
                    self._set_store_snapshot_unlocked(result.snapshot)
                except ReconciliationQueuePersistenceConflict as conflict:
                    self._refresh_after_persistence_conflict_unlocked(conflict)
                    raise
                except ReconciliationQueuePersistenceError:
                    raise
                except Exception as exc:
                    raise ReconciliationQueuePersistenceError(
                        "Cannot renew reconciliation task lease in persistence store"
                    ) from exc
                return result.task
        with self._lock:
            task = self._require(task_id)
            claimed_attempts = _resolve_expected_attempts(
                task,
                expected_attempts,
                task_id=task_id,
            )
            _ensure_worker_lease(
                task,
                expected_attempts=claimed_attempts,
                lease_token=lease_token,
                now=timestamp,
                operation="renew",
            )
            renewed = replace(
                task,
                lease_expires_at=timestamp + float(lease_seconds),
                updated_at=timestamp,
            )
            self._tasks[task.repair_key] = renewed
            self._persist_and_notify_unlocked()
            return renewed

    @_notify_task_transitions("succeeded")
    def mark_succeeded(
        self,
        task_id: str,
        *,
        revision: int | None = None,
        expected_attempts: int | None = None,
        lease_token: str | None = None,
        now: float | None = None,
    ) -> ReconciliationTask:
        """Mark a claimed task as durably repaired."""
        timestamp = self._now(now)
        if self._store is not None:
            with self._lock:
                task = self._require(task_id)
                claimed_attempts = _resolve_expected_attempts(
                    task,
                    expected_attempts,
                    task_id=task_id,
                )
                try:
                    result = self._store.mark_succeeded(
                        task_id,
                        revision=revision,
                        expected_attempts=claimed_attempts,
                        lease_token=lease_token,
                        now=timestamp,
                    )
                    self._set_store_snapshot_unlocked(result.snapshot)
                except ReconciliationQueuePersistenceConflict as conflict:
                    self._refresh_after_persistence_conflict_unlocked(conflict)
                    raise
                except ReconciliationQueuePersistenceError:
                    raise
                except Exception as exc:
                    raise ReconciliationQueuePersistenceError(
                        "Cannot atomically complete reconciliation task in persistence store"
                    ) from exc
                self._condition.notify_all()
                return result.task
        with self._lock:
            task = self._require(task_id)
            claimed_attempts = _resolve_expected_attempts(
                task,
                expected_attempts,
                task_id=task_id,
            )
            _ensure_worker_lease(
                task,
                expected_attempts=claimed_attempts,
                lease_token=lease_token,
                now=timestamp,
                operation="completion",
            )
            completed = replace(
                task,
                state=ReconciliationState.SUCCEEDED,
                observed_revision=revision if revision is not None else task.observed_revision,
                last_error_type=None,
                last_error=None,
                lease_expires_at=None,
                lease_token=None,
                updated_at=timestamp,
            )
            self._tasks[task.repair_key] = completed
            self._persist_and_notify_unlocked()
            return completed

    @_notify_task_transitions("retryable")
    def mark_retryable(
        self,
        task_id: str,
        *,
        error_type: str | None = None,
        error: str | None = None,
        reason: str | None = None,
        next_attempt_at: float | None = None,
        expected_attempts: int | None = None,
        lease_token: str | None = None,
        now: float | None = None,
    ) -> ReconciliationTask:
        """Return a running task to retryable state or exhaust it."""
        timestamp = self._now(now)
        if self._store is not None:
            with self._lock:
                task = self._require(task_id)
                claimed_attempts = _resolve_expected_attempts(
                    task,
                    expected_attempts,
                    task_id=task_id,
                )
                try:
                    result = self._store.mark_retryable(
                        task_id,
                        error_type=error_type,
                        error=error,
                        reason=reason,
                        next_attempt_at=next_attempt_at,
                        expected_attempts=claimed_attempts,
                        lease_token=lease_token,
                        now=timestamp,
                    )
                    self._set_store_snapshot_unlocked(result.snapshot)
                except ReconciliationQueuePersistenceConflict as conflict:
                    self._refresh_after_persistence_conflict_unlocked(conflict)
                    raise
                except ReconciliationQueuePersistenceError:
                    raise
                except Exception as exc:
                    raise ReconciliationQueuePersistenceError(
                        "Cannot atomically retry reconciliation task in persistence store"
                    ) from exc
                self._condition.notify_all()
                return result.task
        with self._lock:
            task = self._require(task_id)
            claimed_attempts = _resolve_expected_attempts(
                task,
                expected_attempts,
                task_id=task_id,
            )
            _ensure_worker_lease(
                task,
                expected_attempts=claimed_attempts,
                lease_token=lease_token,
                now=timestamp,
                operation="completion",
            )
            if task.attempts >= task.max_attempts:
                terminal = replace(
                    task,
                    state=ReconciliationState.TERMINAL,
                    last_error_type=error_type,
                    last_error=error,
                    lease_expires_at=None,
                    lease_token=None,
                    updated_at=timestamp,
                )
                self._tasks[task.repair_key] = terminal
                self._persist_and_notify_unlocked()
                return terminal
            retry_reason = reason or task.reason
            retry_at = (
                next_attempt_at
                if next_attempt_at is not None
                else timestamp + reconciliation_backoff(retry_reason, task.attempts)
            )
            retryable = replace(
                task,
                state=ReconciliationState.RETRYABLE,
                reason=retry_reason,
                next_attempt_at=retry_at,
                last_error_type=error_type,
                last_error=error,
                lease_expires_at=None,
                lease_token=None,
                updated_at=timestamp,
            )
            self._tasks[task.repair_key] = retryable
            self._persist_and_notify_unlocked()
            return retryable

    @_notify_task_transitions("terminal")
    def mark_terminal(
        self,
        task_id: str,
        *,
        error_type: str | None = None,
        error: str | None = None,
        expected_attempts: int | None = None,
        lease_token: str | None = None,
        now: float | None = None,
    ) -> ReconciliationTask:
        """Stop automatic retry for a task while retaining its audit state."""
        timestamp = self._now(now)
        if self._store is not None:
            with self._lock:
                task = self._require(task_id)
                claimed_attempts = _resolve_nonretryable_attempts(
                    task,
                    expected_attempts,
                    lease_token=lease_token,
                    task_id=task_id,
                )
                try:
                    result = self._store.mark_terminal(
                        task_id,
                        error_type=error_type,
                        error=error,
                        expected_attempts=claimed_attempts,
                        lease_token=lease_token,
                        now=timestamp,
                    )
                    self._set_store_snapshot_unlocked(result.snapshot)
                except ReconciliationQueuePersistenceConflict as conflict:
                    self._refresh_after_persistence_conflict_unlocked(conflict)
                    raise
                except ReconciliationQueuePersistenceError:
                    raise
                except Exception as exc:
                    raise ReconciliationQueuePersistenceError(
                        "Cannot atomically terminally resolve reconciliation task in persistence store"
                    ) from exc
                self._condition.notify_all()
                return result.task
        with self._lock:
            task = self._require(task_id)
            if task.state in _FINISHED_STATES:
                return task
            claimed_attempts = _resolve_nonretryable_attempts(
                task,
                expected_attempts,
                lease_token=lease_token,
                task_id=task_id,
            )
            if claimed_attempts is not None:
                _ensure_worker_lease(
                    task,
                    expected_attempts=claimed_attempts,
                    lease_token=lease_token,
                    now=timestamp,
                    operation="state_mutation",
                )
            terminal = replace(
                task,
                state=ReconciliationState.TERMINAL,
                last_error_type=error_type,
                last_error=error,
                lease_expires_at=None,
                lease_token=None,
                updated_at=timestamp,
            )
            self._tasks[task.repair_key] = terminal
            self._persist_and_notify_unlocked()
            return terminal

    @_notify_task_transitions("cancelled")
    def cancel(
        self,
        task_id: str,
        *,
        expected_attempts: int | None = None,
        lease_token: str | None = None,
        now: float | None = None,
    ) -> ReconciliationTask:
        """Cancel a task without treating it as a successful repair."""
        timestamp = self._now(now)
        if self._store is not None:
            with self._lock:
                task = self._require(task_id)
                claimed_attempts = _resolve_nonretryable_attempts(
                    task,
                    expected_attempts,
                    lease_token=lease_token,
                    task_id=task_id,
                )
                try:
                    result = self._store.cancel(
                        task_id,
                        expected_attempts=claimed_attempts,
                        lease_token=lease_token,
                        now=timestamp,
                    )
                    self._set_store_snapshot_unlocked(result.snapshot)
                except ReconciliationQueuePersistenceConflict as conflict:
                    self._refresh_after_persistence_conflict_unlocked(conflict)
                    raise
                except ReconciliationQueuePersistenceError:
                    raise
                except Exception as exc:
                    raise ReconciliationQueuePersistenceError(
                        "Cannot atomically cancel reconciliation task in persistence store"
                    ) from exc
                self._condition.notify_all()
                return result.task
        with self._lock:
            task = self._require(task_id)
            if task.state in _FINISHED_STATES:
                return task
            claimed_attempts = _resolve_nonretryable_attempts(
                task,
                expected_attempts,
                lease_token=lease_token,
                task_id=task_id,
            )
            if claimed_attempts is not None:
                _ensure_worker_lease(
                    task,
                    expected_attempts=claimed_attempts,
                    lease_token=lease_token,
                    now=timestamp,
                    operation="state_mutation",
                )
            cancelled = replace(task, state=ReconciliationState.CANCELLED, lease_expires_at=None, lease_token=None, updated_at=timestamp)
            self._tasks[task.repair_key] = cancelled
            self._persist_and_notify_unlocked()
            return cancelled

    @_notify_task_transitions("lease_expired")
    def recover_expired_running(self, *, now: float | None = None) -> tuple[ReconciliationTask, ...]:
        """Make tasks whose worker lease expired eligible for another attempt."""
        timestamp = self._now(now)
        if self._store is not None:
            with self._lock:
                try:
                    result = self._store.recover_expired_running(now=timestamp)
                    self._set_store_snapshot_unlocked(result.snapshot)
                except ReconciliationQueuePersistenceConflict as conflict:
                    self._refresh_after_persistence_conflict_unlocked(conflict)
                    raise
                except ReconciliationQueuePersistenceError:
                    raise
                except Exception as exc:
                    raise ReconciliationQueuePersistenceError(
                        "Cannot recover expired reconciliation leases in persistence store"
                    ) from exc
                if result.recovered:
                    self._condition.notify_all()
                return result.recovered
        with self._lock:
            recovered = self._recover_expired_running_unlocked(timestamp)
            if recovered:
                self._persist_and_notify_unlocked()
            return tuple(recovered)

    def _recover_expired_running_unlocked(self, timestamp: float) -> list[ReconciliationTask]:
        recovered: list[ReconciliationTask] = []
        for task in tuple(self._tasks.values()):
            if task.state is not ReconciliationState.RUNNING:
                continue
            if task.lease_token is not None and task.lease_expires_at is not None and task.lease_expires_at > timestamp:
                continue
            if task.attempts >= task.max_attempts:
                next_task = replace(
                    task,
                    state=ReconciliationState.TERMINAL,
                    last_error_type="LeaseExpired",
                    last_error="worker lease expired",
                    lease_expires_at=None,
                    lease_token=None,
                    updated_at=timestamp,
                )
            else:
                next_task = replace(
                    task,
                    state=ReconciliationState.RETRYABLE,
                    next_attempt_at=timestamp + reconciliation_backoff(task.reason, task.attempts),
                    last_error_type="LeaseExpired",
                    last_error="worker lease expired",
                    lease_expires_at=None,
                    lease_token=None,
                    updated_at=timestamp,
                )
            self._tasks[task.repair_key] = next_task
            recovered.append(next_task)
        return recovered

    def _ensure_capacity_unlocked(self) -> tuple[ReconciliationTask, ...]:
        if len(self._tasks) < self.max_tasks:
            return ()
        evictable = [task for task in self._tasks.values() if task.state in _FINISHED_STATES]
        if not evictable:
            raise ReconciliationQueueFull(
                f"reconciliation queue is full ({self.max_tasks})"
            )
        victim = min(evictable, key=lambda task: (task.updated_at, task.created_at, task.task_id))
        del self._tasks[victim.repair_key]
        return (victim,)

    def _require(self, task_id: str) -> ReconciliationTask:
        task = self.get(task_id)
        if task is None:
            raise KeyError(task_id)
        return task

    def _now(self, value: float | None) -> float:
        return self._clock() if value is None else value

    def _refresh_store_snapshot(self) -> bool:
        """Refresh a store-backed queue without holding the Condition lock."""
        if self._store is None:
            return False
        snapshot = self._store.load_snapshot()
        with self._condition:
            # A refresh may have started before another local mutation
            # advanced the in-memory generation.  Never publish an older
            # durable snapshot over a newer local one.
            if snapshot.generation <= self._generation:
                return False
            self._set_store_snapshot_unlocked(snapshot)
            self._condition.notify_all()
            return True

    def refresh(self) -> bool:
        """Refresh a durable queue snapshot when another writer advanced it.

        The refresh is a hint/reconciliation operation, not an ownership
        operation.  SQLite-backed queues read the generation and task rows
        atomically.  JSON queues explicitly reload their marker as a
        single-process compatibility path and make no cross-process claim.
        """
        if self._store is not None:
            return self._refresh_store_snapshot()
        if self._path is None:
            return False
        with self._condition:
            before = tuple(self._tasks.values())
            self._load()
            changed = tuple(self._tasks.values()) != before
            if changed:
                self._condition.notify_all()
            return changed

    def _refresh_after_persistence_conflict_unlocked(
        self,
        conflict: ReconciliationQueuePersistenceConflict,
    ) -> None:
        # Mutation callers invoke this while holding the queue's one Condition
        # lock level.  Release that level while doing potentially blocking DB I/O.
        self._lock.release()
        try:
            try:
                snapshot = self._store.load_snapshot() if self._store is not None else None
            except Exception as refresh_error:
                try:
                    conflict.add_note(
                        "Queue refresh after persistence conflict failed: "
                        f"{type(refresh_error).__name__}: {refresh_error}"
                    )
                except (AttributeError, TypeError):
                    pass
                return
        finally:
            self._lock.acquire()
        if snapshot is not None and snapshot.generation >= self._generation:
            self._set_store_snapshot_unlocked(snapshot)

    def _set_store_snapshot_unlocked(
        self,
        snapshot: ReconciliationQueueSnapshot,
    ) -> None:
        if snapshot.generation < 0:
            raise ValueError("invalid reconciliation queue generation")
        if snapshot.generation < self._generation:
            # Runtime refreshes are monotonic.  Initialization starts at zero,
            # while a late read must never roll a newer local snapshot back.
            return
        loaded = {
            task.repair_key: task
            for task in snapshot.tasks
            if task.library_root == self.library_root
        }
        self._generation = snapshot.generation
        self._tasks = loaded
        if len(self._tasks) > self.max_tasks:
            self._tasks = dict(
                sorted(
                    self._tasks.items(),
                    key=lambda pair: pair[1].updated_at,
                )[-self.max_tasks:]
            )

    def _load(self) -> None:
        if self._store is not None:
            try:
                snapshot = self._store.load_snapshot()
                self._set_store_snapshot_unlocked(snapshot)
            except ReconciliationQueuePersistenceError:
                raise
            except Exception as exc:
                raise ReconciliationQueuePersistenceError(
                    "Cannot load reconciliation queue from persistence store"
                ) from exc
            return
        if self._path is None or not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("unsupported reconciliation queue format")
            version = int(raw.get("version", 0))
            if version not in {1, _FORMAT_VERSION}:
                raise ValueError("unsupported reconciliation queue format")
            tasks = raw.get("tasks", [])
            if not isinstance(tasks, list):
                raise ValueError("reconciliation queue tasks must be a list")
            loaded: dict[tuple[str, str, ReconciliationKind], ReconciliationTask] = {}
            now_monotonic = self._clock()
            now_wallclock = self._wall_clock()
            for item in tasks:
                task = _task_from_json(
                    item,
                    version=version,
                    now_monotonic=now_monotonic,
                    now_wallclock=now_wallclock,
                )
                if task.library_root != self.library_root:
                    continue
                loaded[task.repair_key] = task
            self._tasks = loaded
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ReconciliationQueuePersistenceError(
                f"Cannot load reconciliation queue marker: {self._path}"
            ) from exc
        if len(self._tasks) > self.max_tasks:
            self._tasks = dict(
                sorted(self._tasks.items(), key=lambda pair: pair[1].updated_at)[-self.max_tasks:]
            )

    def _persist_and_notify_unlocked(self) -> None:
        self._persist_unlocked()
        self._condition.notify_all()

    def _persist_unlocked(self) -> None:
        if self._store is not None:
            try:
                self._generation = self._store.replace(
                    tuple(self._tasks.values()),
                    expected_generation=self._generation,
                )
            except ReconciliationQueuePersistenceConflict as conflict:
                try:
                    snapshot = self._store.load_snapshot()
                    self._set_store_snapshot_unlocked(snapshot)
                except Exception as refresh_error:
                    try:
                        conflict.add_note(
                            "Queue refresh after persistence conflict failed: "
                            f"{type(refresh_error).__name__}: {refresh_error}"
                        )
                    except (AttributeError, TypeError):
                        pass
                raise
            except ReconciliationQueuePersistenceError:
                raise
            except Exception as exc:
                raise ReconciliationQueuePersistenceError(
                    "Cannot persist reconciliation queue to persistence store"
                ) from exc
            return
        if self._path is None:
            return
        now_monotonic = self._clock()
        now_wallclock = self._wall_clock()
        payload = {
            "version": _FORMAT_VERSION,
            "clock": "wallclock-deadlines",
            "library_root": self.library_root,
            "tasks": [
                _task_to_json(task, now_monotonic, now_wallclock)
                for task in self.snapshot()
            ],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            dir=str(self._path.parent),
            prefix=f".{self._path.stem}_",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._path)
        except OSError as exc:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise ReconciliationQueuePersistenceError(
                f"Cannot persist reconciliation queue marker: {self._path}"
            ) from exc


def reconciliation_backoff(reason: str, attempt: int) -> float:
    """Return bounded seconds before the next attempt for a failure reason."""
    if attempt < 1:
        raise ValueError("attempt must be positive")
    normalized = reason.lower().replace("-", "_")
    if normalized in {"busy", "locked"}:
        base, cap = 0.25, 8.0
    elif normalized == "stale":
        base, cap = 0.5, 16.0
    elif normalized in {"scan_failed", "scanfailure"}:
        base, cap = 2.0, 60.0
    elif normalized == "staged":
        base, cap = 1.0, 30.0
    else:
        base, cap = 1.0, 30.0
    return min(cap, base * (2 ** min(attempt - 1, 30)))


def _canonical_path(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.path.normpath(os.fspath(path))))


def _resolve_expected_attempts(
    task: ReconciliationTask,
    expected_attempts: int | None,
    *,
    task_id: str,
) -> int:
    """Resolve a worker mutation's immutable claim attempt.

    Legacy callers may omit ``expected_attempts`` while the local snapshot is
    still running; worker code should pass the value captured at claim time so
    a refreshed retryable snapshot cannot downgrade the mutation to an admin
    operation.
    """
    if expected_attempts is None:
        if task.state is not ReconciliationState.RUNNING:
            raise ValueError(f"Task {task_id} is not running")
        return task.attempts
    if (
        not isinstance(expected_attempts, int)
        or isinstance(expected_attempts, bool)
        or expected_attempts < 1
    ):
        raise ValueError("expected_attempts must be a positive integer")
    return expected_attempts


def _resolve_nonretryable_attempts(
    task: ReconciliationTask,
    expected_attempts: int | None,
    *,
    lease_token: str | None,
    task_id: str,
) -> int | None:
    """Separate worker-scoped terminal/cancel from administrative mutation."""
    if expected_attempts is not None:
        return _resolve_expected_attempts(
            task,
            expected_attempts,
            task_id=task_id,
        )
    if task.state is ReconciliationState.RUNNING:
        if lease_token is None:
            # Token-less administrative forced termination of a running task
            # is authoritative: no lease/attempt CAS applies.  A running
            # worker's later completion CAS will then fail, which is the
            # intended outcome of an admin terminal/cancel.
            return None
        return task.attempts
    if lease_token is not None:
        raise ReconciliationQueuePersistenceConflict(
            "Reconciliation task worker mutation lost its claim context",
            stale_worker_completion=True,
            operation="state_mutation",
        )
    return None


def _ensure_worker_lease(
    task: ReconciliationTask,
    *,
    expected_attempts: int,
    lease_token: str | None,
    now: float,
    operation: str,
) -> None:
    """Reject worker mutations unless the complete lease CAS still holds."""
    if (
        task.state is not ReconciliationState.RUNNING
        or task.attempts != expected_attempts
        or not lease_token
        or task.lease_token != lease_token
        or task.lease_expires_at is None
        or task.lease_expires_at <= now
    ):
        raise ReconciliationQueuePersistenceConflict(
            "Reconciliation task lease ownership is no longer current",
            stale_worker_completion=True,
            operation=operation,
        )


def _merge_operation_ids(existing: tuple[str, ...], operation_id: str | None) -> tuple[str, ...]:
    if not operation_id or operation_id in existing:
        return existing
    return (*existing, operation_id)


def _task_to_json(
    task: ReconciliationTask,
    now_monotonic: float,
    now_wallclock: float,
) -> dict[str, object]:
    data = asdict(task)
    data["kind"] = task.kind.value
    data["state"] = task.state.value
    data["operation_ids"] = list(task.operation_ids)
    data["next_attempt_at_wallclock"] = now_wallclock + max(
        0.0, task.next_attempt_at - now_monotonic
    )
    data["lease_expires_at_wallclock"] = (
        now_wallclock + max(0.0, task.lease_expires_at - now_monotonic)
        if task.lease_expires_at is not None
        else None
    )
    # Keep the old keys present for human diagnostics, but never use their
    # monotonic values to restore a task in a later process.
    data["next_attempt_at"] = None
    data["lease_expires_at"] = None
    return data


def _task_from_json(
    item: object,
    *,
    version: int,
    now_monotonic: float,
    now_wallclock: float,
) -> ReconciliationTask:
    if not isinstance(item, dict):
        raise ValueError("reconciliation queue task must be an object")
    try:
        operation_ids = item.get("operation_ids", ())
        if not isinstance(operation_ids, list | tuple):
            raise ValueError("operation_ids must be a list")
        kind = ReconciliationKind(str(item["kind"]))
        state = ReconciliationState(
            str(item.get("state", ReconciliationState.PENDING.value))
        )
        if version >= 2:
            next_wallclock = item.get("next_attempt_at_wallclock")
            lease_wallclock = item.get("lease_expires_at_wallclock")
            next_attempt_at = (
                now_monotonic
                if next_wallclock is None
                else now_monotonic + max(
                    0.0, float(next_wallclock) - now_wallclock
                )
            )
            lease_expires_at = (
                None
                if lease_wallclock is None
                else now_monotonic + max(
                    0.0, float(lease_wallclock) - now_wallclock
                )
            )
        else:
            # v1 persisted monotonic timestamps cannot be compared safely
            # after process restart. Active tasks are therefore made due and
            # running leases are recovered immediately rather than risked as
            # permanently stuck tasks.
            next_attempt_at = (
                now_monotonic
                if state in _ACTIVE_STATES
                else float(item.get("next_attempt_at", now_monotonic))
            )
            lease_expires_at = None if state is ReconciliationState.RUNNING else (
                float(item["lease_expires_at"])
                if item.get("lease_expires_at") is not None
                else None
            )
        max_attempts = int(item.get("max_attempts", 5))
        attempts = int(item.get("attempts", 0))
        if max_attempts < 1 or attempts < 0:
            raise ValueError("invalid reconciliation attempt bounds")
        return ReconciliationTask(
            task_id=str(item["task_id"]),
            library_root=_canonical_path(str(item["library_root"])),
            path=_canonical_path(str(item["path"])),
            kind=kind,
            reason=str(item["reason"]),
            state=state,
            attempts=attempts,
            next_attempt_at=next_attempt_at,
            operation_ids=tuple(str(value) for value in operation_ids),
            last_error_type=(
                str(item["last_error_type"])
                if item.get("last_error_type") is not None
                else None
            ),
            last_error=(
                str(item["last_error"])
                if item.get("last_error") is not None
                else None
            ),
            expected_revision=(
                int(item["expected_revision"])
                if item.get("expected_revision") is not None
                else None
            ),
            observed_revision=(
                int(item["observed_revision"])
                if item.get("observed_revision") is not None
                else None
            ),
            created_at=float(item.get("created_at", 0.0)),
            updated_at=float(item.get("updated_at", 0.0)),
            lease_expires_at=lease_expires_at,
            lease_token=(
                str(item["lease_token"])
                if item.get("lease_token") is not None
                else None
            ),
            max_attempts=max_attempts,
            payload=(
                normalize_reconciliation_payload(
                    kind,
                    json.loads(str(item.get("payload", "{}"))),
                    library_root=str(item["library_root"]),
                )
                if kind is ReconciliationKind.FILESYSTEM_PROJECTION_REPAIR
                else "{}"
            ),
        )
    except (KeyError, TypeError, ValueError, OverflowError, json.JSONDecodeError) as exc:
        raise ValueError("invalid reconciliation queue task") from exc
