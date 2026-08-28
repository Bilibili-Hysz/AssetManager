"""File operation application service."""
from __future__ import annotations

from collections import deque
import errno
import json
import logging
import os
import shutil
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from sqlite3 import Connection, OperationalError
from time import monotonic_ns, perf_counter, time
from typing import TYPE_CHECKING, Mapping
from uuid import uuid4

from AssetsManager.application.context import session_operation
from AssetsManager.core.performance import PerformanceRecorder
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import (
    FileSystemChanged,
    TagCatalogChanged,
)
from AssetsManager.repositories.asset_index_repository import AssetIndexRevisionConflict

if TYPE_CHECKING:
    from AssetsManager.application.asset_index_service import AssetIndexService
    from AssetsManager.application.context import LibrarySession
    from AssetsManager.application.reconciliation_queue import ReconciliationQueue

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FileOperationWarning:
    """Structured non-fatal diagnostic from a projection refresh."""

    code: str
    phase: str
    path: str
    status: str
    retry_count: int = 0
    failure_type: str | None = None
    operation_id: str = ""

    @property
    def message(self) -> str:
        return f"{self.code}: {self.path}"


@dataclass(frozen=True)
class FileOperationResult:
    changed_paths: tuple[Path, ...]
    errors: tuple[str, ...] = ()
    warnings: tuple[FileOperationWarning, ...] = ()
    moved_pairs: tuple[tuple[Path, Path], ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def degraded(self) -> bool:
        return bool(self.warnings)


@dataclass(frozen=True)
class RestoreResult:
    """Outcome of :meth:`FileOperationService.restore_backup`.

    The filesystem restore itself either succeeded (the result is returned)
    or raised; ``degraded`` carries the projection-restore signal: ``True``
    means the file was restored but its projection snapshot (tags, notes,
    favorites) could not be re-applied, so the restore must not be recorded
    as a fully clean success by undo bookkeeping.  ``warnings`` carries the
    structured diagnostics collected on the executing thread.
    """

    path: Path
    degraded: bool = False
    warnings: tuple[FileOperationWarning, ...] = ()


def _assert_under_root(path: Path, root: str | Path | None) -> None:
    """Refuse paths that resolve outside the library root.

    Symlink policy (deliberate, safety-first): ``resolve()`` follows
    symlinks, so a link stored *inside* the library that points *outside*
    it resolves to an external target and is rejected here with ValueError.
    This is by design: moving, deleting, or copying through such a link
    would silently mutate data outside the library.  Callers that need
    link traversal must opt in explicitly — this guard never does.
    """
    if root is not None and not Path(path).resolve().is_relative_to(Path(root)):
        raise ValueError(f'Path {path} is outside library root')


_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}

_MAX_FILENAME_COMPONENT_UNITS = 255


def _windows_name_error(name: str) -> str | None:
    """Return a stable error code for a Windows-invalid name, else None.

    Windows rejects device names (CON, PRN, AUX, NUL, COM1-9, LPT1-9 —
    even with an extension), components ending in a dot or space, control
    characters, and components longer than 255 UTF-16 units (the
    MAX_PATH-family limit at the name level).  The check is Windows-only:
    every one of these is legal on POSIX filesystems.

    Codes follow the ``_batch_rename`` error-key style so callers can map
    them to localized messages: ``"invalid_name"`` / ``"reserved_name"``.
    """
    if os.name != "nt":
        return None
    if not name or name in {".", ".."}:
        return "invalid_name"
    if any(ord(character) < 32 for character in name):
        return "invalid_name"
    if name.endswith((".", " ")):
        return "invalid_name"
    if name.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        return "reserved_name"
    if len(name.encode("utf-16-le")) // 2 > _MAX_FILENAME_COMPONENT_UNITS:
        return "invalid_name"
    return None


def error_category(exc: BaseException) -> str:
    """Classify a file-operation failure into a stable, structured category.

    Returns a machine-readable key (not localized text) so callers can
    surface or map it — e.g. ``[not_found] ...`` when collecting errors —
    instead of relying on raw ``str(exc)`` text.
    """
    if isinstance(exc, PermissionError):
        return "permission_denied"
    if isinstance(exc, FileNotFoundError):
        return "not_found"
    if isinstance(exc, OSError) and (
        exc.errno == errno.ENOSPC
        or "no space left on device" in str(exc).lower()
        or "磁盘空间不足" in str(exc)
    ):
        return "disk_full"
    return "operation_failed"


_path_locks_guard = threading.Lock()
_path_locks: dict[str, threading.Lock] = {}


@contextmanager
def acquire_path_locks(*paths: Path):
    """Serialize file operations that touch the same resolved paths.

    Locks are acquired in sorted path order so concurrent multi-path
    operations cannot deadlock against each other.  The registry is
    process-wide so undo backup preparation and deletion share the same
    per-path exclusion.
    """
    keys = sorted({os.path.normcase(str(Path(path).resolve())) for path in paths})
    with _path_locks_guard:
        locks = [_path_locks.setdefault(key, threading.Lock()) for key in keys]
    for lock in locks:
        lock.acquire()
    try:
        yield
    finally:
        for lock in reversed(locks):
            lock.release()


def _measure_command(command: str):
    """Record a public command only after its session lease has been acquired."""
    def decorate(method):
        @wraps(method)
        def measured(self, *args, **kwargs):
            depth = self._telemetry_depth()
            if depth == 0:
                self._begin_refresh_diagnostics()
            self._telemetry_local.depth = depth + 1
            started = perf_counter() if self._performance_recorder is not None else None
            try:
                result = method(self, *args, **kwargs)
            except Exception:
                if depth == 0 and not self._telemetry_suppressed():
                    self._record_command(command, started, "error", 0, "failed")
                raise
            finally:
                self._telemetry_local.depth = depth
                if depth == 0:
                    self._publish_refresh_diagnostics()
            if depth == 0 and not self._telemetry_suppressed():
                errors = getattr(result, "errors", ())
                warnings = getattr(result, "warnings", ())
                if not warnings:
                    warnings = self._refresh_warnings()
                changed = getattr(result, "changed_paths", None)
                affected = len(changed) if changed is not None else 1
                self._record_command(
                    command,
                    started,
                    "partial" if errors else ("degraded" if warnings else "success"),
                    affected,
                    "events_published",
                )
            return result
        return measured
    return decorate


class FileOperationService:
    """Filesystem operations shared by desktop actions and future APIs."""

    def __init__(self, session: LibrarySession | None = None,
                  asset_index_service: AssetIndexService | None = None,
                  performance_recorder: PerformanceRecorder | None = None,
                  reconciliation_queue: ReconciliationQueue | None = None,
                  import_manifest_store=None,
                  pending_projection_repairs_dir: Path | None = None):
        self.session = session
        self._asset_index_service = asset_index_service
        self._reconciliation_queue = reconciliation_queue
        self._import_manifest_store = import_manifest_store
        self._pending_projection_repairs_dir = pending_projection_repairs_dir
        self._performance_recorder = (
            performance_recorder if performance_recorder is not None and performance_recorder.enabled else None
        )
        self._telemetry_local = threading.local()
        self._refresh_diagnostics_lock = threading.Lock()
        self._refresh_diagnostics: deque[
            tuple[str, tuple[FileOperationWarning, ...]]
        ] = deque(maxlen=200)

    def _telemetry_depth(self) -> int:
        return getattr(self._telemetry_local, "depth", 0)

    def _telemetry_suppressed(self) -> int:
        return getattr(self._telemetry_local, "suppressed", 0)

    def _refresh_warnings(self) -> tuple[FileOperationWarning, ...]:
        return tuple(getattr(self._telemetry_local, "refresh_warnings", ()))

    def _current_operation_id(self) -> str:
        return str(getattr(self._telemetry_local, "operation_id", ""))

    def _begin_refresh_diagnostics(self) -> None:
        self._telemetry_local.operation_id = f"file-op-{uuid4().hex}"
        self._telemetry_local.refresh_warnings = []

    def _publish_refresh_diagnostics(self) -> None:
        warnings = self._refresh_warnings()
        if not warnings:
            return
        operation_id = self._current_operation_id()
        with self._refresh_diagnostics_lock:
            self._refresh_diagnostics.append((operation_id, warnings))

    @property
    def last_refresh_warnings(self) -> tuple[FileOperationWarning, ...]:
        """Return refresh diagnostics from the most recent command on this thread."""
        return self._refresh_warnings()

    @property
    def last_operation_id(self) -> str | None:
        """Return the most recent command id observed on this thread."""
        operation_id = self._current_operation_id()
        return operation_id or None

    def drain_refresh_diagnostics(
        self,
        operation_id: str | None = None,
    ) -> tuple[tuple[str, tuple[FileOperationWarning, ...]], ...]:
        """Consume completed refresh diagnostics across worker/UI threads.

        When ``operation_id`` is supplied, unrelated completed operations stay
        queued for their own caller instead of being destructively consumed.
        """
        with self._refresh_diagnostics_lock:
            if operation_id is None:
                diagnostics = tuple(self._refresh_diagnostics)
                self._refresh_diagnostics.clear()
                return diagnostics
            matched = []
            retained = deque(maxlen=self._refresh_diagnostics.maxlen)
            for diagnostic in self._refresh_diagnostics:
                if diagnostic[0] == operation_id:
                    matched.append(diagnostic)
                else:
                    retained.append(diagnostic)
            self._refresh_diagnostics = retained
            return tuple(matched)

    @property
    def reconciliation_queue(self) -> ReconciliationQueue | None:
        """Return the session-scoped repair queue, when one is configured."""
        return self._reconciliation_queue

    @contextmanager
    def suppress_command_telemetry(self):
        """Let a higher-level command own telemetry for delegated file work."""
        suppressed = self._telemetry_suppressed()
        self._telemetry_local.suppressed = suppressed + 1
        try:
            yield
        finally:
            self._telemetry_local.suppressed = suppressed

    def _record_command(
        self, command: str, started: float | None, outcome: str, affected: int, phase: str
    ) -> None:
        if self._performance_recorder is None or started is None:
            return
        try:
            self._performance_recorder.record(
                "file.command",
                (perf_counter() - started) * 1000,
                session_token=self.session.event_token if self.session is not None else None,
                path=self.session.root_str if self.session is not None else None,
                attributes={
                    "command": command,
                    "outcome": outcome,
                    "affected_count": affected,
                    "phase": phase,
                    "operation_id": self._current_operation_id(),
                },
            )
        except Exception:
            pass

    def _reconciliation_scope(self, path: Path) -> Path:
        """Choose an existing directory for an asset-index rescan task."""
        candidate = Path(path).resolve()
        if candidate.is_dir():
            return candidate
        parent = candidate.parent
        if parent.is_dir():
            return parent
        if self.session is not None:
            return self.session.root
        return parent

    def _record_index_refresh_issue(
        self,
        phase: str,
        path: Path,
        *,
        status: str,
        retry_count: int = 0,
        failure: BaseException | None = None,
        expected_revision: int | None = None,
        observed_revision: int | None = None,
        warning_code: str | None = None,
        reconciliation_path: Path | None = None,
        repair_payload: dict[str, object] | None = None,
    ) -> None:
        """Record a degraded index refresh without masking filesystem success."""
        failure_type = type(failure).__name__ if failure is not None else None
        operation_id = self._current_operation_id()
        warning = FileOperationWarning(
            code=warning_code or f"asset_index_refresh_{status}",
            phase=phase,
            path=str(path),
            status=status,
            retry_count=retry_count,
            failure_type=failure_type,
            operation_id=operation_id,
        )
        warnings = getattr(self._telemetry_local, "refresh_warnings", None)
        if warnings is None:
            warnings = []
            self._telemetry_local.refresh_warnings = warnings
        warnings.append(warning)
        reconciliation_state = "not_configured"
        reconciliation_error_type = ""
        if self._reconciliation_queue is not None and self.session is not None:
            projection_enqueue_failed = False
            queue_path = reconciliation_path or path
            enqueue_request = {
                "path": str(queue_path),
                "reason": status,
                "operation_id": operation_id or None,
                "expected_revision": expected_revision,
                "observed_revision": observed_revision,
            }
            try:
                if repair_payload is not None:
                    from AssetsManager.application.reconciliation_queue import (
                        ReconciliationKind,
                    )
                    try:
                        self._reconciliation_queue.enqueue_or_merge(
                            path=queue_path,
                            reason=status,
                            operation_id=operation_id or None,
                            expected_revision=expected_revision,
                            observed_revision=observed_revision,
                            kind=ReconciliationKind.FILESYSTEM_PROJECTION_REPAIR,
                            payload=repair_payload,
                        )
                    except Exception as exc:
                        # The projection repair is the durable part of the
                        # pair: persist its request so a later restart can
                        # re-enqueue it instead of losing it forever.
                        reconciliation_error_type = type(exc).__name__
                        projection_enqueue_failed = True
                        self._persist_pending_projection_repair({
                            **enqueue_request,
                            "kind": ReconciliationKind.FILESYSTEM_PROJECTION_REPAIR.value,
                            "payload": repair_payload,
                        })
                try:
                    self._reconciliation_queue.enqueue_or_merge(
                        path=queue_path,
                        reason=status,
                        operation_id=operation_id or None,
                        expected_revision=expected_revision,
                        observed_revision=observed_revision,
                    )
                    reconciliation_state = (
                        "generic_queued_projection_failed"
                        if projection_enqueue_failed
                        else "queued"
                    )
                except Exception as exc:
                    # A repair-marker failure must never turn a successful
                    # filesystem command into a filesystem failure.  The warning
                    # remains available through the normal diagnostics channel,
                    # while telemetry preserves the lost enqueue signal.
                    reconciliation_state = "enqueue_failed"
                    reconciliation_error_type = type(exc).__name__
                    from AssetsManager.application.reconciliation_queue import (
                        ReconciliationKind,
                    )
                    self._persist_pending_projection_repair({
                        **enqueue_request,
                        "kind": ReconciliationKind.ASSET_INDEX_ROOT_RESCAN.value,
                        "payload": None,
                    })
            except Exception as exc:
                # Fallback bookkeeping itself must never break the command.
                reconciliation_state = "enqueue_failed"
                reconciliation_error_type = reconciliation_error_type or type(exc).__name__
                _log.warning(
                    "Pending projection repair persistence failed for %s: %s",
                    queue_path, exc,
                )
        if self._performance_recorder is None:
            return
        try:
            self._performance_recorder.record(
                "file.index_refresh",
                0.0,
                session_token=self.session.event_token if self.session is not None else None,
                path=str(path),
                attributes={
                    "phase": phase,
                    "status": status,
                    "retry_count": retry_count,
                    "failure_type": failure_type or "",
                    "operation_id": operation_id,
                    "reconciliation_state": reconciliation_state,
                    "reconciliation_error_type": reconciliation_error_type,
                },
            )
        except Exception:
            # Diagnostics must never replace the original file operation result.
            pass

    def _resolve_pending_projection_repairs_dir(self) -> Path | None:
        """Resolve the directory holding durable enqueue-failure markers."""
        if self._pending_projection_repairs_dir is not None:
            return self._pending_projection_repairs_dir
        if self.session is None:
            return None
        try:
            from AssetsManager.core.path_resolver import library_data_dir

            return library_data_dir(self.session.root_str) / "pending_projection_repairs"
        except Exception:
            return None

    def _persist_pending_projection_repair(
        self, request: Mapping[str, object]
    ) -> None:
        """Write a durable ``<timestamp>-<uuid>.json`` marker for one enqueue.

        Best effort by design: when the enqueue failed (e.g. disk full),
        demanding more disk for the marker would be wrong, so any write
        failure falls back to log-only (the pre-fix behaviour).
        """
        directory = self._resolve_pending_projection_repairs_dir()
        if directory is None:
            return
        try:
            directory.mkdir(parents=True, exist_ok=True)
            marker = directory / f"{int(time())}-{uuid4().hex}.json"
            document = {
                "format": "assetsmanager.pending-projection-repair",
                "version": 1,
                "saved_at": time(),
                "request": dict(request),
            }
            marker.write_text(
                json.dumps(document, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as exc:
            _log.error(
                "Could not persist pending projection repair marker: %s", exc
            )

    def drain_pending_projection_repairs(self) -> int:
        """Re-enqueue persisted projection-repair requests from a previous run.

        Every successfully re-enqueued marker is removed; a marker whose
        enqueue fails again is kept for the next attempt.  Drain failures
        never raise: startup must not depend on this recovery path.
        """
        queue = self._reconciliation_queue
        directory = self._resolve_pending_projection_repairs_dir()
        if queue is None or directory is None:
            return 0
        try:
            markers = sorted(directory.glob("*.json"))
        except OSError:
            return 0
        from AssetsManager.application.reconciliation_queue import (
            ReconciliationKind,
        )

        kinds = {kind.value: kind for kind in ReconciliationKind}
        drained = 0
        for marker in markers:
            try:
                document = json.loads(marker.read_text(encoding="utf-8"))
                request = (
                    document.get("request") if isinstance(document, dict) else None
                )
                if not isinstance(request, dict):
                    raise ValueError("marker has no enqueue request")
                path_value = request.get("path")
                if not isinstance(path_value, str) or not path_value:
                    raise ValueError("marker has no enqueue path")
                kind = kinds.get(
                    str(request.get("kind") or ""),
                    ReconciliationKind.ASSET_INDEX_ROOT_RESCAN,
                )
                payload = (
                    request.get("payload")
                    if kind is ReconciliationKind.FILESYSTEM_PROJECTION_REPAIR
                    else None
                )
                queue.enqueue_or_merge(
                    path=path_value,
                    reason=str(request.get("reason") or "pending_projection_repair_drain"),
                    operation_id=request.get("operation_id"),
                    expected_revision=request.get("expected_revision"),
                    observed_revision=request.get("observed_revision"),
                    kind=kind,
                    payload=payload,
                )
            except Exception as exc:
                _log.warning(
                    "Keeping pending projection repair marker %s: %s",
                    marker.name, exc,
                )
                continue
            try:
                marker.unlink()
            except OSError as exc:
                # Re-enqueueing is idempotent (enqueue_or_merge), so a marker
                # that survives until the next drain is safe to replay.
                _log.warning(
                    "Could not remove drained marker %s: %s", marker.name, exc
                )
                continue
            drained += 1
        return drained

    def _record_degraded_index_result(
        self, phase: str, path: Path, result: object
    ) -> None:
        status = getattr(result, "status", "unknown")
        status_value = getattr(status, "value", status)
        if (
            getattr(result, "committed", None) is False
            and getattr(result, "published", False)
        ):
            status_value = "staged"
        self._record_index_refresh_issue(
            phase,
            path,
            status=str(status_value),
            retry_count=int(getattr(result, "retry_count", 0) or 0),
            failure=getattr(result, "failure", None),
            expected_revision=getattr(result, "expected_revision", None),
            observed_revision=getattr(result, "actual_revision", None),
        )

    @property
    def _library_root(self) -> Path | None:
        return self.session.root if self.session is not None else None

    def _root_for(self, library_root: str | Path | None) -> Path | None:
        root = self._library_root or (Path(library_root).resolve() if library_root else None)
        if library_root is not None and root is not None and Path(library_root).resolve() != root:
            raise ValueError(f"Library root does not match bound session: {library_root}")
        return root

    def _connection(self) -> Connection:
        if self.session is None:
            raise RuntimeError("A bound session is required for projection updates")
        return self.session.connection_for(self.session.root)

    @contextmanager
    def _clean_transaction_boundary(self):
        """Guard filesystem deletes against caller-owned SQLite transactions."""
        if self.session is None:
            yield
            return
        from AssetsManager.core.database import db_write_lock

        connection = self._connection()
        with db_write_lock(connection):
            if connection.in_transaction:
                raise RuntimeError(
                    "FileOperationService delete requires a clean transaction boundary"
                )
            yield

    def _publish_file_change(
        self, kind: str, paths: tuple[Path, ...], old_paths: tuple[Path, ...] = ()
    ) -> None:
        if self.session is None:
            return
        get_event_bus().publish(FileSystemChanged(
            library_root=self.session.root_str,
            session_token=self.session.event_token,
            kind=kind,
            paths=tuple(str(path) for path in paths),
            old_paths=tuple(str(path) for path in old_paths),
        ))

    @session_operation
    @_measure_command("create_folder")
    def create_folder(self, parent: str | Path, name: str = "New Folder") -> Path:
        root = self._root_for(None)
        name_error = _windows_name_error(name)
        if name_error is not None:
            # OSError (not ValueError) so desktop callers that catch
            # OSError can surface the friendly, stable code to the user.
            raise OSError(
                f"{name_error}: invalid folder name on Windows: {name!r}"
            )
        base = Path(parent) / name
        _assert_under_root(base, root)
        for _ in range(100):
            target = unique_destination(base)
            try:
                target.mkdir()
                self._refresh_parents(target.parent)
                self._refresh_directory_tree(target)
                self._publish_file_change("created", (target,))
                return target
            except FileExistsError:
                base = target
        raise OSError(f"Could not create unique folder under {parent}")

    @session_operation
    @_measure_command("rename")
    def rename(self, old_path: str | Path, new_name: str,
               library_root: str | Path | None = None) -> Path:
        old = Path(old_path).resolve()
        name_error = _windows_name_error(new_name)
        if name_error is not None:
            raise OSError(
                f"{name_error}: invalid file name on Windows: {new_name!r}"
            )
        dst = (old.parent / new_name).resolve()
        if dst.parent != old.parent:
            raise ValueError("New name must stay in the original directory")
        result = self.move(old, dst, library_root=library_root)
        return result

    @session_operation
    @_measure_command("move")
    def move(self, source: str | Path, destination: str | Path,
             library_root: str | Path | None = None) -> Path:
        src = Path(source).resolve()
        dst = Path(destination).resolve()
        name_error = _windows_name_error(dst.name)
        if name_error is not None:
            # Validate before touching the filesystem so a reserved or
            # malformed destination yields a friendly, stable code instead
            # of a raw WinError from shutil.move/os.rename.
            raise OSError(
                f"{name_error}: invalid file name on Windows: {dst.name!r}"
            )
        root = self._root_for(library_root)
        _assert_under_root(src, root)
        _assert_under_root(dst, root)
        if src == dst:
            return dst
        if os.path.lexists(dst):
            raise FileExistsError(
                f"Destination already exists, refusing to overwrite: {dst}"
            )
        connection = self._connection() if self.session is not None else None
        from AssetsManager.core.database import db_write_lock
        from contextlib import nullcontext

        # Boundary check and projection update hold the connection-owned write
        # gate; the filesystem IO itself runs outside the lock so a long
        # cross-device copy does not block every DB writer.  The check is
        # repeated after the IO because a background rescan could leave
        # ``conn.in_transaction`` true between the two phases.
        guard = db_write_lock(connection) if connection is not None else nullcontext()
        with acquire_path_locks(src, dst):
            with guard:
                if connection is not None and connection.in_transaction:
                    raise RuntimeError(
                        "FileOperationService move requires a clean transaction boundary"
                    )
                # Re-check under the path lock: a concurrent move to the same
                # destination must not silently overwrite it.
                if os.path.lexists(dst):
                    raise FileExistsError(
                        f"Destination already exists, refusing to overwrite: {dst}"
                    )
            is_dir = src.is_dir()
            try:
                shutil.move(str(src), str(dst))
            except OSError:
                self._remove_partial_target(dst)
                raise
            with db_write_lock(connection) if connection is not None else nullcontext():
                if connection is not None and connection.in_transaction:
                    _log.warning(
                        "Move projection raced with an open transaction after "
                        "moving %s to %s", src, dst
                    )
            try:
                if root:
                    self._migrate_metadata(root, src, dst)
            except BaseException as exc:
                self._record_index_refresh_issue(
                    "metadata",
                    dst,
                    status="failed",
                    failure=exc,
                    warning_code="metadata_migration_failed",
                    reconciliation_path=self._reconciliation_scope(dst),
                    repair_payload=self._move_repair_payload(src, dst, is_directory=is_dir),
                )
            self._refresh_after_move(src, dst, is_dir)
            self._publish_file_change("moved", (dst,), (src,))
        return dst

    @session_operation
    @_measure_command("copy")
    def copy_to_directory(self, sources: list[str | Path], destination_dir: str | Path,
                          library_root: str | Path | None = None) -> FileOperationResult:
        changed: list[Path] = []
        errors: list[str] = []
        root = self._root_for(library_root)
        is_bound = root is not None
        destination = Path(destination_dir).resolve()
        if root is None:
            # Legacy unbound copies may rearrange files within the destination's
            # containing tree, but cannot import from outside that tree.
            root = destination.parent
        _assert_under_root(destination, root)
        for source in sources:
            src = Path(source).resolve()
            if not is_bound:
                _assert_under_root(src, root)
            target = None
            # Lock the source and the stable first-candidate destination
            # name: two concurrent copies of same-named files into one
            # directory must not both resolve (and truncate-write) the same
            # target.  unique_destination only probes availability without
            # holding a reservation, so serialization here — mirroring the
            # move series — makes the loser re-resolve after the winner's
            # copy completed.
            with acquire_path_locks(src, Path(destination_dir) / src.name):
                try:
                    target = unique_destination(destination / src.name).resolve()
                    if src.is_dir():
                        shutil.copytree(src, target)
                        self._refresh_directory_tree(target)
                    else:
                        shutil.copy2(src, target)
                    self._refresh_parents(target.parent)
                    changed.append(target)
                except OSError as exc:
                    if target is not None:
                        self._remove_partial_target(target)
                    errors.append(f"[{error_category(exc)}] {exc}")
        # One aggregate event per batch (mirrors ImportService): copies have
        # no "old" location, so old_paths stays empty.
        if changed:
            self._publish_file_change("copied", tuple(changed))
        return FileOperationResult(
            tuple(changed), tuple(errors), self._refresh_warnings()
        )

    @session_operation
    @_measure_command("move_batch")
    def move_to_directory(self, sources: list[str | Path], destination_dir: str | Path,
                          library_root: str | Path | None = None) -> FileOperationResult:
        changed: list[Path] = []
        errors: list[str] = []
        moved_pairs: list[tuple[Path, Path]] = []
        root = self._root_for(library_root)
        _assert_under_root(Path(destination_dir).resolve(), root)
        connection = self._connection() if self.session is not None else None
        from AssetsManager.core.database import db_write_lock
        from contextlib import nullcontext

        # Admit the whole batch before the first filesystem mutation.  The
        # per-item check below remains a race-observability guard for changes
        # that occur after this admission point.
        if connection is not None:
            with db_write_lock(connection):
                if connection.in_transaction:
                    raise RuntimeError(
                        "FileOperationService move requires a clean transaction boundary"
                    )

        for source in sources:
            src = Path(source).resolve()
            _assert_under_root(src, root)
            target = None
            # Lock the destination candidate too: two concurrent moves of
            # same-named files into one directory must not overwrite each
            # other.  The candidate name is stable (src.name) so both sides
            # lock the same key, and the collision-free rename happens under
            # that lock.
            with acquire_path_locks(src, Path(destination_dir) / src.name):
                try:
                    with db_write_lock(connection) if connection is not None else nullcontext():
                        if connection is not None and connection.in_transaction:
                            raise RuntimeError(
                                "FileOperationService move requires a clean transaction boundary"
                            )
                    is_dir = src.is_dir()
                    target = unique_destination(Path(destination_dir) / src.name).resolve()
                    try:
                        shutil.move(str(src), str(target))
                    except OSError:
                        self._remove_partial_target(target)
                        raise
                    try:
                        if root:
                            self._migrate_metadata(root, src, target)
                    except BaseException as exc:
                        self._record_index_refresh_issue(
                            "metadata",
                            target,
                            status="failed",
                            failure=exc,
                            warning_code="metadata_migration_failed",
                            reconciliation_path=self._reconciliation_scope(target),
                            repair_payload=self._move_repair_payload(src, target, is_directory=is_dir),
                        )
                    self._refresh_after_move(src, target, is_dir)
                    changed.append(target)
                    moved_pairs.append((src, target))
                except OSError as exc:
                    if target is not None:
                        self._remove_partial_target(target)
                    errors.append(f"[{error_category(exc)}] {exc}")
        # One aggregate event per batch (mirrors ImportService): every
        # successful (old, new) pair rides a single "moved" event.
        if moved_pairs:
            self._publish_file_change(
                "moved",
                tuple(target for _src, target in moved_pairs),
                tuple(src for src, _target in moved_pairs),
            )
        return FileOperationResult(
            tuple(changed), tuple(errors), self._refresh_warnings(),
            tuple(moved_pairs),
        )

    @session_operation
    @_measure_command("duplicate")
    def duplicate(self, path: str | Path, copy_label: str = "_copy") -> Path:
        src = Path(path).resolve()
        root = self._root_for(None)
        _assert_under_root(src, root)
        candidate = src.with_name(f"{src.stem}{copy_label}{src.suffix}")
        # Lock the source and the stable first-candidate name so two
        # concurrent duplicates of the same file cannot both write the same
        # target (unique_destination does not hold a reservation).
        with acquire_path_locks(src, candidate):
            target = unique_destination(candidate).resolve()
            _assert_under_root(target, root)
            try:
                if src.is_dir():
                    shutil.copytree(src, target)
                else:
                    shutil.copy2(src, target)
            except OSError:
                self._remove_partial_target(target)
                raise
            self._refresh_parents(target.parent)
            if target.is_dir():
                self._refresh_directory_tree(target)
            # A duplicate has no "old" location: old_paths stays empty.
            self._publish_file_change("created", (target,))
        return target

    @session_operation
    @_measure_command("delete_permanent")
    def delete_permanent(self, paths: list[str | Path],
                         library_root: str | Path | None = None) -> FileOperationResult:
        changed: list[Path] = []
        errors: list[str] = []
        root = self._root_for(library_root)
        for path in paths:
            p = Path(path).resolve()
            _assert_under_root(p, root)
            if root is not None and p == Path(root).resolve():
                raise ValueError(f"Refusing to delete library root: {p}")
            with acquire_path_locks(p):
                with self._clean_transaction_boundary():
                    try:
                        is_dir = p.is_dir()
                        if is_dir:
                            shutil.rmtree(p)
                        else:
                            p.unlink()
                    except OSError as exc:
                        errors.append(f"[{error_category(exc)}] {exc}")
                        continue
                    try:
                        self._clear_deleted_projection(p)
                    except BaseException as exc:
                        _log.warning(
                            "Projection cleanup failed after deleting %s: %s", p, exc
                        )
                        self._record_index_refresh_issue(
                            "projection_cleanup",
                            p,
                            status="failed",
                            failure=exc,
                            reconciliation_path=self._reconciliation_scope(p),
                            warning_code="projection_cleanup_failed",
                            repair_payload=self._delete_repair_payload(
                                p, delete_mode="permanent"
                            ),
                        )
                    try:
                        self._refresh_parents(p.parent)
                    except Exception as exc:
                        errors.append(f"[{error_category(exc)}] {exc}")
                    changed.append(p)
        # One aggregate event per batch (mirrors ImportService).
        if changed:
            self._publish_file_change("deleted", tuple(changed))
        return FileOperationResult(
            tuple(changed), tuple(errors), self._refresh_warnings()
        )

    @session_operation
    @_measure_command("restore_backup")
    def restore_backup(self, backup: str | Path, destination: str | Path,
                       library_root: str | Path | None = None) -> RestoreResult:
        """Restore an undo backup and publish the corresponding create event."""
        source = Path(backup).resolve()
        target = Path(destination).resolve()
        root = self._root_for(library_root)
        _assert_under_root(target, root)
        is_dir = source.is_dir()
        degraded = False
        with acquire_path_locks(target):
            if os.path.lexists(target):
                raise FileExistsError(
                    f"Destination already exists, refusing to overwrite: {target}"
                )
            try:
                if is_dir:
                    shutil.copytree(source, target)
                else:
                    shutil.copy2(source, target)
            except OSError:
                self._remove_partial_target(target)
                raise
            self._refresh_parents(target.parent)
            if is_dir:
                self._refresh_directory_tree(target)
            projection_restored = self._restore_projection_snapshot(source, target)
            degraded = not projection_restored
            if not projection_restored:
                repair_payload = self._restore_repair_payload(source, target, is_dir)
                self._record_index_refresh_issue(
                    "projection_restore",
                    target,
                    status="failed",
                    failure=RuntimeError("projection snapshot restore failed"),
                    reconciliation_path=self._reconciliation_scope(target),
                    warning_code="projection_restore_failed",
                    repair_payload=repair_payload,
                )
        self._publish_file_change("restored", (target,))
        return RestoreResult(
            path=target,
            degraded=degraded,
            warnings=self._refresh_warnings(),
        )

    @session_operation
    @_measure_command("delete_to_trash")
    def delete_to_trash(self, paths: list[str | Path],
                        library_root: str | Path | None = None) -> FileOperationResult:
        from send2trash import send2trash

        changed: list[Path] = []
        errors: list[str] = []
        root = self._root_for(library_root)
        for path in paths:
            p = Path(path).resolve()
            _assert_under_root(p, root)
            if root is not None and p == Path(root).resolve():
                raise ValueError(f"Refusing to delete library root: {p}")
            with acquire_path_locks(p):
                with self._clean_transaction_boundary():
                    try:
                        send2trash(str(p))
                    except OSError as exc:
                        errors.append(f"[{error_category(exc)}] {exc}")
                        continue
                    try:
                        self._clear_deleted_projection(p)
                    except BaseException as exc:
                        _log.warning(
                            "Projection cleanup failed after trashing %s: %s", p, exc
                        )
                        self._record_index_refresh_issue(
                            "projection_cleanup",
                            p,
                            status="failed",
                            failure=exc,
                            reconciliation_path=self._reconciliation_scope(p),
                            warning_code="projection_cleanup_failed",
                            repair_payload=self._delete_repair_payload(
                                p, delete_mode="trash"
                            ),
                        )
                    try:
                        self._refresh_parents(p.parent)
                    except Exception as exc:
                        errors.append(f"[{error_category(exc)}] {exc}")
                    changed.append(p)
        # One aggregate event per batch (mirrors ImportService).
        if changed:
            self._publish_file_change("deleted", tuple(changed))
        return FileOperationResult(
            tuple(changed), tuple(errors), self._refresh_warnings()
        )

    def _migrate_metadata(self, library_root: Path, old_path: Path, new_path: Path) -> None:
        if self.session is None:
            raise RuntimeError(
                "FileOperationService metadata migration requires a LibrarySession"
            )
        from AssetsManager.application.thumbnail_cache_lifecycle import cache_owner_lock
        from AssetsManager.core.database import migrate_path_metadata
        with cache_owner_lock(self.session.thumb_dir):
            migrate_path_metadata(
                self._connection(), self.session.thumb_dir, old_path, new_path,
            )

    def _refresh_parents(self, *parents: Path) -> None:
        if self.session is None or self._asset_index_service is None:
            return
        conn = self._connection()
        for parent in set(parents):
            try:
                result_api = getattr(
                    self._asset_index_service, "index_directory_result", None
                )
                if callable(result_api):
                    result = result_api(
                        conn, self.session.root, parent, force=True,
                    )
                    if getattr(result, "degraded", False):
                        self._record_degraded_index_result(
                            "parent", parent, result
                        )
                        continue
                else:
                    self._asset_index_service.index_directory(
                        conn, self.session.root, parent, force=True,
                    )
            except AssetIndexRevisionConflict as exc:
                # Legacy service doubles may still raise the conflict directly.
                self._record_index_refresh_issue(
                    "parent", parent, status="stale", failure=exc
                )
                continue
            except OperationalError as exc:
                self._record_index_refresh_issue(
                    "parent", parent, status="busy", failure=exc
                )
                continue
            except Exception as exc:
                # A non-whitelisted refresh failure must never escape after
                # the filesystem change already happened (move, create_folder,
                # duplicate, ... would otherwise report overall failure).
                # Degrade to a warning + generic rescan instead.
                self._record_index_refresh_issue(
                    "parent", parent, status="failed", failure=exc,
                    reconciliation_path=self._reconciliation_scope(parent),
                )
                continue

    def _refresh_after_move(self, old_path: Path, new_path: Path, is_dir: bool) -> None:
        if self.session is None or self._asset_index_service is None:
            return
        conn = self._connection()
        if is_dir:
            try:
                self._asset_index_service.remove_entry(conn, old_path)
            except BaseException as exc:
                self._record_index_refresh_issue(
                    "remove", old_path, status="failed", failure=exc
                )
            try:
                self._asset_index_service.remove_directory(conn, old_path)
            except BaseException as exc:
                self._record_index_refresh_issue(
                    "remove", old_path, status="failed", failure=exc
                )
        self._refresh_parents(old_path.parent, new_path.parent)
        if is_dir:
            self._refresh_directory_tree(new_path)

    def _remove_partial_target(self, target: Path) -> None:
        try:
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink(missing_ok=True)
        except OSError:
            pass

    def _refresh_directory_tree(self, directory: Path) -> None:
        if self.session is None or self._asset_index_service is None:
            return
        try:
            result_api = getattr(
                self._asset_index_service, "index_directory_tree_result", None
            )
            if callable(result_api):
                result = result_api(
                    self._connection(), self.session.root, directory,
                )
                if getattr(result, "degraded", False):
                    self._record_degraded_index_result(
                        "tree", directory, result
                    )
                    return
            else:
                self._asset_index_service.index_directory_tree(
                    self._connection(), self.session.root, directory,
                )
        except AssetIndexRevisionConflict as exc:
            # Legacy service doubles may still raise the conflict directly.
            self._record_index_refresh_issue(
                "tree", directory, status="stale", failure=exc
            )
            return
        except OperationalError as exc:
            self._record_index_refresh_issue(
                "tree", directory, status="busy", failure=exc
            )
            return
        except Exception as exc:
            # Same contract as _refresh_parents: the filesystem change has
            # already happened, so degrade to warning + generic rescan
            # instead of letting the command fail wholesale.
            self._record_index_refresh_issue(
                "tree", directory, status="failed", failure=exc,
                reconciliation_path=self._reconciliation_scope(directory),
            )

    def _move_repair_payload(
        self, source: Path, destination: Path, *, is_directory: bool
    ) -> dict[str, object]:
        """Single source for the ``move`` projection-repair payload shape.

        The literal key order below is load-bearing: enqueued payloads are
        persisted/compared as JSON with substring assertions.
        """
        return {
            "payload_version": 1,
            "operation_kind": "move",
            "operation_id": self._current_operation_id() or uuid4().hex,
            "projection_set": [
                "asset_index", "tags", "metadata", "favorites",
                "thumbnail_rows", "thumbnail_bytes",
            ],
            "scope_path": str(self._reconciliation_scope(destination)),
            "source_path": str(source),
            "destination_path": str(destination),
            "is_directory": is_directory,
            "expected_state": {
                "source_absent": True,
                "destination_present": True,
            },
        }

    def _delete_repair_payload(
        self, path: Path, *, delete_mode: str
    ) -> dict[str, object]:
        """Single source for the ``delete`` projection-repair payload shape.

        The literal key order below is load-bearing: enqueued payloads are
        persisted/compared as JSON with substring assertions.
        """
        return {
            "payload_version": 1,
            "operation_kind": "delete",
            "operation_id": self._current_operation_id() or uuid4().hex,
            "projection_set": [
                "asset_index", "tags", "metadata", "favorites",
                "thumbnail_rows", "thumbnail_bytes",
            ],
            "scope_path": str(self._reconciliation_scope(path)),
            "target_path": str(path),
            "delete_mode": delete_mode,
            "expected_state": {"target_absent": True},
        }

    def _restore_repair_payload(
        self, backup: Path, target: Path, is_directory: bool
    ) -> dict[str, object] | None:
        if self.session is None:
            return None
        snapshot_path = Path(str(backup) + ".projection.json")
        try:
            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return None
            from AssetsManager.application.reconciliation_queue import (
                _validate_restore_snapshot,
            )
            snapshot = _validate_restore_snapshot(payload, root=self.session.root)
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        scope = self._reconciliation_scope(target)
        return {
            "payload_version": 1,
            "operation_kind": "restore",
            "operation_id": self._current_operation_id() or uuid4().hex,
            "projection_set": ["asset_index", "tags", "metadata", "favorites"],
            "scope_path": str(scope),
            "target_path": str(target.resolve()),
            "is_directory": is_directory,
            "expected_state": {"target_present": True},
            "snapshot": snapshot,
        }

    def _restore_projection_snapshot(self, backup: Path, target: Path) -> bool:
        if self.session is None:
            return True
        snapshot_path = Path(str(backup) + ".projection.json")
        failed_marker = Path(str(backup) + ".projection.failed")
        if not snapshot_path.is_file():
            if failed_marker.is_file():
                # The snapshot was expected for this backup but its write
                # failed when the delete was prepared (UndoService leaves a
                # durable failure marker).  Restore must not pretend
                # success: report failure so the caller's projection_restore
                # repair channel records the degraded outcome and enqueues a
                # reconciliation task instead of silently dropping the
                # tags/notes/favorites of the restored file.
                _log.warning(
                    "Projection snapshot for %s was never written (failure "
                    "marker present); tags, notes and favorites for %s are "
                    "not restorable",
                    backup, target,
                )
                return False
            # Legacy backups predate projection snapshots: nothing to do.
            return True
        try:
            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            _log.warning(
                "Ignoring unreadable projection snapshot %s: %s", snapshot_path, exc
            )
            return False
        if not isinstance(payload, dict):
            return False
        from AssetsManager.core.database import db_write_lock
        from AssetsManager.core.path_resolver import remap_path_subtree

        base = str(payload.get("base", ""))
        target_key = str(target.resolve())

        def map_path(file_path: str) -> str:
            if base and base != target_key:
                return remap_path_subtree(base, target_key, file_path)
            return file_path

        conn = self._connection()
        with db_write_lock(conn):
            outer_transaction = conn.in_transaction
            savepoint = (
                f"file_operation_projection_restore_{id(self):x}_{monotonic_ns():x}"
            )
            savepoint_active = False
            try:
                conn.execute(f"SAVEPOINT {savepoint}")
                savepoint_active = True
                for file_path, tag in payload.get("file_tags", []):
                    conn.execute(
                        "INSERT OR IGNORE INTO file_tags (file_path, tag) VALUES (?,?)",
                        (map_path(file_path), tag),
                    )
                for file_path, notes, cached_size, cached_mtime, cached_file_count, urls in payload.get(
                    "file_meta", []
                ):
                    conn.execute(
                        "INSERT INTO file_meta "
                        "(file_path, notes, cached_size, cached_mtime, cached_file_count, urls) "
                        "VALUES (?,?,?,?,?,?) "
                        "ON CONFLICT(file_path) DO UPDATE SET "
                        "notes=CASE WHEN excluded.notes!='' THEN excluded.notes ELSE file_meta.notes END, "
                        "cached_size=COALESCE(excluded.cached_size, file_meta.cached_size), "
                        "cached_mtime=COALESCE(excluded.cached_mtime, file_meta.cached_mtime), "
                        "cached_file_count=COALESCE(excluded.cached_file_count, file_meta.cached_file_count), "
                        "urls=CASE WHEN excluded.urls!='[]' THEN excluded.urls ELSE file_meta.urls END",
                        (
                            map_path(file_path),
                            notes,
                            cached_size,
                            cached_mtime,
                            cached_file_count,
                            urls,
                        ),
                    )
                for owner_key, file_path, created_at in payload.get(
                    "library_favorites", []
                ):
                    conn.execute(
                        "INSERT OR IGNORE INTO library_favorites "
                        "(owner_key, file_path, created_at) VALUES (?, ?, ?)",
                        (owner_key, map_path(file_path), created_at),
                    )
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                savepoint_active = False
                if not outer_transaction:
                    conn.commit()
            except BaseException as exc:
                if savepoint_active:
                    try:
                        conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                    except BaseException:
                        pass
                if not outer_transaction and conn.in_transaction:
                    try:
                        conn.rollback()
                    except BaseException:
                        pass
                _log.warning(
                    "Failed to restore projection snapshot %s: %s", snapshot_path, exc
                )
                return False
        return True

    def _clear_deleted_projection(
        self, path: Path, *, publish_event: bool = True
    ) -> None:
        """Drop projection rows and thumbnail artifacts for a deleted path.

        The DB projection cleanup (file_tags/file_meta/library_favorites/
        thumbnail rows/asset index) deliberately does not depend on the
        thumbnail cache owner lease, so a busy cache owner can never skip
        it and leave ghost rows behind.  Only ``remove_artifacts`` runs
        under ``cache_owner_lock``.  If that lease times out, the
        TimeoutError propagates to the caller: the existing delete repair
        channel (``delete_permanent`` / ``delete_to_trash`` →
        ``_record_index_refresh_issue``, and the repair worker's own
        retryable-failure handling) then enqueues a ``delete`` projection
        repair task instead of silently skipping artifact cleanup.
        """
        if self.session is None:
            return
        from AssetsManager.core.database import db_write_lock
        from AssetsManager.repositories.favorite_repository import FavoriteRepository
        from AssetsManager.repositories.metadata_repository import MetadataRepository
        from AssetsManager.repositories.tag_repository import TagRepository
        from AssetsManager.repositories.thumbnail_repository import ThumbnailRepository

        target = str(path.resolve())
        conn = self._connection()
        cache_keys: list[str] = []
        removed_tag_rows = 0
        with db_write_lock(conn):
            outer_transaction = conn.in_transaction
            savepoint = (
                f"file_operation_projection_cleanup_{id(self):x}_{monotonic_ns():x}"
            )
            savepoint_active = False
            try:
                conn.execute(f"SAVEPOINT {savepoint}")
                savepoint_active = True
                removed_tag_rows = TagRepository(
                    conn,
                    library_root=self.session.context.root_identity,
                    session=self.session,
                ).delete_path(target, commit=False)
                MetadataRepository(conn).delete_path(target, commit=False)
                FavoriteRepository(conn).delete_path(target, commit=False)
                cache_keys = ThumbnailRepository(conn).delete_path(
                    target, commit=False
                )
                if self._asset_index_service is not None:
                    self._asset_index_service.remove_entry(
                        conn, path, commit=False
                    )
                    self._asset_index_service.remove_directory(
                        conn, path, commit=False
                    )
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                savepoint_active = False
                if not outer_transaction:
                    conn.commit()
            except BaseException as exc:
                cleanup_errors: list[BaseException] = []
                if savepoint_active:
                    for statement in (
                        f"ROLLBACK TO SAVEPOINT {savepoint}",
                        f"RELEASE SAVEPOINT {savepoint}",
                    ):
                        try:
                            conn.execute(statement)
                        except BaseException as cleanup_exc:
                            cleanup_errors.append(cleanup_exc)
                if not outer_transaction and conn.in_transaction:
                    try:
                        conn.rollback()
                    except BaseException as cleanup_exc:
                        cleanup_errors.append(cleanup_exc)
                if cleanup_errors:
                    exc.add_note(
                        "File projection cleanup transaction cleanup also failed: "
                        + "; ".join(str(error) for error in cleanup_errors)
                    )
                raise
        # Tag rows are already gone from the projection DB; publish before
        # the artifact phase so a cache-lease timeout cannot suppress it.
        if publish_event and removed_tag_rows:
            get_event_bus().publish(TagCatalogChanged(
                library_root=self.session.root_str,
                session_token=self.session.event_token,
            ))
        if not cache_keys:
            return
        from AssetsManager.application.thumbnail_cache_lifecycle import (
            cache_owner_lock,
            remove_artifacts,
        )
        try:
            with cache_owner_lock(self.session.thumb_dir):
                for cache_key in cache_keys:
                    remove_artifacts(self.session.thumb_dir, cache_key)
        except TimeoutError:
            _log.warning(
                "Thumbnail cache owner busy during projection cleanup; "
                "artifact removal for %s is deferred to the repair channel",
                path,
            )
            raise


_MAX_UNIQUE_RESERVE_ATTEMPTS = 1000


def unique_destination(path: str | Path) -> Path:
    """Return a non-existing path by appending `_1`, `_2`, ... if needed.

    For numbered suffixes, availability is atomically probed via
    ``os.open(O_CREAT | O_EXCL)`` to avoid TOCTOU races on the check.
    The reservation is not held: the probe file is removed before
    returning, so a caller that creates or writes the destination in a
    separate step must serialize concurrent operations on the same
    candidate with :func:`acquire_path_locks` (as the move/copy/duplicate
    commands do) — two callers probing the same non-existing first
    candidate would otherwise both receive it and corrupt each other's
    writes.
    """
    candidate = Path(path)
    if not candidate.exists():
        return candidate
    base = candidate.stem
    suffix = candidate.suffix
    parent = candidate.parent
    for index in range(1, _MAX_UNIQUE_RESERVE_ATTEMPTS + 1):
        candidate = parent / f"{base}_{index}{suffix}"
        if _try_reserve(candidate):
            return candidate
    raise OSError(f"Could not reserve a unique destination for {path}")


def _try_reserve(path: Path) -> bool:
    """Atomically create *path* as an empty file; return True on success.

    Uses ``O_CREAT | O_EXCL`` so the kernel rejects the call if the file
    already exists — no check-then-act race.  The file is deleted
    immediately after creation; callers must create the real content
    promptly (the window is milliseconds, acceptable for desktop use).
    """
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    try:
        os.close(fd)
        path.unlink()
    except OSError:
        raise
    return True
