"""One-time migration of JSON reconciliation markers into SQLite."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import logging
import os
from pathlib import Path
import time
from typing import Callable

from AssetsManager.application.reconciliation_queue_store import (
    SQLiteReconciliationQueueStore,
)
# The marker read reuses the queue's own JSON conversion helpers so the
# migration observes exactly the task set a queue would load. The queue
# constructor itself is deliberately NOT used for this read: it performs
# startup lease recovery and can rewrite the marker (see
# ``_read_legacy_marker``), which would turn a migration read into a write.
from AssetsManager.application.reconciliation_queue import (
    ReconciliationKind,
    ReconciliationQueuePersistenceError,
    ReconciliationTask,
    _canonical_path,
    _task_from_json,
)

_log = logging.getLogger(__name__)

# Mirrors ``ReconciliationQueue.max_tasks`` so the legacy read applies the
# same bounded load-time truncation a queue would have applied.
_LEGACY_READ_MAX_TASKS = 200

# Marker format versions accepted by the queue's own task conversion
# (version 1 is the legacy monotonic-deadline layout; version 2 is the
# wallclock-deadline layout). Pinned locally so the migration read does not
# couple to the queue module's private format constant.
_SUPPORTED_MARKER_VERSIONS = frozenset({1, 2})


class ReconciliationMarkerMigrationError(ReconciliationQueuePersistenceError):
    """Raised when a legacy marker cannot be retired safely."""

    def __init__(self, message: str, *, durable_store_updated: bool = False) -> None:
        self.durable_store_updated = durable_store_updated
        super().__init__(message)


class ReconciliationMarkerMigrationStatus(str, Enum):
    """Outcome of one marker migration attempt."""

    ABSENT = "absent"
    IMPORTED = "imported"
    RETIRED_EMPTY = "retired_empty"
    ALREADY_DURABLE = "already_durable"


@dataclass(frozen=True, slots=True)
class ReconciliationMarkerMigrationResult:
    """Auditable result of a marker migration attempt."""

    status: ReconciliationMarkerMigrationStatus
    marker_path: Path
    archive_path: Path
    task_count: int

    @property
    def migrated(self) -> bool:
        """Return whether the marker was consumed by this cutover."""
        return self.status in {
            ReconciliationMarkerMigrationStatus.IMPORTED,
            ReconciliationMarkerMigrationStatus.RETIRED_EMPTY,
            ReconciliationMarkerMigrationStatus.ALREADY_DURABLE,
        }


def migrate_reconciliation_marker(
    *,
    marker_path: str | Path,
    library_root: str | Path,
    store: SQLiteReconciliationQueueStore,
    archive_path: str | Path | None = None,
    clock: Callable[[], float] = time.monotonic,
    wall_clock: Callable[[], float] = time.time,
) -> ReconciliationMarkerMigrationResult:
    """Import one JSON marker and retire it after durable SQLite publication.

    The migration is intentionally strict:

    * an absent marker is a no-op;
    * an empty SQLite store may import the marker snapshot;
    * a non-empty SQLite store may only retire an empty or exactly equivalent
      marker, preventing silent task loss or state downgrade;
    * the marker is renamed only after SQLite persistence succeeds;
    * if rename fails after persistence, the exception records that durable
      state exists so the next startup can retry retirement without re-import.

    This is a single-process cutover contract. Cross-process marker locking and
    generation/merge remain a later phase.
    """
    marker = Path(marker_path)
    archive = (
        Path(archive_path)
        if archive_path is not None
        else marker.with_name(marker.name + ".migrated")
    )
    if not marker.exists():
        return ReconciliationMarkerMigrationResult(
            status=ReconciliationMarkerMigrationStatus.ABSENT,
            marker_path=marker,
            archive_path=archive,
            task_count=0,
        )

    try:
        legacy_tasks = _read_legacy_marker(
            marker,
            library_root=library_root,
            clock=clock,
            wall_clock=wall_clock,
        )
    except ReconciliationQueuePersistenceError as exc:
        _log.warning(
            "Reconciliation marker is unreadable or unsupported; "
            "treating it as unmigrated and continuing: %s (%s)",
            marker,
            exc,
        )
        legacy_tasks = ()
    except Exception as exc:
        raise ReconciliationMarkerMigrationError(
            f"Cannot read reconciliation marker: {marker}"
        ) from exc

    try:
        durable_tasks = store.load()
    except ReconciliationQueuePersistenceError:
        raise
    except Exception as exc:
        raise ReconciliationMarkerMigrationError(
            "Cannot inspect durable reconciliation queue before marker migration"
        ) from exc

    if durable_tasks:
        if legacy_tasks and not _same_snapshot(legacy_tasks, durable_tasks):
            raise ReconciliationMarkerMigrationError(
                "Legacy reconciliation marker conflicts with existing durable queue: "
                f"{marker}"
            )
        _retire_marker(marker, archive, durable_store_updated=False)
        status = (
            ReconciliationMarkerMigrationStatus.ALREADY_DURABLE
            if legacy_tasks
            else ReconciliationMarkerMigrationStatus.RETIRED_EMPTY
        )
        return ReconciliationMarkerMigrationResult(
            status=status,
            marker_path=marker,
            archive_path=archive,
            task_count=len(durable_tasks),
        )

    if legacy_tasks:
        try:
            store.replace(legacy_tasks)
        except Exception as exc:
            raise ReconciliationMarkerMigrationError(
                "Cannot publish legacy reconciliation marker into SQLite"
            ) from exc
        try:
            _retire_marker(marker, archive, durable_store_updated=True)
        except ReconciliationMarkerMigrationError:
            raise
        return ReconciliationMarkerMigrationResult(
            status=ReconciliationMarkerMigrationStatus.IMPORTED,
            marker_path=marker,
            archive_path=archive,
            task_count=len(legacy_tasks),
        )

    _retire_marker(marker, archive, durable_store_updated=False)
    return ReconciliationMarkerMigrationResult(
        status=ReconciliationMarkerMigrationStatus.RETIRED_EMPTY,
        marker_path=marker,
        archive_path=archive,
        task_count=0,
    )


def _read_legacy_marker(
    marker: Path,
    *,
    library_root: str | Path,
    clock: Callable[[], float] = time.monotonic,
    wall_clock: Callable[[], float] = time.time,
) -> tuple[ReconciliationTask, ...]:
    """Read a legacy JSON marker strictly read-only.

    Constructing a ``ReconciliationQueue`` over the marker is NOT a read: the
    constructor performs startup lease recovery and, whenever an expired
    running lease is found, rewrites the marker via ``_persist_unlocked``
    (``ReconciliationQueue.__init__``). A migration must never mutate the
    artifact it is reading, so the marker is parsed directly with the queue's
    own JSON conversion helpers instead.

    Lease recovery is intentionally deferred: the durable SQLite-backed queue
    constructed by the bootstrap performs the same recovery at its own
    construction after the marker has been imported or retired, so no
    conversion is lost by reading the raw snapshot. The one observable
    difference is a strict comparison: both the legacy snapshot and the
    durable store are now read raw, so an expired running task can no longer
    produce a spurious migration conflict against a non-empty durable queue.
    """
    if not marker.exists():
        return ()
    try:
        raw = json.loads(marker.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("unsupported reconciliation queue format")
        version = int(raw.get("version", 0))
        if version not in _SUPPORTED_MARKER_VERSIONS:
            raise ValueError("unsupported reconciliation queue format")
        tasks = raw.get("tasks", [])
        if not isinstance(tasks, list):
            raise ValueError("reconciliation queue tasks must be a list")
        loaded: dict[tuple[str, str, ReconciliationKind], ReconciliationTask] = {}
        now_monotonic = clock()
        now_wallclock = wall_clock()
        for item in tasks:
            task = _task_from_json(
                item,
                version=version,
                now_monotonic=now_monotonic,
                now_wallclock=now_wallclock,
            )
            if task.library_root != _canonical_path(library_root):
                continue
            loaded[task.repair_key] = task
        if len(loaded) > _LEGACY_READ_MAX_TASKS:
            loaded = dict(
                sorted(
                    loaded.items(),
                    key=lambda pair: pair[1].updated_at,
                )[-_LEGACY_READ_MAX_TASKS:]
            )
        return tuple(loaded.values())
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ReconciliationQueuePersistenceError(
            f"Cannot load reconciliation queue marker: {marker}"
        ) from exc


def _same_snapshot(
    left: tuple[ReconciliationTask, ...],
    right: tuple[ReconciliationTask, ...],
) -> bool:
    def key(task: ReconciliationTask) -> tuple[str, str, str, str]:
        return (
            task.library_root,
            task.path,
            task.kind.value,
            task.task_id,
        )

    def stable(task: ReconciliationTask) -> tuple[object, ...]:
        # Deadline fields are intentionally excluded: JSON and SQLite both
        # rebase wall-clock deadlines into a fresh monotonic clock on load, so
        # a crash between durable publish and archive rename can produce small
        # or even fully-due monotonic differences without a task-state conflict.
        return (
            task.task_id,
            task.library_root,
            task.path,
            task.kind,
            task.reason,
            task.state,
            task.attempts,
            task.operation_ids,
            task.last_error_type,
            task.last_error,
            task.expected_revision,
            task.observed_revision,
            task.created_at,
            task.updated_at,
            task.max_attempts,
        )

    left_sorted = tuple(sorted(left, key=key))
    right_sorted = tuple(sorted(right, key=key))
    return tuple(stable(task) for task in left_sorted) == tuple(
        stable(task) for task in right_sorted
    )


def _retire_marker(
    marker: Path,
    archive: Path,
    *,
    durable_store_updated: bool,
) -> None:
    """Rename a marker without overwriting a conflicting archive."""
    if not marker.exists():
        return
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        try:
            if marker.read_bytes() != archive.read_bytes():
                raise ReconciliationMarkerMigrationError(
                    "Existing migrated marker archive conflicts with source marker: "
                    f"{archive}",
                    durable_store_updated=durable_store_updated,
                )
            marker.unlink()
            return
        except ReconciliationMarkerMigrationError:
            raise
        except OSError as exc:
            raise ReconciliationMarkerMigrationError(
                "Cannot remove already archived reconciliation marker: "
                f"{marker}",
                durable_store_updated=durable_store_updated,
            ) from exc
    try:
        # The application currently runs on Windows, where rename refuses to
        # replace an existing destination. The explicit destination check above
        # also prevents intentional overwrite in the common path.
        os.rename(marker, archive)
    except OSError as exc:
        raise ReconciliationMarkerMigrationError(
            "Cannot retire reconciliation marker after durable publication: "
            f"{marker}",
            durable_store_updated=durable_store_updated,
        ) from exc
