"""Execute queued asset-index reconciliation tasks."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from sqlite3 import OperationalError
from math import isfinite
from time import monotonic, sleep, time
import threading
from typing import TYPE_CHECKING, Callable, Protocol

from AssetsManager.application.asset_index_service import (
    AssetIndexPublishResult,
    AssetIndexPublishStatus,
)
from AssetsManager.application.reconciliation_queue import (
    ReconciliationQueue,
    ReconciliationQueuePersistenceConflict,
    ReconciliationKind,
    ReconciliationQueuePersistenceError,
    ReconciliationState,
    ReconciliationTask,
)
from AssetsManager.repositories.asset_index_repository import AssetIndexRevisionConflict

if TYPE_CHECKING:
    from AssetsManager.application.asset_index_service import AssetIndexService
    from AssetsManager.application.context import LibrarySession


class ReconciliationWorkerStopTimeout(RuntimeError):
    """Raised when a worker does not stop within its bounded shutdown window."""


class _SweeperStopEvent(Protocol):
    """Minimum stop signal used by the periodic sweeper."""

    def wait(self, timeout: float | None = None) -> bool: ...


@dataclass(frozen=True, slots=True)
class ReconciliationAttemptResult:
    """Outcome of one claimed reconciliation task."""

    task: ReconciliationTask
    state: ReconciliationState
    publish_result: AssetIndexPublishResult | None = None
    error_type: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Return whether the projection reached durable success."""
        return self.state is ReconciliationState.SUCCEEDED

    @property
    def degraded(self) -> bool:
        """Return whether the repair remains unresolved."""
        return not self.ok


class AssetIndexReconciliationService:
    """Run idempotent asset-index tree rescans from a session queue.

    ``process_once`` remains the explicit, testable worker boundary.  The
    optional daemon worker uses the same state transitions and is stopped by
    the owning ``LibraryRuntime`` before the session closes.
    """

    def __init__(
        self,
        *,
        session: LibrarySession,
        asset_index_service: AssetIndexService,
        reconciliation_queue: ReconciliationQueue,
        projection_repair_service=None,
        import_manifest_recovery=None,
        clock: Callable[[], float] = monotonic,
        wall_clock: Callable[[], float] = time,
        max_consecutive_errors: int = 3,
        max_worker_restarts: int = 0,
        worker_restart_backoff: float = 1.0,
        max_persistence_conflict_retries: int = 2,
        persistence_conflict_backoff: float = 0.05,
        stop_timeout: float = 30.0,
        worker_lease_seconds: float = 30.0,
        worker_max_operation_age: float = 300.0,
        transition_outbox_prune_interval: float = 3600.0,
        transition_outbox_ack_retention_seconds: float = 7 * 24 * 60 * 60,
        transition_outbox_dead_letter_retention_seconds: float = 30 * 24 * 60 * 60,
        transition_outbox_prune_limit: int = 1000,
    ) -> None:
        self.session = session
        self.asset_index_service = asset_index_service
        self.reconciliation_queue = reconciliation_queue
        self.projection_repair_service = projection_repair_service
        # Optional duck-typed callback.  Keeping this dependency inverted lets
        # the queue worker acknowledge import manifests without importing the
        # manifest store (and therefore without creating an application-cycle).
        self.import_manifest_recovery = import_manifest_recovery
        if (
            not isinstance(max_consecutive_errors, int)
            or isinstance(max_consecutive_errors, bool)
            or max_consecutive_errors < 1
        ):
            raise ValueError("max_consecutive_errors must be a positive integer")
        if (
            not isinstance(max_worker_restarts, int)
            or isinstance(max_worker_restarts, bool)
            or max_worker_restarts < 0
        ):
            raise ValueError("max_worker_restarts must be a non-negative integer")
        if (
            not isinstance(worker_restart_backoff, (int, float))
            or isinstance(worker_restart_backoff, bool)
            or not isfinite(float(worker_restart_backoff))
            or worker_restart_backoff < 0
            or worker_restart_backoff >= 60.0
        ):
            raise ValueError(
                "worker_restart_backoff must be finite, non-negative, and less than 60 seconds"
            )
        if (
            not isinstance(max_persistence_conflict_retries, int)
            or isinstance(max_persistence_conflict_retries, bool)
            or max_persistence_conflict_retries < 0
        ):
            raise ValueError("max_persistence_conflict_retries must be a non-negative integer")
        if (
            not isinstance(persistence_conflict_backoff, (int, float))
            or isinstance(persistence_conflict_backoff, bool)
            or not isfinite(float(persistence_conflict_backoff))
            or persistence_conflict_backoff < 0
            or persistence_conflict_backoff >= 60.0
        ):
            raise ValueError(
                "persistence_conflict_backoff must be finite, non-negative, and less than 60 seconds"
            )
        if (
            not isinstance(stop_timeout, (int, float))
            or isinstance(stop_timeout, bool)
            or not isfinite(float(stop_timeout))
            or stop_timeout < 0
            or stop_timeout >= 60.0
        ):
            raise ValueError(
                "stop_timeout must be finite, non-negative, and less than 60 seconds"
            )
        if (
            not isinstance(worker_lease_seconds, (int, float))
            or isinstance(worker_lease_seconds, bool)
            or not isfinite(float(worker_lease_seconds))
            or worker_lease_seconds <= 0
        ):
            raise ValueError("worker_lease_seconds must be finite and positive")
        if (
            not isinstance(worker_max_operation_age, (int, float))
            or isinstance(worker_max_operation_age, bool)
            or not isfinite(float(worker_max_operation_age))
            or worker_max_operation_age <= 0
        ):
            raise ValueError("worker_max_operation_age must be finite and positive")
        if (
            not isinstance(transition_outbox_prune_interval, (int, float))
            or isinstance(transition_outbox_prune_interval, bool)
            or not isfinite(float(transition_outbox_prune_interval))
            or transition_outbox_prune_interval <= 0
        ):
            raise ValueError("transition_outbox_prune_interval must be finite and positive")
        if (
            not isinstance(transition_outbox_ack_retention_seconds, (int, float))
            or isinstance(transition_outbox_ack_retention_seconds, bool)
            or not isfinite(float(transition_outbox_ack_retention_seconds))
            or transition_outbox_ack_retention_seconds <= 0
        ):
            raise ValueError(
                "transition_outbox_ack_retention_seconds must be finite and positive"
            )
        if (
            not isinstance(transition_outbox_dead_letter_retention_seconds, (int, float))
            or isinstance(transition_outbox_dead_letter_retention_seconds, bool)
            or not isfinite(float(transition_outbox_dead_letter_retention_seconds))
            or transition_outbox_dead_letter_retention_seconds <= 0
        ):
            raise ValueError(
                "transition_outbox_dead_letter_retention_seconds must be finite and positive"
            )
        if (
            not isinstance(transition_outbox_prune_limit, int)
            or isinstance(transition_outbox_prune_limit, bool)
            or transition_outbox_prune_limit < 1
        ):
            raise ValueError("transition_outbox_prune_limit must be a positive integer")
        self._clock = clock
        self._wall_clock = wall_clock
        self._max_consecutive_errors = max_consecutive_errors
        self._max_worker_restarts = max_worker_restarts
        self._worker_restart_backoff = worker_restart_backoff
        self._max_persistence_conflict_retries = max_persistence_conflict_retries
        self._persistence_conflict_backoff = persistence_conflict_backoff
        self._stop_timeout = stop_timeout
        self._worker_lease_seconds = float(worker_lease_seconds)
        self._worker_max_operation_age = float(worker_max_operation_age)
        self._transition_outbox_prune_interval = float(
            transition_outbox_prune_interval
        )
        self._transition_outbox_ack_retention_seconds = float(
            transition_outbox_ack_retention_seconds
        )
        self._transition_outbox_dead_letter_retention_seconds = float(
            transition_outbox_dead_letter_retention_seconds
        )
        self._transition_outbox_prune_limit = transition_outbox_prune_limit
        self._lifecycle_lock = threading.RLock()
        self._stop_event: threading.Event | None = None
        self._worker: threading.Thread | None = None
        self._worker_error: str | None = None
        self._worker_faulted = False
        self._consecutive_worker_errors = 0
        self._worker_restart_count = 0
        self._sweeper_stop: threading.Event | None = None
        self._sweeper: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        """Return whether the session worker is currently alive."""
        with self._lifecycle_lock:
            return self._worker is not None and self._worker.is_alive()

    @property
    def last_worker_error(self) -> str | None:
        """Return the latest worker exception summary, if one occurred."""
        with self._lifecycle_lock:
            return self._worker_error

    @property
    def worker_faulted(self) -> bool:
        """Return whether the worker stopped because its error budget was exhausted."""
        with self._lifecycle_lock:
            return self._worker_faulted

    @property
    def consecutive_worker_errors(self) -> int:
        """Return the current consecutive worker exception count."""
        with self._lifecycle_lock:
            return self._consecutive_worker_errors

    @property
    def worker_restart_count(self) -> int:
        """Return the number of bounded automatic worker restarts."""
        with self._lifecycle_lock:
            return self._worker_restart_count

    def start(self) -> bool:
        """Start the daemon worker and its expired-lease sweeper.

        Return ``False`` if already running.
        """
        with self._lifecycle_lock:
            if self._worker is not None and self._worker.is_alive():
                return False
            stop_event = threading.Event()
            worker = threading.Thread(
                target=self._run_worker,
                args=(stop_event,),
                name=f"asset-reconciliation-{self.session.root_str}",
                daemon=True,
            )
            sweeper_stop = threading.Event()
            sweeper = threading.Thread(
                target=self._run_sweeper,
                args=(sweeper_stop,),
                name=f"asset-reconciliation-sweeper-{self.session.root_str}",
                daemon=True,
            )
            self._stop_event = stop_event
            self._worker = worker
            self._worker_error = None
            self._worker_faulted = False
            self._consecutive_worker_errors = 0
            self._worker_restart_count = 0
            self._sweeper_stop = sweeper_stop
            self._sweeper = sweeper
            try:
                worker.start()
                sweeper.start()
            except BaseException as exc:
                self._worker = None
                self._stop_event = None
                self._sweeper = None
                self._sweeper_stop = None
                self._worker_error = f"{type(exc).__name__}: {exc}"
                self._worker_faulted = True
                raise
            return True

    def stop(self, timeout: float | None = None) -> None:
        """Stop the worker within a bounded shutdown window.

        A timeout leaves the worker state intact so a caller can retry close
        after the underlying I/O unblocks; it never pretends that shutdown
        completed while the thread is still alive.
        """
        wait_timeout = self._stop_timeout if timeout is None else timeout
        if wait_timeout < 0:
            raise ValueError("timeout must be non-negative")
        with self._lifecycle_lock:
            worker = self._worker
            stop_event = self._stop_event
            if worker is None or stop_event is None:
                return
            stop_event.set()
            self.reconciliation_queue.wake()
        sweeper_stop = self._sweeper_stop
        if sweeper_stop is not None:
            sweeper_stop.set()
            sweeper = self._sweeper
            if sweeper is not None and sweeper is not threading.current_thread():
                sweeper.join(min(wait_timeout, 2.0))
        if worker is threading.current_thread():
            return
        worker.join(wait_timeout)
        if worker.is_alive():
            message = (
                "reconciliation worker did not stop within "
                f"{wait_timeout:.3f} seconds"
            )
            with self._lifecycle_lock:
                self._worker_error = message
                self._worker_faulted = True
            raise ReconciliationWorkerStopTimeout(message)
        with self._lifecycle_lock:
            if self._worker is worker:
                self._worker = None
                self._stop_event = None

    def _run_sweeper(self, stop_event: _SweeperStopEvent) -> None:
        """Periodically reclaim leases and prune expired outbox history.

        Heartbeats are capped (see :meth:`_lease_heartbeat`), so a stuck
        worker's lease expires ~lease_seconds after its renewal budget runs
        out.  The sweeper makes expiry actionable even when the stuck worker
        is the only claimer in this process: expired RUNNING tasks are
        flipped back to retryable within one sweep interval.
        """
        sweep_interval = 10.0
        next_outbox_prune_at = 0.0
        while not stop_event.wait(sweep_interval):
            try:
                retry_transitions = getattr(
                    self.reconciliation_queue,
                    "retry_transition_backlog",
                    None,
                )
                if callable(retry_transitions):
                    # v44 transition delivery is independent from whether a
                    # new reconciliation task becomes due.  Drain it from the
                    # existing lifecycle-owned sweeper so a failed listener
                    # replays while the library is otherwise idle.
                    retry_transitions()
            except BaseException:
                # Delivery is at-least-once and the outbox retains its head
                # event; a transient SQLite/listener failure must not take the
                # worker supervisor down.
                pass
            try:
                now_wallclock = self._wall_clock()
                if now_wallclock >= next_outbox_prune_at:
                    prune = getattr(
                        self.reconciliation_queue,
                        "prune_transition_outbox",
                        None,
                    )
                    if callable(prune):
                        prune(
                            acknowledged_before=(
                                now_wallclock
                                - self._transition_outbox_ack_retention_seconds
                            ),
                            dead_letter_before=(
                                now_wallclock
                                - self._transition_outbox_dead_letter_retention_seconds
                            ),
                            limit=self._transition_outbox_prune_limit,
                        )
                    next_outbox_prune_at = (
                        now_wallclock + self._transition_outbox_prune_interval
                    )
            except BaseException:
                # Prune is strictly retention-only.  Its SQLite failure must
                # leave pending rows untouched and retry on the next sweep.
                pass
            try:
                self.reconciliation_queue.recover_expired_running(
                    now=self._clock()
                )
            except BaseException:
                # A failed sweep is transient (SQLite contention); the next
                # interval retries.  Never take the worker down with it.
                pass

    def _run_worker(self, stop_event: threading.Event) -> None:
        consecutive_errors = 0
        restart_count = 0
        try:
            while not stop_event.is_set():
                try:
                    result = self.process_once(
                        _stop_event=stop_event,
                        lease_seconds=self._worker_lease_seconds,
                    )
                    if stop_event.is_set():
                        break
                    if result is None:
                        # Keep durable refresh errors inside the same
                        # supervisor boundary as process_once failures.
                        self.reconciliation_queue.wait_for_ready(
                            now=self._clock(),
                            timeout=1.0,
                        )
                except ReconciliationQueuePersistenceConflict as exc:
                    consecutive_errors += 1
                    with self._lifecycle_lock:
                        self._worker_error = f"{type(exc).__name__}: {exc}"
                        self._consecutive_worker_errors = consecutive_errors
                        # A conflict that escaped the operation-specific
                        # policy is not safe to replay through a generic
                        # worker restart.  Keep the worker visibly faulted.
                        self._worker_faulted = True
                    break
                except Exception as exc:
                    consecutive_errors += 1
                    with self._lifecycle_lock:
                        self._worker_error = f"{type(exc).__name__}: {exc}"
                        self._consecutive_worker_errors = consecutive_errors
                    if consecutive_errors >= self._max_consecutive_errors:
                        if restart_count >= self._max_worker_restarts:
                            with self._lifecycle_lock:
                                self._worker_faulted = True
                            break
                        restart_count += 1
                        with self._lifecycle_lock:
                            self._worker_restart_count = restart_count
                            # The worker remains alive while the supervisor
                            # starts a fresh processing epoch. ``faulted`` is
                            # reserved for the terminal, exhausted state.
                            self._worker_faulted = False
                        if stop_event.wait(self._worker_restart_backoff):
                            break
                        consecutive_errors = 0
                        with self._lifecycle_lock:
                            self._consecutive_worker_errors = 0
                        continue
                    # A failed process or durable refresh gets a bounded,
                    # stop-interruptible backoff.  Avoid another DB read here;
                    # the next normal loop performs the authoritative claim.
                    if stop_event.wait(min(2.0 ** (consecutive_errors - 1), 5.0)):
                        break
                    continue
                else:
                    consecutive_errors = 0
                    with self._lifecycle_lock:
                        self._consecutive_worker_errors = 0
                    # A non-None result is immediately followed by another
                    # claim; a None result already waited above.
                    continue
        finally:
            with self._lifecycle_lock:
                if self._worker is threading.current_thread():
                    self._worker = None
                    self._stop_event = None

    def process_once(
        self,
        *,
        now: float | None = None,
        lease_seconds: float = 30.0,
        _stop_event: threading.Event | None = None,
    ) -> ReconciliationAttemptResult | None:
        """Claim and execute one due task, with bounded persistence retries."""
        if (
            not isinstance(lease_seconds, (int, float))
            or isinstance(lease_seconds, bool)
            or not isfinite(float(lease_seconds))
            or lease_seconds <= 0
        ):
            raise ValueError("lease_seconds must be finite and positive")
        timestamp = self._clock() if now is None else now
        for conflict_retry in range(self._max_persistence_conflict_retries + 1):
            try:
                return self._process_once_attempt(
                    timestamp=timestamp,
                    lease_seconds=lease_seconds,
                    stop_event=_stop_event,
                )
            except ReconciliationQueuePersistenceConflict as conflict:
                if not self._is_retryable_persistence_conflict(conflict):
                    raise
                if conflict_retry >= self._max_persistence_conflict_retries:
                    raise
                self._refresh_after_persistence_conflict(conflict)
                if _stop_event is not None:
                    if _stop_event.wait(self._persistence_conflict_backoff):
                        return None
                elif self._persistence_conflict_backoff > 0:
                    sleep(self._persistence_conflict_backoff)
        raise AssertionError("unreachable persistence conflict retry loop")

    def _process_once_attempt(
        self,
        *,
        timestamp: float,
        lease_seconds: float,
        stop_event: threading.Event | None,
    ) -> ReconciliationAttemptResult | None:
        effective_lease_seconds = min(lease_seconds, self._worker_max_operation_age)
        task = self.reconciliation_queue.claim_next(
            now=timestamp,
            lease_seconds=effective_lease_seconds,
        )
        if task is None:
            return None

        self._mark_import_recovery_running(task)

        operation_started_at = self._clock()
        if (
            task.lease_expires_at is None
            or task.lease_expires_at <= operation_started_at
        ):
            expired_claim = ReconciliationQueuePersistenceConflict(
                "Reconciliation task lease expired before operation start",
                stale_worker_completion=True,
                operation="claim",
            )
            stale = self._stale_completion_noop(
                task,
                expired_claim,
                now=operation_started_at,
            )
            if stale is not None:
                return stale
            raise ReconciliationQueuePersistenceError(
                "Reconciliation task lease expired before operation start"
            ) from expired_claim
        renew_until = operation_started_at + self._worker_max_operation_age
        heartbeat_stop = threading.Event()
        heartbeat_errors: list[BaseException] = []
        heartbeat = threading.Thread(
            target=self._lease_heartbeat,
            args=(
                task,
                effective_lease_seconds,
                renew_until,
                heartbeat_stop,
                stop_event,
                heartbeat_errors,
            ),
            name=f"asset-reconciliation-lease-{task.task_id}",
            daemon=True,
        )
        try:
            heartbeat.start()
        except BaseException as exc:
            return self._retry(task, "heartbeat_start_failed", exc, self._clock())
        operation_error: BaseException | None = None
        operation_reason: str | None = None
        operation_is_terminal = False
        result: AssetIndexPublishResult | None = None
        is_projection_repair = (
            task.kind is ReconciliationKind.FILESYSTEM_PROJECTION_REPAIR
        )
        try:
            with self.session.operation():
                if is_projection_repair:
                    if self.projection_repair_service is None:
                        raise RuntimeError(
                            "filesystem projection repair service is not configured"
                        )
                    self.projection_repair_service.repair(task)
                else:
                    conn = self.session.connection_for(self.session.root)
                    result = self.asset_index_service.index_directory_tree_result(
                        conn,
                        self.session.root,
                        Path(task.path),
                    )
        except AssetIndexRevisionConflict as exc:
            operation_error = exc
            operation_reason = "stale"
        except OperationalError as exc:
            operation_error = exc
            operation_reason = "busy"
        except (FileNotFoundError, NotADirectoryError) as exc:
            operation_error = exc
            operation_is_terminal = True
        except OSError as exc:
            operation_error = exc
            operation_reason = "scan_failed"
        except Exception as exc:
            operation_error = exc
            operation_is_terminal = True
        finally:
            heartbeat_stop.set()
            heartbeat.join()

        completion_timestamp = self._clock()
        durably_committed = (
            result is not None
            and result.published
            and result.committed is True
        )
        if completion_timestamp >= renew_until:
            if (
                result is not None
                and durably_committed
                and self._publish_revision_is_current(result)
            ):
                # M6a-9: a durably committed tree publish is authoritative even
                # when the worker exceeded its operation age budget.  The tree
                # was published in one transaction and the committed revision
                # still matches the repository, so acknowledge the completion
                # directly; only uncommitted/unpublished late results remain
                # subject to the age deadline.
                return self._apply_publish_result(task, result, completion_timestamp)
            deadline_conflict = ReconciliationQueuePersistenceConflict(
                "Reconciliation task exceeded its worker operation age budget",
                stale_worker_completion=True,
                operation="completion",
            )
            stale = self._stale_completion_noop(
                task,
                deadline_conflict,
                now=completion_timestamp,
                operation_deadline=renew_until,
            )
            if stale is not None:
                return stale
            raise ReconciliationQueuePersistenceError(
                "Reconciliation task exceeded its worker operation age budget"
            ) from deadline_conflict

        if heartbeat_errors:
            renewal_error = heartbeat_errors[0]
            if isinstance(renewal_error, ReconciliationQueuePersistenceConflict):
                stale = self._stale_completion_noop(
                    task,
                    renewal_error,
                    now=completion_timestamp,
                )
                if stale is not None:
                    return stale
            raise ReconciliationQueuePersistenceError(
                "Reconciliation task lease renewal failed"
            ) from renewal_error

        if operation_error is not None:
            if operation_is_terminal:
                return self._terminal(task, operation_error, completion_timestamp)
            assert operation_reason is not None
            return self._retry(task, operation_reason, operation_error, completion_timestamp)

        if is_projection_repair:
            return self._apply_repair_success(task, completion_timestamp)

        assert result is not None
        return self._apply_publish_result(task, result, completion_timestamp)

    def _lease_heartbeat(
        self,
        task: ReconciliationTask,
        lease_seconds: float,
        renew_until: float,
        heartbeat_stop: threading.Event,
        worker_stop: threading.Event | None,
        errors: list[BaseException],
    ) -> None:
        """Renew a claimed lease while a potentially long scan is running.

        Renewal is capped at ``renew_until + lease_seconds`` (the operation
        age budget plus one lease window): a stuck worker (e.g. a network
        drive hang) stops renewing, its lease expires, and the periodic
        sweeper (or any next claimer) can reclaim the task.  Scans that
        finish within the cap still acknowledge their durable completion
        through the queue's lease CAS; tasks that exceed it are idempotent
        and get re-scanned.  ``renew_until`` keeps guarding *uncommitted*
        late completions in :meth:`_process_once_attempt`.
        """
        interval = max(min(lease_seconds / 3.0, 5.0), 0.01)
        renewal_deadline = renew_until + lease_seconds
        while not heartbeat_stop.wait(interval):
            if worker_stop is not None and worker_stop.is_set():
                return
            if self._clock() >= renewal_deadline:
                return
            try:
                self.reconciliation_queue.renew_lease(
                    task.task_id,
                    expected_attempts=task.attempts,
                    lease_token=task.lease_token,
                    lease_seconds=lease_seconds,
                    now=self._clock(),
                )
            except BaseException as exc:
                if heartbeat_stop.is_set() or (
                    worker_stop is not None and worker_stop.is_set()
                ):
                    return
                errors.append(exc)
                return

    @staticmethod
    def _is_retryable_persistence_conflict(
        conflict: ReconciliationQueuePersistenceConflict,
    ) -> bool:
        """Retry only conflicts with explicit retry metadata."""
        return (
            getattr(conflict, "retryable", False) is True
            or getattr(conflict, "retry_after_refresh", False) is True
        )

    def _refresh_after_persistence_conflict(
        self,
        conflict: ReconciliationQueuePersistenceConflict,
    ) -> None:
        """Refresh durable queue state, failing closed when unsupported."""
        queue = self.reconciliation_queue
        try:
            refresh = getattr(queue, "refresh", None) or getattr(queue, "reload", None)
            if callable(refresh):
                result = refresh()
                if result is not None:
                    self._apply_queue_refresh_result(result)
                return

            store = getattr(queue, "persistence_store", None)
            if store is None:
                store = getattr(queue, "_store", None)
            loader = getattr(store, "load_snapshot", None)
            if callable(loader):
                self._apply_queue_refresh_result(loader())
                return
            loader = getattr(store, "load", None)
            if callable(loader):
                self._apply_queue_refresh_result(loader())
                return
            loader = getattr(queue, "_load", None)
            if callable(loader):
                loader()
                return
            raise RuntimeError("queue exposes no durable refresh protocol")
        except BaseException as refresh_error:
            try:
                conflict.add_note(
                    "Queue refresh after persistence conflict failed: "
                    f"{type(refresh_error).__name__}: {refresh_error}"
                )
            except (AttributeError, TypeError):
                pass
            raise ReconciliationQueuePersistenceError(
                "Cannot refresh reconciliation queue after persistence conflict"
            ) from refresh_error

    def _apply_queue_refresh_result(self, result: object) -> None:
        setter = getattr(self.reconciliation_queue, "_set_store_snapshot_unlocked", None)
        if not callable(setter) or not hasattr(result, "tasks") or not hasattr(result, "generation"):
            return
        lock = getattr(self.reconciliation_queue, "_lock", None)
        if lock is None:
            setter(result)
        else:
            with lock:
                setter(result)

    def _publish_revision_is_current(
        self,
        result: AssetIndexPublishResult,
    ) -> bool:
        """Verify a committed publish's revision against the repository.

        A late, durably committed publish may only be acknowledged when the
        revision it advanced is still the root's current revision; if the
        publish did not actually land (or the repository cannot be read), the
        completion must not be acknowledged as the latest state.  A result
        whose revision is newer than the repository is treated as superseded
        and is also not acknowledged; an equal-or-fresher repository state
        still satisfies the repair.
        """
        if result.revision is None:
            return True
        try:
            with self.session.operation():
                conn = self.session.connection_for(self.session.root)
                current = self.asset_index_service.current_revision(
                    conn, self.session.root
                )
        except BaseException:
            return False
        return current >= result.revision

    def _stale_completion_noop(
        self,
        task: ReconciliationTask,
        conflict: ReconciliationQueuePersistenceConflict,
        *,
        now: float | None = None,
        operation_deadline: float | None = None,
    ) -> ReconciliationAttemptResult | None:
        if getattr(conflict, "stale_worker_completion", False) is not True:
            return None
        self._refresh_after_persistence_conflict(conflict)
        current = self.reconciliation_queue.get(task.task_id)
        if current is None:
            raise ReconciliationQueuePersistenceError(
                f"Cannot verify stale completion for missing task {task.task_id}"
            )
        if (
            current.state
            in {
                ReconciliationState.SUCCEEDED,
                ReconciliationState.TERMINAL,
                ReconciliationState.CANCELLED,
            }
            or current.attempts != task.attempts
            or current.state in {
                ReconciliationState.PENDING,
                ReconciliationState.RETRYABLE,
            }
            or (
                operation_deadline is not None
                and now is not None
                and now >= operation_deadline
            )
            or (
                current.state is ReconciliationState.RUNNING
                and (
                    current.lease_expires_at is None
                    or (now is not None and current.lease_expires_at <= now)
                )
            )
        ):
            return ReconciliationAttemptResult(
                task=current,
                state=current.state,
                error_type="StaleWorkerCompletion",
                error=str(conflict),
            )
        return None

    def process_available(
        self,
        *,
        limit: int = 1,
        now: float | None = None,
        lease_seconds: float = 30.0,
    ) -> tuple[ReconciliationAttemptResult, ...]:
        """Process at most ``limit`` due tasks without sleeping."""
        if limit < 1:
            raise ValueError("limit must be positive")
        timestamp = self._clock() if now is None else now
        results: list[ReconciliationAttemptResult] = []
        for _ in range(limit):
            result = self.process_once(now=timestamp, lease_seconds=lease_seconds)
            if result is None:
                break
            results.append(result)
        return tuple(results)

    def _apply_repair_success(
        self,
        task: ReconciliationTask,
        timestamp: float,
    ) -> ReconciliationAttemptResult:
        try:
            completed = self.reconciliation_queue.mark_succeeded(
                task.task_id,
                expected_attempts=task.attempts,
                lease_token=task.lease_token,
                revision=None,
                now=timestamp,
            )
        except ReconciliationQueuePersistenceConflict as conflict:
            stale = self._stale_completion_noop(task, conflict, now=timestamp)
            if stale is not None:
                return stale
            raise
        self._acknowledge_import_recovery(completed)
        return ReconciliationAttemptResult(task=completed, state=completed.state)

    def _apply_publish_result(
        self,
        task: ReconciliationTask,
        result: AssetIndexPublishResult,
        timestamp: float,
    ) -> ReconciliationAttemptResult:
        if result.published and result.committed is True:
            try:
                completed = self.reconciliation_queue.mark_succeeded(
                    task.task_id,
                    expected_attempts=task.attempts,
                    lease_token=task.lease_token,
                    revision=result.revision,
                    now=timestamp,
                )
            except ReconciliationQueuePersistenceConflict as conflict:
                stale = self._stale_completion_noop(task, conflict, now=timestamp)
                if stale is not None:
                    return ReconciliationAttemptResult(
                        task=stale.task,
                        state=stale.state,
                        publish_result=result,
                        error_type=stale.error_type,
                        error=stale.error,
                    )
                raise
            self._acknowledge_import_recovery(completed)
            return ReconciliationAttemptResult(
                task=completed,
                state=completed.state,
                publish_result=result,
            )

        status = result.status
        if status is AssetIndexPublishStatus.BUSY:
            reason = "busy"
        elif status is AssetIndexPublishStatus.STALE:
            reason = "stale"
        elif status is AssetIndexPublishStatus.SCAN_FAILED:
            reason = "scan_failed"
        elif result.published and result.committed is False:
            reason = "staged"
        else:
            return self._terminal(
                task,
                result.failure or RuntimeError(f"unsupported publish status: {status.value}"),
                timestamp,
                publish_result=result,
            )

        failure = result.failure
        try:
            next_task = self.reconciliation_queue.mark_retryable(
                task.task_id,
                expected_attempts=task.attempts,
                lease_token=task.lease_token,
                error_type=type(failure).__name__ if failure is not None else status.value,
                error=str(failure) if failure is not None else status.value,
                reason=reason,
                now=timestamp,
            )
        except ReconciliationQueuePersistenceConflict as conflict:
            stale = self._stale_completion_noop(task, conflict, now=timestamp)
            if stale is not None:
                return ReconciliationAttemptResult(
                    task=stale.task,
                    state=stale.state,
                    publish_result=result,
                    error_type=stale.error_type,
                    error=stale.error,
                )
            raise
        return ReconciliationAttemptResult(
            task=next_task,
            state=next_task.state,
            publish_result=result,
            error_type=next_task.last_error_type,
            error=next_task.last_error,
        )

    def _acknowledge_import_recovery(self, task: ReconciliationTask) -> None:
        """Notify the manifest store only after queue success is durable."""
        if self._durable_transition_outbox_owns_manifest_recovery():
            # The queue's post-commit outbox dispatcher invokes the manifest
            # listener and receives its explicit acknowledgement disposition.
            # Bypassing it here could complete a manifest while the durable
            # transition remains pending.
            return
        callback = self.import_manifest_recovery
        acknowledge = getattr(callback, "acknowledge_task", None)
        if not callable(acknowledge):
            return
        try:
            acknowledge(task)
        except Exception:
            # Queue success is already committed; an ACK write can safely be
            # retried on the next startup/recovery pass.  Never turn a durable
            # queue success into a worker failure solely because bookkeeping
            # notification was temporarily unavailable.
            pass

    def _mark_import_recovery_running(self, task: ReconciliationTask) -> None:
        if self._durable_transition_outbox_owns_manifest_recovery():
            return
        callback = self.import_manifest_recovery
        mark_running = getattr(callback, "mark_task_running", None)
        if not callable(mark_running):
            return
        try:
            mark_running(task)
        except Exception:
            # Visibility is advisory; the queue lease/state remains the
            # authoritative owner and can be reconciled at the next startup.
            pass

    def _durable_transition_outbox_owns_manifest_recovery(self) -> bool:
        """Whether queue transitions, rather than worker callbacks, own ACKs."""
        enabled = getattr(
            self.reconciliation_queue,
            "durable_transition_outbox_enabled",
            False,
        )
        try:
            return bool(enabled() if callable(enabled) else enabled)
        except Exception:
            return False

    def _retry(
        self,
        task: ReconciliationTask,
        reason: str,
        error: BaseException,
        timestamp: float,
    ) -> ReconciliationAttemptResult:
        try:
            next_task = self.reconciliation_queue.mark_retryable(
                task.task_id,
                expected_attempts=task.attempts,
                lease_token=task.lease_token,
                error_type=type(error).__name__,
                error=str(error),
                reason=reason,
                now=timestamp,
            )
        except ReconciliationQueuePersistenceConflict as conflict:
            stale = self._stale_completion_noop(task, conflict, now=timestamp)
            if stale is not None:
                return stale
            raise
        # Preserve the actual failure class in the result while keeping the
        # task's dedupe identity stable.
        return ReconciliationAttemptResult(
            task=next_task,
            state=next_task.state,
            error_type=type(error).__name__,
            error=str(error),
        )

    def _terminal(
        self,
        task: ReconciliationTask,
        error: BaseException,
        timestamp: float,
        *,
        publish_result: AssetIndexPublishResult | None = None,
    ) -> ReconciliationAttemptResult:
        try:
            terminal = self.reconciliation_queue.mark_terminal(
                task.task_id,
                expected_attempts=task.attempts,
                lease_token=task.lease_token,
                error_type=type(error).__name__,
                error=str(error),
                now=timestamp,
            )
        except ReconciliationQueuePersistenceConflict as conflict:
            stale = self._stale_completion_noop(task, conflict, now=timestamp)
            if stale is not None:
                return stale
            raise
        return ReconciliationAttemptResult(
            task=terminal,
            state=terminal.state,
            publish_result=publish_result,
            error_type=type(error).__name__,
            error=str(error),
        )
