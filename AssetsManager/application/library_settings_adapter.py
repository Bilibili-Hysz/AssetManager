"""UI-neutral adapter for the library maintenance and recovery settings surface."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from AssetsManager.application.context import LibrarySession
from AssetsManager.application.database_integrity_service import (
    DatabaseIntegrityService,
    IntegrityCheckReport,
)
from AssetsManager.application.database_maintenance_service import (
    DatabaseMaintenanceService,
    DatabaseSizeResult,
)
from AssetsManager.application.library_export_service import (
    BackupValidationResult,
    LibraryBackupResult,
    LibraryExportResult,
    LibraryRestoreResult,
    RestoreQuarantineEntry,
)
from AssetsManager.application.library_governance import (
    LibraryHealthSnapshot,
    collect_library_health,
)


class LibrarySettingsBlockedError(RuntimeError):
    """Raised when a settings operation is blocked by a lifecycle boundary."""


@dataclass(frozen=True)
class LibrarySettingsViewModel:
    """Read-only state consumed by a Desktop settings presentation layer."""

    library_root: Path
    session_token: str
    restore_allowed: bool
    restore_block_reason: str | None
    integrity_running: bool
    integrity_report: IntegrityCheckReport | None
    integrity_error: str | None
    integrity_schedule_error: str | None
    maintenance_running: bool
    maintenance_result: object | None
    maintenance_error: str | None
    maintenance_schedule_error: str | None


class _LibraryScopedServices(Protocol):
    session: LibrarySession
    integrity_service: DatabaseIntegrityService
    maintenance_service: DatabaseMaintenanceService
    export_service: Any


class LibrarySettingsAdapter:
    """Guard library settings operations without exposing Runtime internals to UI.

    The adapter is intentionally Qt-free. The dialog or its worker layer owns
    threading and presentation signals; this object owns only session identity,
    service selection, and lifecycle guards.
    """

    def __init__(self, services: _LibraryScopedServices) -> None:
        self._services = services
        self._session = services.session
        self._session_token = services.session.event_token

    @property
    def library_root(self) -> Path:
        return self._session.root

    @property
    def library_data_dir(self) -> Path:
        """Return the library's RuntimeData slot ("open data directory" target).

        Test doubles may not model ``data_dir`` on the session; fall back to
        the library root instead of raising from a presentation refresh path.
        """
        data_dir = getattr(self._session, "data_dir", None)
        return Path(data_dir) if data_dir is not None else Path(self._session.root)

    def collect_health_snapshot(self) -> LibraryHealthSnapshot:
        """Collect the H2-a1 health card metrics for the bound library.

        Heavy IO (recursive directory walks + read-only counts) — the caller
        must run this off the GUI thread (the settings dialog uses the shared
        ``run_task`` worker, same primitive as the maintenance runner).
        """
        self._ensure_live("library_health")
        session = self._session
        data_dir = Path(getattr(session, "data_dir", session.root))
        thumb_dir = getattr(session, "thumb_dir", None)
        return collect_library_health(
            session.connection_for(session.root),
            db_path=data_dir / "assetmanager.db",
            thumb_dir=Path(thumb_dir) if thumb_dir is not None else data_dir / ".thumbnails",
            derivatives_dir=data_dir / "derivatives",
        )

    @property
    def session_token(self) -> str:
        return self._session_token

    def view_model(self) -> LibrarySettingsViewModel:
        session_closed = self._session.is_closed
        integrity = self._services.integrity_service
        maintenance = self._services.maintenance_service
        return LibrarySettingsViewModel(
            library_root=self._session.root,
            session_token=self._session_token,
            restore_allowed=session_closed,
            restore_block_reason=None if session_closed else "restore_requires_closed_session",
            integrity_running=integrity.running,
            integrity_report=integrity.last_report,
            integrity_error=self._integrity_error(integrity.last_report),
            integrity_schedule_error=getattr(integrity, "last_schedule_error", None),
            maintenance_running=maintenance.running,
            maintenance_result=maintenance.last_result,
            maintenance_error=self._maintenance_error(maintenance.last_result),
            maintenance_schedule_error=getattr(maintenance, "last_schedule_error", None),
        )

    def start_integrity_check(self) -> bool:
        self._ensure_live("integrity_check")
        return self._services.integrity_service.schedule()

    def read_database_size(self) -> DatabaseSizeResult:
        self._ensure_live("database_size")
        return self._services.maintenance_service.database_size()

    def start_wal_checkpoint(self, mode: str = "PASSIVE") -> bool:
        self._ensure_live("wal_checkpoint")
        return self._services.maintenance_service.schedule("checkpoint", mode=mode)

    def export_metadata(self, destination: str | Path) -> LibraryExportResult:
        self._ensure_live("metadata_export")
        return self._services.export_service.export_metadata_json(
            self._session.root, destination
        )

    def create_backup(
        self,
        destination: str | Path,
        *,
        include_thumbnails: bool = False,
    ) -> LibraryBackupResult:
        self._ensure_live("backup")
        return self._services.export_service.create_backup(
            self._session.root,
            destination,
            include_thumbnails=include_thumbnails,
        )

    def validate_backup(self, archive_path: str | Path) -> BackupValidationResult:
        return self._services.export_service.validate_backup(
            archive_path,
            expected_library_root=self._session.root,
        )

    def list_restore_quarantine(self) -> tuple[RestoreQuarantineEntry, ...]:
        return self._services.export_service.list_restore_quarantine(self._session.root)

    def restore_backup(
        self,
        archive_path: str | Path,
        *,
        overwrite_existing: bool = False,
    ) -> LibraryRestoreResult:
        if not self._session.is_closed:
            raise LibrarySettingsBlockedError("restore_requires_closed_session")
        return self._services.export_service.restore_backup(
            archive_path,
            self._session.root,
            overwrite_existing=overwrite_existing,
        )

    @staticmethod
    def _integrity_error(report: IntegrityCheckReport | None) -> str | None:
        if report is None or getattr(report, "healthy", False):
            return None
        issues = tuple(str(issue) for issue in getattr(report, "issues", ()))
        if issues:
            return "; ".join(issues)
        quick_check = getattr(report, "quick_check", None)
        return str(quick_check) if quick_check else "Database integrity check failed"

    @staticmethod
    def _maintenance_error(result: object | None) -> str | None:
        if result is None:
            return None
        error = getattr(result, "error", None)
        if error:
            return str(error)
        if getattr(result, "success", True) is False:
            reason = getattr(result, "reason", None)
            return str(reason) if reason else "Database maintenance failed"
        return None

    def _ensure_live(self, operation: str) -> None:
        if self._session.is_closed:
            raise LibrarySettingsBlockedError(
                f"{operation}_requires_live_session"
            )


__all__ = [
    "LibrarySettingsAdapter",
    "LibrarySettingsBlockedError",
    "LibrarySettingsViewModel",
]
