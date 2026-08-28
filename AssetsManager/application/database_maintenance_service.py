"""Small, session-bound database maintenance operations.

This service deliberately covers only operations whose lifetime and locking
semantics are clear with the current database architecture. VACUUM is
reported as unsupported until the application owns an explicit maintenance
window for it.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import logging
from pathlib import Path
import sqlite3
import threading
from typing import Literal, cast

from AssetsManager.application.context import ConnectionProvider, LibrarySession
from AssetsManager.core.database import DatabaseManager, db_write_lock
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import MaintenanceChanged

_log = logging.getLogger(__name__)
CheckpointMode = Literal["PASSIVE", "FULL", "RESTART", "TRUNCATE"]
_CHECKPOINT_MODES = frozenset({"PASSIVE", "FULL", "RESTART", "TRUNCATE"})


@dataclass(frozen=True)
class DatabaseSizeResult:
    """Result of reading the live SQLite database file size."""

    database_path: Path
    size_bytes: int


@dataclass(frozen=True)
class WalCheckpointResult:
    """SQLite WAL checkpoint outcome: busy, log frames, checkpointed frames."""

    mode: CheckpointMode
    busy: int
    log_frames: int
    checkpointed_frames: int
    success: bool = True
    error: str | None = None


@dataclass(frozen=True)
class VacuumResult:
    """Explicit VACUUM boundary for the current runtime architecture."""

    supported: bool = False
    success: bool = False
    reason: str = (
        "VACUUM is not enabled: its exclusive/long-running lock and session "
        "lifecycle window are not yet owned by an application maintenance coordinator."
    )

    @property
    def error(self) -> str:
        """Expose the unsupported boundary through the common result surface."""
        return self.reason


@dataclass(frozen=True)
class MaintenanceFailureResult:
    """Failure captured by a background maintenance operation."""

    operation: Literal["size", "checkpoint", "vacuum"]
    error: str
    cancelled: bool = False
    success: bool = False


class DatabaseMaintenanceService:
    """Run bounded database maintenance for one live ``LibrarySession``.

    Size reads use the filesystem only. Checkpoints use the session-owned
    connection under a short operation lease and the existing write lock;
    ``busy_timeout`` bounds lock waiting. No public method assumes a UI
    thread, and ``schedule`` runs the selected operation on a daemon worker.
    """

    def __init__(
        self,
        *,
        connection_provider: ConnectionProvider,
        session: LibrarySession,
    ) -> None:
        self._connection_provider = connection_provider
        self._session = session
        self._state_lock = threading.Lock()
        self._running = False
        self._closed = False
        self._cancel_event = threading.Event()
        self._done = threading.Event()
        self._done.set()
        self._active_connection: sqlite3.Connection | None = None
        self._last_result: object | None = None
        self._last_schedule_error: str | None = None

    def _connection(self) -> sqlite3.Connection:
        root = self._session.root
        conn = self._connection_provider(root)
        return DatabaseManager.validate_connection_owner(root, conn, allow_unmanaged=True)

    @property
    def running(self) -> bool:
        with self._state_lock:
            return self._running

    @property
    def last_result(self) -> object | None:
        with self._state_lock:
            return self._last_result

    @property
    def last_schedule_error(self) -> str | None:
        with self._state_lock:
            return self._last_schedule_error

    def database_size(self) -> DatabaseSizeResult:
        """Return the size of the library's SQLite database file."""
        database_file = self._database_path()
        return DatabaseSizeResult(
            database_path=database_file,
            size_bytes=database_file.stat().st_size,
        )

    def checkpoint(self, mode: str = "PASSIVE") -> WalCheckpointResult:
        """Run a bounded WAL checkpoint and return SQLite's three counters."""
        self._ensure_live_session()
        checkpoint_mode = self._normalize_checkpoint_mode(mode)
        self._check_cancelled()
        with self._session.operation():
            conn = self._connection()
            with self._connection_lock(conn):
                try:
                    with self._temporary_busy_timeout(conn):
                        with db_write_lock(conn):
                            row = conn.execute(
                                f"PRAGMA wal_checkpoint({checkpoint_mode})"
                            ).fetchone()
                        self._check_cancelled()
                except sqlite3.Error as exc:
                    if self._cancel_event.is_set():
                        raise RuntimeError("Database maintenance cancelled") from exc
                    _log.warning("WAL checkpoint failed for %s: %s", self._session.root, exc)
                    return WalCheckpointResult(
                        mode=checkpoint_mode,
                        busy=-1,
                        log_frames=-1,
                        checkpointed_frames=-1,
                        success=False,
                        error=str(exc),
                    )
        if row is None or len(row) != 3:
            return WalCheckpointResult(
                mode=checkpoint_mode,
                busy=-1,
                log_frames=-1,
                checkpointed_frames=-1,
                success=False,
                error="SQLite returned an invalid wal_checkpoint result",
            )
        busy, log_frames, checkpointed_frames = (int(value) for value in row)
        success = checkpoint_mode == "PASSIVE" or busy == 0
        return WalCheckpointResult(
            mode=checkpoint_mode,
            busy=busy,
            log_frames=log_frames,
            checkpointed_frames=checkpointed_frames,
            success=success,
            error=None if success else "WAL checkpoint is busy",
        )

    def vacuum(self) -> VacuumResult:
        """Return the explicit safety boundary; do not guess VACUUM semantics."""
        self._ensure_live_session()
        return VacuumResult()

    def schedule(
        self,
        operation: Literal["size", "checkpoint", "vacuum"] = "checkpoint",
        *,
        mode: str = "PASSIVE",
    ) -> bool:
        """Run one maintenance operation in a daemon thread without blocking UI.

        VACUUM is rejected at this boundary without starting a worker: the
        return value is ``False`` and ``last_schedule_error`` is
        ``"vacuum_not_supported"``.
        """
        if operation == "vacuum":
            # VACUUM has no owned maintenance window in the current
            # architecture; a worker could only ever produce an unsupported
            # result, so refuse the schedule instead of starting one.
            with self._state_lock:
                self._last_schedule_error = "vacuum_not_supported"
            return False
        if operation not in {"size", "checkpoint"}:
            raise ValueError(f"Unsupported database maintenance operation: {operation}")
        if operation == "checkpoint":
            # Reject bad input synchronously; a successful schedule call must
            # always represent a worker that has a valid operation to run.
            self._normalize_checkpoint_mode(mode)
        try:
            self._ensure_live_session()
        except RuntimeError:
            with self._state_lock:
                # Record the refusal in every case: a dead session and a
                # stopped service have distinct causes and feedback strings.
                self._last_schedule_error = (
                    "service_closed" if self._closed else "session_closed"
                )
            raise
        with self._state_lock:
            if self._running:
                self._last_schedule_error = "already_running"
                return False
            if self._closed:
                self._last_schedule_error = "service_closed"
                return False
            self._last_schedule_error = None
            self._running = True
            self._cancel_event.clear()
            self._done.clear()
        worker = threading.Thread(
            target=self._run_scheduled,
            args=(operation, mode),
            name="AssetsManager-DatabaseMaintenance",
            daemon=True,
        )
        try:
            worker.start()
        except Exception as exc:
            failure = MaintenanceFailureResult(
                operation=operation,
                error=f"{type(exc).__name__}: {exc}",
            )
            with self._state_lock:
                self._running = False
                self._last_result = failure
                self._last_schedule_error = (
                    f"worker_start_failed: {type(exc).__name__}: {exc}"
                )
                self._done.set()
            _log.exception("Failed to start database maintenance worker")
            return False
        return True

    def stop(self) -> None:
        """Request cancellation and interrupt an active SQLite checkpoint."""
        with self._state_lock:
            self._closed = True
        self._cancel_event.set()
        with self._state_lock:
            conn = self._active_connection
        if conn is not None:
            try:
                conn.interrupt()
            except sqlite3.Error:
                _log.debug("Database maintenance interrupt skipped", exc_info=True)
        if not self._done.wait(timeout=10.0):
            _log.warning(
                "Database maintenance still draining for %s; "
                "background cleanup will finish without blocking session close",
                self._session.root,
            )
        with self._state_lock:
            if self._active_connection is not None:
                _log.warning(
                    "Database maintenance connection still active for %s",
                    self._session.root,
                )

    def _run_scheduled(self, operation: Literal["size", "checkpoint", "vacuum"], mode: str) -> None:
        try:
            if operation == "size":
                result: object = self.database_size()
            elif operation == "checkpoint":
                result = self.checkpoint(mode)
            else:
                result = self.vacuum()
            with self._state_lock:
                self._last_result = result
        except Exception as exc:
            cancelled = self._cancel_event.is_set()
            failure = MaintenanceFailureResult(
                operation=operation,
                error=str(exc),
                cancelled=cancelled,
            )
            with self._state_lock:
                self._last_result = failure
            _log.warning("Database maintenance %s failed: %s", operation, exc)
        finally:
            # Publish the completion notification for every finished run —
            # success or failure — so session-level subscribers can observe
            # maintenance settling. UI subscription is tracked as follow-up
            # wiring on top of this server-side event.
            self._publish_completed()
            with self._state_lock:
                self._running = False
                self._active_connection = None
                self._done.set()

    def _publish_completed(self) -> None:
        """Notify event-bus subscribers that a scheduled run has finished.

        Fires once per completed run, on both the success and failure paths.
        """
        token = self._session.event_token
        if not token:
            return
        try:
            # MaintenanceChanged is a UI-notification event, deliberately not
            # projection data: it has no ProjectionDomain mapping in
            # runtime_events.EVENT_DOMAINS, so the RuntimeEventRouter (which
            # only subscribes to mapped types) ignores it.  The one consumer
            # — the settings dialog's queued Qt bridge — subscribes to this
            # type on the bus directly.
            get_event_bus().publish(MaintenanceChanged(
                library_root=self._session.root_str,
                session_token=token,
                kind="maintenance",
            ))
        except Exception:
            _log.exception("Database maintenance completion notification failed")

    @contextmanager
    def _temporary_busy_timeout(self, conn: sqlite3.Connection):
        row = conn.execute("PRAGMA busy_timeout").fetchone()
        if row is None or len(row) != 1:
            raise RuntimeError("SQLite returned an invalid busy_timeout result")
        original_timeout = int(row[0])
        try:
            conn.execute("PRAGMA busy_timeout=500")
            yield
        finally:
            conn.execute(f"PRAGMA busy_timeout={original_timeout}")

    @staticmethod
    def _normalize_checkpoint_mode(mode: str) -> CheckpointMode:
        normalized_mode = mode.upper()
        if normalized_mode not in _CHECKPOINT_MODES:
            raise ValueError(f"Unsupported WAL checkpoint mode: {mode}")
        return cast(CheckpointMode, normalized_mode)

    def _database_path(self) -> Path:
        self._ensure_live_session()
        with self._session.operation():
            database_file = self._session.data_dir / "assetmanager.db"
        if not database_file.is_file():
            raise FileNotFoundError(database_file)
        return database_file

    def _ensure_live_session(self) -> None:
        if self._session.is_closed:
            raise RuntimeError("Cannot use a closed LibrarySession")
        with self._state_lock:
            if self._closed:
                raise RuntimeError("Database maintenance service is closed")

    def _check_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise RuntimeError("Database maintenance cancelled")

    @contextmanager
    def _connection_lock(self, conn: sqlite3.Connection):
        with self._state_lock:
            self._active_connection = conn
        try:
            yield
        finally:
            with self._state_lock:
                if self._active_connection is conn:
                    self._active_connection = None
