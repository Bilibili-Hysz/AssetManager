"""Portable metadata export and safe backup validation for one library session.

The class body is split by responsibility into three mixin modules:

  library_export_service_export.py   — ExportMixin: metadata payload, backup creation
  library_export_service_validate.py — ValidateMixin: archive validation, extraction policy
  library_export_service_restore.py  — RestoreMixin: restore flow, failure state, admission

This module keeps the class identity: format/limit constants and constructor
orchestration.  ``zipfile``, ``sqlite3``, ``LibraryLock``, ``db_write_lock``,
``library_data_dir`` and ``library_lock_path`` stay in this module's
namespace — the mixins resolve them lazily through this module so tests can
monkeypatch them (see ``_export.py`` / ``_restore.py``).
"""
from __future__ import annotations

from pathlib import Path
import sqlite3  # noqa: F401  (resolved lazily by the mixins; patched in tests)
import threading
import zipfile  # noqa: F401  (resolved lazily by the mixins; patched in tests)
from typing import Callable, ContextManager

from AssetsManager.application.context import ConnectionProvider, LibrarySession
from AssetsManager.application.library_export_service_export import ExportMixin
from AssetsManager.application.library_export_service_restore import RestoreMixin
from AssetsManager.application.library_export_service_types import (
    BackupValidationResult,
    LibraryBackupResult,
    LibraryExportResult,
    LibraryRestoreResult,
    RestoreAdmissionBlockedError,
    RestoreFailureState,
    RestoreQuarantineEntry,
)
from AssetsManager.application.library_export_service_validate import ValidateMixin
from AssetsManager.core.database import db_write_lock  # noqa: F401  (patched in tests)
from AssetsManager.core.library_lock import LibraryLock  # noqa: F401  (patched in tests)
from AssetsManager.core.path_resolver import RootIdentity
from AssetsManager.core.path_resolver import (  # noqa: F401  (patched in tests)
    library_data_dir,
    library_lock_path,
)
from AssetsManager.repositories.tag_repository import TagRepository

__all__ = [
    "BackupValidationResult",
    "LibraryBackupResult",
    "LibraryExportResult",
    "LibraryExportService",
    "LibraryRestoreResult",
    "RestoreAdmissionBlockedError",
    "RestoreFailureState",
    "RestoreQuarantineEntry",
]


class LibraryExportService(ExportMixin, ValidateMixin, RestoreMixin):
    """Build metadata exports and safe RuntimeData backup archives.

    Metadata export includes only tags, notes, and URLs. Backup creation uses a
    SQLite backup snapshot for the active WAL database, excludes thumbnails by
    default, and never mutates or extracts into the live library. Validation is
    read-only and rejects unsafe archive paths and checksum mismatches.
    """
    FORMAT = "assetsmanager.metadata"
    SCHEMA_VERSION = 1
    BACKUP_FORMAT = "assetsmanager.library-backup"
    BACKUP_SCHEMA_VERSION = 1
    _BACKUP_MANIFEST = "manifest.json"
    _BACKUP_DATA_ROOT = "data"
    _RESTORE_BACKUP_ROOT = "_orphaned/restore-backups"
    # Limits are deliberately generous so large libraries (multi-GB video/model
    # assets, extensive thumbnail caches) remain backupable; the remaining hard
    # caps only guard against absurd archives and runaway member sizes.
    _MAX_ARCHIVE_MEMBERS = 100_000
    _MAX_CENTRAL_DIRECTORY_SIZE = 64 * 1024 * 1024
    _MAX_MANIFEST_FILES = _MAX_ARCHIVE_MEMBERS - 1
    # Large enough for a manifest covering the full member cap (worst-case
    # entry ~350 bytes x 100k members); the manifest is held in memory while
    # being read and parsed.
    _MAX_MANIFEST_SIZE = 64 * 1024 * 1024
    _MAX_MEMBER_SIZE = 64 * 1024 * 1024 * 1024
    _MAX_DATABASE_QUICK_CHECK_SIZE = 512 * 1024 * 1024
    # Validation quick_check scans the whole database (a full scan, not page
    # sampling), so the throwaway check connection gets a 32 MiB page cache
    # instead of the tiny default. The memory is transient - one connection
    # for one validation pass - and keeps the scan fast up to the 512 MiB
    # gate above.
    _QUICK_CHECK_CACHE_KIB = 32 * 1024
    _MAX_EXPANDED_SIZE = 512 * 1024 * 1024 * 1024
    _MAX_COMPRESSION_RATIO = 1_000
    _WINDOWS_DEVICE_NAMES = {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
        "com¹",
        "com²",
        "com³",
        "lpt¹",
        "lpt²",
        "lpt³",
    }

    def __init__(
        self,
        *,
        connection_provider: ConnectionProvider,
        session: LibrarySession | None = None,
        restore_coordinator: Callable[
            [LibrarySession, str | Path | RootIdentity], ContextManager[None]
        ]
        | None = None,
        restore_state_provider: Callable[[str | Path], object | None] | None = None,
        restore_acknowledger: Callable[[str | Path, str], object | None] | None = None,
    ) -> None:
        self._session = session
        self._tag_repository: TagRepository | None = None
        self._root_identity = None
        if isinstance(session, LibrarySession):
            expected_provider = session.connection_for
            provider_self = getattr(connection_provider, "__self__", None)
            provider_func = getattr(connection_provider, "__func__", None)
            expected_func = getattr(expected_provider, "__func__", None)
            if not (
                connection_provider == expected_provider
                or (provider_self is session and provider_func is expected_func)
            ):
                raise ValueError(
                    "LibraryExportService connection provider does not belong to "
                    "the LibrarySession"
                )
            self._connection_provider = expected_provider
            self._root_identity = session.context.root_identity
            # Restore-admission services may be constructed after a session has
            # closed; materialize the strict repository only inside a live
            # export operation.
            self._tag_repository = None
        else:
            self._connection_provider = connection_provider
        self._restore_coordinator = restore_coordinator
        self._restore_state_provider = restore_state_provider
        self._restore_acknowledger = restore_acknowledger
        self._restore_state_lock = threading.Lock()
        self._restore_failure_state: RestoreFailureState | None = None
