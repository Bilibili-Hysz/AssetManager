"""Result and error types shared by the split library export service.

``LibraryExportService`` is split into three responsibility mixins plus a
facade; these six frozen dataclasses and the restore-admission error are the
contract shared by every part.  The facade module re-exports them so the
public import path stays ``AssetsManager.application.library_export_service``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class LibraryExportResult:
    """Outcome of writing one metadata export file."""

    destination: Path
    entry_count: int
    bytes_written: int

@dataclass(frozen=True)
class LibraryBackupResult:
    """Outcome of writing one RuntimeData backup archive."""

    destination: Path
    file_count: int
    bytes_written: int
    includes_thumbnails: bool
    warnings: tuple[str, ...] = ()

@dataclass(frozen=True)
class BackupValidationResult:
    """Read-only validation result for a backup archive."""

    valid: bool
    library_name: str | None
    file_count: int
    includes_thumbnails: bool
    database_quick_check: str | None
    errors: tuple[str, ...] = ()

@dataclass(frozen=True)
class LibraryRestoreResult:
    """Outcome of replacing a library RuntimeData directory."""

    library_root: Path
    data_dir: Path
    previous_data_dir: Path | None
    file_count: int

@dataclass(frozen=True)
class RestoreQuarantineEntry:
    """Read-only description of one safe restore quarantine directory."""

    path: Path
    name: str
    modified_at: datetime
    is_empty: bool

@dataclass(frozen=True)
class RestoreFailureState:
    """Process-local canonical evidence that restore admission needs review.

    ``generation`` and ``token`` are optional for source compatibility with
    older direct callers, but are populated for coordinator-backed restores.
    """

    phase: str
    message: str
    secondary_errors: tuple[str, ...] = ()
    generation: int | None = None
    token: str | None = None

class RestoreAdmissionBlockedError(RuntimeError):
    """Raised until an observed unsafe restore failure is acknowledged."""

    def __init__(self, state: RestoreFailureState) -> None:
        super().__init__(
            "Restore admission is blocked after an unsafe failure; "
            "inspect restore_failure_state and acknowledge it before retrying"
        )
        self.restore_failure_state = state
