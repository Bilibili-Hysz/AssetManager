"""Session-bound database integrity and orphan maintenance checks."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import logging
from pathlib import Path
import sqlite3
import threading
import time

from AssetsManager.application.context import ConnectionProvider, LibrarySession
from AssetsManager.application.thumbnail_cache_lifecycle import (
    artifact_path,
    cache_owner_lock,
)
from AssetsManager.core.database import DatabaseManager, db_write_lock
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import MaintenanceChanged

_log = logging.getLogger(__name__)


class _IntegrityCheckCancelled(RuntimeError):
    """Internal signal used when a Runtime closes an in-flight check."""


class _QuickCheckBusy(RuntimeError):
    """Raised when quick_check could not run because the database stayed busy.

    A busy/locked database is a transient, retryable condition rather than
    evidence of corruption, so callers record it as a warning instead of
    marking the library unhealthy.
    """


_BUSY_PHRASES = ("database is locked", "database table is locked")
# quick_check runs immediately and then gets up to _BUSY_MAX_ATTEMPTS - 1
# retries with exponentially increasing delays when the database is busy.
_BUSY_MAX_ATTEMPTS = 3
_BUSY_RETRY_BASE_DELAY = 0.25
# Pure-SQL delete batch size. Filesystem revalidation runs before the write
# lock is taken, so the lock is never held during slow stat calls.
_DELETE_BATCH_SIZE = 500


def _is_busy_error(exc: BaseException) -> bool:
    """Return whether a SQLite error is a transient busy/locked condition."""
    message = str(exc).lower()
    return any(phrase in message for phrase in _BUSY_PHRASES)


class PathExistence(Enum):
    """Conservative result of checking a library-managed filesystem path."""

    EXISTS = "exists"
    MISSING = "missing"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class IntegrityCheckReport:
    """Result of one library maintenance pass."""

    checked_at: float
    duration_ms: float
    quick_check: str
    metadata_removed: int = 0
    thumbnail_metadata_removed: int = 0
    thumbnail_files_removed: int = 0
    issues: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def healthy(self) -> bool:
        return self.quick_check == "ok" and not self.issues


class DatabaseIntegrityService:
    """Run conservative integrity maintenance for one live library session.

    The slow read-only and filesystem portions do not hold a session operation
    lease. Database reads and writes use short leases, and every destructive
    delete is revalidated before the connection write lock is taken; the lock
    itself only guards fast batched SQL deletes. The service never deletes
    user files; malformed or out-of-root thumbnail keys are metadata-only
    cleanup candidates and their baked files are skipped.
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
        self._active_runs = 0
        self._run_done = threading.Event()
        self._run_done.set()
        self._cancel_event = threading.Event()
        self._connection_lock = threading.Lock()
        self._active_connection: sqlite3.Connection | None = None
        self._last_report: IntegrityCheckReport | None = None
        self._last_schedule_error: str | None = None
        self._run_issues: list[str] | None = None
        self._run_issue_seen: set[str] | None = None

    def _connection(self) -> sqlite3.Connection:
        root = self._session.root
        conn = self._connection_provider(root)
        return DatabaseManager.validate_connection_owner(root, conn, allow_unmanaged=True)

    @property
    def last_report(self) -> IntegrityCheckReport | None:
        with self._state_lock:
            return self._last_report

    @property
    def last_schedule_error(self) -> str | None:
        with self._state_lock:
            return self._last_schedule_error

    @property
    def running(self) -> bool:
        with self._state_lock:
            return self._running

    def run(self) -> IntegrityCheckReport:
        """Run one integrity pass and return its report."""
        with self._state_lock:
            if self._closed:
                self._last_schedule_error = "service_closed"
                return IntegrityCheckReport(
                    checked_at=time.time(),
                    duration_ms=0.0,
                    quick_check="error",
                    issues=("service_closed",),
                )
        self._begin_run()
        try:
            return self._run_pass()
        finally:
            self._finish_run()

    def _begin_run(self) -> None:
        with self._state_lock:
            self._active_runs += 1
            self._run_done.clear()

    def _finish_run(self) -> None:
        with self._state_lock:
            self._active_runs -= 1
            if self._active_runs == 0:
                self._run_done.set()

    def _run_pass(self) -> IntegrityCheckReport:
        started = time.perf_counter()
        quick_check = "error"
        metadata_removed = 0
        thumbnail_metadata_removed = 0
        thumbnail_files_removed = 0
        issues: list[str] = []
        warnings: list[str] = []
        self._run_issues = issues

        try:
            if self._session.is_closed:
                raise RuntimeError("Cannot use a closed LibrarySession")
            quick_check = self._quick_check()
            if quick_check != "ok":
                issues.append(f"SQLite quick_check returned: {quick_check}")
            else:
                metadata_removed = self._prune_missing_metadata()
                (
                    thumbnail_metadata_removed,
                    thumbnail_files_removed,
                ) = self._prune_thumbnail_orphans()
        except _IntegrityCheckCancelled:
            quick_check = "cancelled" if quick_check == "error" else quick_check
            issues.append("Integrity check cancelled during session shutdown")
        except _QuickCheckBusy as exc:
            # The database stayed locked for the whole retry window. That is a
            # transient, retryable condition rather than evidence of corruption:
            # record a warning and stay healthy so the next pass retries.
            quick_check = "ok"
            message = f"SQLite quick_check busy; retryable, will retry next pass: {exc}"
            warnings.append(message)
            _log.warning("Library integrity quick_check busy for %s: %s", self._session.root, exc)
        except Exception as exc:
            _log.exception("Library integrity check failed for %s", self._session.root)
            issues.append(f"{type(exc).__name__}: {exc}")

        report = IntegrityCheckReport(
            checked_at=time.time(),
            duration_ms=(time.perf_counter() - started) * 1000.0,
            quick_check=quick_check,
            metadata_removed=metadata_removed,
            thumbnail_metadata_removed=thumbnail_metadata_removed,
            thumbnail_files_removed=thumbnail_files_removed,
            issues=tuple(issues),
            warnings=tuple(warnings),
        )
        with self._state_lock:
            self._last_report = report
        self._run_issues = None
        self._run_issue_seen = None
        if report.healthy:
            _log.info(
                "Library integrity check passed for %s (%.1f ms; metadata=%d, thumbnails=%d)",
                self._session.root,
                report.duration_ms,
                report.metadata_removed,
                report.thumbnail_metadata_removed,
            )
        else:
            _log.warning(
                "Library integrity check reported issues for %s: %s",
                self._session.root,
                "; ".join(report.issues) or report.quick_check,
            )
        return report

    def schedule(self) -> bool:
        """Start one daemon maintenance pass without blocking the UI thread."""
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
            self._active_runs += 1
            self._run_done.clear()

        worker = threading.Thread(
            target=self._run_scheduled,
            name="AssetsManager-IntegrityCheck",
            daemon=True,
        )
        try:
            worker.start()
        except Exception as exc:
            failure = IntegrityCheckReport(
                checked_at=time.time(),
                duration_ms=0.0,
                quick_check="error",
                issues=(f"{type(exc).__name__}: {exc}",),
            )
            with self._state_lock:
                self._running = False
                self._active_runs -= 1
                self._last_report = failure
                self._last_schedule_error = (
                    f"worker_start_failed: {type(exc).__name__}: {exc}"
                )
                if self._active_runs == 0:
                    self._run_done.set()
            _log.exception("Failed to start library integrity check worker")
            return False
        return True

    def stop(self) -> None:
        """Cancel an in-flight pass during Runtime/session shutdown."""
        with self._state_lock:
            self._closed = True
        self._cancel_event.set()
        with self._connection_lock:
            active_connection = self._active_connection
        if active_connection is not None:
            try:
                active_connection.interrupt()
            except Exception:
                _log.debug("Integrity quick_check interrupt skipped", exc_info=True)
        if not self._run_done.wait(timeout=10.0):
            _log.warning(
                "Library integrity check still draining for %s; "
                "background cleanup will finish without blocking session close",
                self._session.root,
            )
        with self._connection_lock:
            if self._active_connection is not None:
                _log.warning(
                    "Library integrity check connection still active for %s",
                    self._session.root,
                )

    def _run_scheduled(self) -> None:
        try:
            self.run()
            self._publish_completed()
        finally:
            with self._state_lock:
                # A completed run supersedes any stale scheduling error (for
                # example "already_running" recorded by a concurrent call);
                # runtime failures surface through the report/issues instead.
                self._last_schedule_error = None
                self._running = False
                self._active_runs -= 1
                if self._active_runs == 0:
                    self._run_done.set()

    def _publish_completed(self) -> None:
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
                kind="integrity",
            ))
        except Exception:
            _log.exception("Integrity check completion notification failed")

    def _check_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise _IntegrityCheckCancelled

    def _commit_while_live(self, conn: sqlite3.Connection) -> None:
        def commit() -> None:
            self._check_cancelled()
            conn.commit()

        self._session._publish_while_live(commit)

    def _quick_check(self) -> str:
        self._check_cancelled()
        database_file = self._session.data_dir / "assetmanager.db"
        if not database_file.is_file():
            raise FileNotFoundError(database_file)
        conn = sqlite3.connect(str(database_file), check_same_thread=False)
        with self._connection_lock:
            self._active_connection = conn
        try:
            conn.execute("PRAGMA busy_timeout=500")
            values: tuple[str, ...] | None = None
            delay = _BUSY_RETRY_BASE_DELAY
            for attempt in range(_BUSY_MAX_ATTEMPTS):
                self._check_cancelled()
                try:
                    values = tuple(
                        str(row[0])
                        for row in conn.execute("PRAGMA quick_check").fetchall()
                    )
                    break
                except sqlite3.OperationalError as exc:
                    if self._cancel_event.is_set():
                        raise _IntegrityCheckCancelled from exc
                    if not _is_busy_error(exc):
                        raise
                    if attempt == _BUSY_MAX_ATTEMPTS - 1:
                        raise _QuickCheckBusy(str(exc)) from exc
                    _log.warning(
                        "SQLite quick_check busy for %s (attempt %d/%d); retrying",
                        self._session.root,
                        attempt + 1,
                        _BUSY_MAX_ATTEMPTS,
                    )
                    time.sleep(delay)
                    delay *= 2
            if values is None:  # pragma: no cover - all attempts raised above
                raise _QuickCheckBusy("database is locked")
            self._check_cancelled()
            return "; ".join(values) or "error"
        except sqlite3.OperationalError:
            if self._cancel_event.is_set():
                # Cancellation is a deliberate alternate outcome, not a bug
                # caused by the lock, so drop the OperationalError chain.
                raise _IntegrityCheckCancelled from None
            raise
        finally:
            with self._connection_lock:
                if self._active_connection is conn:
                    self._active_connection = None
            conn.close()

    def _prune_missing_metadata(self) -> int:
        self._check_cancelled()
        with self._session.operation():
            conn = self._connection()
            rows = conn.execute("SELECT file_path FROM file_meta").fetchall()
        missing = []
        for (file_path,) in rows:
            self._check_cancelled()
            if self._path_existence(file_path) is PathExistence.MISSING:
                missing.append(str(file_path))
        if not missing:
            return 0

        # Revalidate every candidate before taking the write lock: the
        # filesystem stat loop must never run while the lock is held.
        confirmed = []
        for path in missing:
            self._check_cancelled()
            if self._path_existence(path) is PathExistence.MISSING:
                confirmed.append(path)
        if not confirmed:
            return 0

        self._check_cancelled()
        removed = 0
        with self._session.operation():
            conn = self._connection()
            with db_write_lock(conn):
                try:
                    for start in range(0, len(confirmed), _DELETE_BATCH_SIZE):
                        batch = confirmed[start : start + _DELETE_BATCH_SIZE]
                        self._check_cancelled()
                        placeholders = ", ".join("?" for _ in batch)
                        cursor = conn.execute(
                            "DELETE FROM file_meta WHERE file_path IN "
                            f"({placeholders})",
                            batch,
                        )
                        removed += max(cursor.rowcount, 0)
                    self._commit_while_live(conn)
                except BaseException:
                    conn.rollback()
                    raise
        return removed

    def _prune_thumbnail_orphans(self) -> tuple[int, int]:
        self._check_cancelled()
        with self._session.operation():
            conn = self._connection()
            rows = conn.execute(
                "SELECT cache_key, source_path FROM thumbnail_cache"
            ).fetchall()
        orphaned = []
        for cache_key, source_path in rows:
            self._check_cancelled()
            if self._path_existence(source_path) is PathExistence.MISSING:
                orphaned.append((str(cache_key), str(source_path)))

        # Revalidate every candidate before taking the write lock: the
        # filesystem stat loop must never run while the lock is held.
        confirmed = []
        for cache_key, source_path in orphaned:
            self._check_cancelled()
            if self._path_existence(source_path) is PathExistence.MISSING:
                confirmed.append((cache_key, source_path))

        thumb_dir = self._session.thumb_dir.resolve()
        self._check_cancelled()
        metadata_removed = 0
        files_removed = 0
        try:
            with cache_owner_lock(thumb_dir):
                with self._session.operation():
                    conn = self._connection()
                    if confirmed:
                        with db_write_lock(conn):
                            try:
                                for start in range(0, len(confirmed), _DELETE_BATCH_SIZE):
                                    batch = confirmed[start : start + _DELETE_BATCH_SIZE]
                                    self._check_cancelled()
                                    placeholders = ", ".join("(?, ?)" for _ in batch)
                                    cursor = conn.execute(
                                        "DELETE FROM thumbnail_cache WHERE "
                                        f"(cache_key, source_path) IN ({placeholders})",
                                        tuple(item for pair in batch for item in pair),
                                    )
                                    metadata_removed += max(cursor.rowcount, 0)
                                self._commit_while_live(conn)
                            except BaseException:
                                conn.rollback()
                                raise
                    known_artifacts = {
                        (str(row[0]), str(row[1] or "webp"))
                        for row in conn.execute(
                            "SELECT cache_key, artifact_kind FROM thumbnail_cache"
                        ).fetchall()
                    }
                    if thumb_dir.is_dir():
                        try:
                            baked_files = tuple(thumb_dir.iterdir())
                        except OSError:
                            baked_files = ()
                        for baked_path in sorted(
                            baked_files, key=lambda path: path.name.casefold()
                        ):
                            self._check_cancelled()
                            suffix = baked_path.suffix.lower().lstrip(".")
                            if suffix not in {"webp", "jpg"} or not baked_path.is_file():
                                continue
                            key = baked_path.stem
                            if (key, suffix) in known_artifacts:
                                continue
                            safe_path = artifact_path(thumb_dir, key, suffix)
                            if safe_path is None:
                                continue
                            try:
                                safe_path.unlink()
                                files_removed += 1
                            except (OSError, ValueError):
                                _log.warning("Failed to remove orphan thumbnail: %s", safe_path)
                                issues = self._run_issues
                                if issues is not None:
                                    message = (
                                        f"Failed to remove orphan thumbnail file; "
                                        f"retry next pass: {safe_path}"
                                    )
                                    if message not in issues:
                                        issues.append(message)
        except TimeoutError:
            _log.warning("Thumbnail cache owner busy during integrity scan")
        return metadata_removed, files_removed

    @staticmethod
    def _safe_thumbnail_path(thumb_dir: Path, cache_key: str) -> Path | None:
        try:
            baked_path = (thumb_dir / f"{cache_key}.webp").resolve()
            if baked_path.parent != thumb_dir:
                _log.warning("Skipping unsafe thumbnail cache key: %s", cache_key)
                return None
            return baked_path
        except (OSError, ValueError, RuntimeError):
            _log.warning("Skipping malformed thumbnail cache key: %s", cache_key)
            return None

    def _path_existence(self, path: object) -> PathExistence:
        """Normalize path checks so only a confirmed missing path is deletable."""
        try:
            result = self._exists(path)
        except (OSError, RuntimeError, ValueError, TypeError):
            result = PathExistence.UNKNOWN
        if isinstance(result, PathExistence):
            state = result
        elif isinstance(result, bool):
            # Keep old test/plugin seams source-compatible while the production
            # implementation exposes the stricter three-state contract.
            state = PathExistence.EXISTS if result else PathExistence.MISSING
        else:
            state = PathExistence.UNKNOWN
        if state is PathExistence.UNKNOWN:
            self._record_unknown_path(path)
        return state

    def _record_unknown_path(self, path: object) -> None:
        issues = self._run_issues
        if issues is not None:
            message = f"Filesystem path state is unknown; skipped cleanup: {path!r}"
            seen = self._run_issue_seen
            if seen is None:
                seen = set()
                self._run_issue_seen = seen
            if message not in seen:
                seen.add(message)
                issues.append(message)

    def _exists(self, path: object) -> PathExistence:
        """Return UNKNOWN for malformed, inaccessible, or out-of-root paths."""
        try:
            candidate = Path(str(path))
            root = self._session.root.resolve()
            if not candidate.is_absolute():
                candidate = root / candidate
            resolved = candidate.resolve(strict=False)
            try:
                resolved.relative_to(root)
            except ValueError:
                return PathExistence.UNKNOWN
            if not resolved.parent.is_dir():
                return PathExistence.UNKNOWN
            return (
                PathExistence.EXISTS
                if resolved.is_file() or resolved.is_dir()
                else PathExistence.MISSING
            )
        except (OSError, RuntimeError, ValueError, TypeError):
            return PathExistence.UNKNOWN
