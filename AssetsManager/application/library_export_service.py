"""Portable metadata export and safe backup validation for one library session."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import ctypes
import hashlib
import os
import json
import unicodedata
from pathlib import Path
from pathlib import PurePosixPath
import sqlite3
from sqlite3 import Connection
import stat
import struct
import sys
import tempfile
import threading
import uuid
import zipfile
import zlib
from ctypes import wintypes
from typing import Any, BinaryIO, Callable, ContextManager, cast
from urllib.parse import quote

from AssetsManager.application.context import ConnectionProvider, LibrarySession, session_operation
from AssetsManager.core.database import DatabaseManager, db_write_lock
from AssetsManager.core.library_lock import LibraryLock
from AssetsManager.core.path_resolver import (
    RootIdentity,
    db_path,
    library_data_dir,
    library_lock_path,
    root_identity,
)
from AssetsManager.repositories.metadata_repository import MetadataRepository
from AssetsManager.repositories.tag_repository import TagRepository


_WIN32_LCMAP_LOWERCASE = 0x00000100
_WIN32_LC_MAP_STRING_EX: Any = None
if sys.platform == "win32":
    try:
        win_dll = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
        _WIN32_LC_MAP_STRING_EX = cast(Any, win_dll.LCMapStringEx)
        _WIN32_LC_MAP_STRING_EX.argtypes = [
            ctypes.c_wchar_p,
            wintypes.DWORD,
            ctypes.c_wchar_p,
            wintypes.INT,
            ctypes.c_wchar_p,
            wintypes.INT,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        _WIN32_LC_MAP_STRING_EX.restype = wintypes.INT
    except (AttributeError, OSError):
        _WIN32_LC_MAP_STRING_EX = None


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


class _BackupCancelledError(RuntimeError):
    """Cancellation signal shared by every backup-phase cancel check.

    A distinct type keeps the signal distinguishable from ordinary member
    read failures, which ``_validate_open_backup`` converts into validation
    errors instead of propagating.
    """


class LibraryExportService:
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

    @staticmethod
    def _external_state_value(state: object, name: str, default: object = None) -> object:
        if isinstance(state, dict):
            return state.get(name, default)
        return getattr(state, name, default)

    def _external_restore_state(self) -> RestoreFailureState | None:
        if self._restore_state_provider is None or self._session is None:
            return None
        external = self._restore_state_provider(self._session.root)
        if external is None or external == {}:
            return None
        secondary = self._external_state_value(external, "secondary_errors", ())
        if not isinstance(secondary, tuple):
            secondary = tuple(secondary) if isinstance(secondary, (list, set)) else ()
        generation_value = self._external_state_value(external, "generation")
        token_value = self._external_state_value(external, "token")
        generation = generation_value if isinstance(generation_value, int) else None
        token = token_value if isinstance(token_value, str) else None
        return RestoreFailureState(
            phase=str(self._external_state_value(external, "phase", "restore")),
            message=str(self._external_state_value(external, "message", "Restore recovery required")),
            secondary_errors=secondary,
            generation=generation,
            token=token,
        )

    @property
    def restore_failure_state(self) -> RestoreFailureState | None:
        """Return canonical recovery evidence, falling back to the local mirror."""
        external = self._external_restore_state()
        if external is not None:
            return external
        with self._restore_state_lock:
            return self._restore_failure_state

    def acknowledge_restore_failure(
        self, token: str | None = None
    ) -> RestoreFailureState | None:
        """Compare-and-delete canonical state, then clear the local mirror.

        A local mirror is intentionally preferred when no explicit token is
        supplied: a stale ExportService must not silently adopt and clear a
        newer process-level poison. Bootstrap-bound callers pass the recovery
        token captured from the canonical provider when they own the ACK.
        """
        with self._restore_state_lock:
            local = self._restore_failure_state
        external = self._external_restore_state()
        previous = local or external
        if self._restore_acknowledger is not None and self._session is not None:
            # A default ACK is local-only.  It must not submit a stale local
            # token to a process-global adapter, even when that adapter accepts
            # arbitrary tokens.  Only an explicit token is authority to clear
            # global state.
            if token is None:
                if external is not None:
                    return external
                with self._restore_state_lock:
                    self._restore_failure_state = None
                return previous
            acked_state = external or previous
            self._restore_acknowledger(self._session.root, token)
            remaining = self._external_restore_state()
            if remaining is not None:
                return remaining
            with self._restore_state_lock:
                self._restore_failure_state = None
            return acked_state
        with self._restore_state_lock:
            self._restore_failure_state = None
        return previous

    def _ensure_restore_admission(self) -> None:
        state = self.restore_failure_state
        if state is not None:
            raise RestoreAdmissionBlockedError(state)

    def _connection(self, library_root: str | Path) -> Connection:
        if isinstance(self._session, LibrarySession):
            requested = root_identity(library_root, strict=False)
            captured = self._root_identity
            if captured is None or requested.map_key != captured.map_key:
                raise ValueError(
                    "LibraryExportService library_root does not match the bound "
                    "LibrarySession"
                )
            return self._session.connection_for(captured)
        root = str(Path(library_root).resolve())
        conn = self._connection_provider(root)
        return DatabaseManager.validate_connection_owner(root, conn, allow_unmanaged=True)

    @session_operation
    def build_metadata_export(self, library_root: str | Path) -> dict:
        """Return a schema-versioned export payload without writing files."""
        root = Path(library_root).resolve()
        conn = self._connection(root)
        metadata_rows = MetadataRepository(conn).list_file_metadata()
        if isinstance(self._session, LibrarySession):
            tag_repository = TagRepository.for_session(self._session)
        else:
            tag_repository = TagRepository(conn)
        tag_rows = tag_repository.list_file_tags()

        metadata_by_path = {
            file_path: {"notes": notes, "urls": list(urls)}
            for file_path, notes, urls in metadata_rows
        }
        tags_by_path: dict[str, list[str]] = {}
        for file_path, tag in tag_rows:
            tags_by_path.setdefault(file_path, []).append(tag)

        entries = []
        for file_path in sorted(
            set(metadata_by_path) | set(tags_by_path),
            key=lambda path: (path.casefold(), path),
        ):
            path_value, path_type = self._portable_path(root, file_path)
            metadata = metadata_by_path.get(file_path, {"notes": "", "urls": []})
            entries.append(
                {
                    "path": path_value,
                    "path_type": path_type,
                    "tags": sorted(
                        set(tags_by_path.get(file_path, [])),
                        key=lambda tag: (tag.casefold(), tag),
                    ),
                    "notes": metadata["notes"],
                    "urls": metadata["urls"],
                }
            )

        return {
            "format": self.FORMAT,
            "schema_version": self.SCHEMA_VERSION,
            "exported_at": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "library": {
                "name": root.name or "library",
                "path_format": "relative-to-library-root",
            },
            "entries": entries,
        }

    def export_metadata_json(
        self,
        library_root: str | Path,
        destination: str | Path,
        *,
        progress: Callable[[int, int], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> LibraryExportResult:
        """Atomically write the metadata payload as UTF-8 JSON."""
        root = Path(library_root).resolve()
        if should_cancel is not None and should_cancel():
            raise RuntimeError("Metadata export cancelled")
        payload = self.build_metadata_export(root)
        target = Path(destination)
        if target.resolve(strict=False) == db_path(root).resolve(strict=False):
            raise ValueError("Export destination cannot replace the library database")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            bytes_written = temporary.stat().st_size
            temporary.replace(target)
        except BaseException:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise
        if progress is not None:
            progress(1, bytes_written)
        return LibraryExportResult(
            destination=target,
            entry_count=len(payload["entries"]),
            bytes_written=bytes_written,
        )

    @staticmethod
    def backup_filename(
        library_root: str | Path,
        now: datetime | None = None,
    ) -> str:
        """Return a timestamped default archive filename."""
        root = Path(library_root).resolve()
        timestamp = now or datetime.now(timezone.utc)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        timestamp = timestamp.astimezone(timezone.utc)
        return (
            f"{root.name or 'library'}_backup_"
            f"{timestamp.strftime('%Y%m%dT%H%M%SZ')}.assetbackup.zip"
        )

    @session_operation
    def create_backup(
        self,
        library_root: str | Path,
        destination: str | Path,
        *,
        include_thumbnails: bool = False,
        progress: Callable[[int, int], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> LibraryBackupResult:
        """Create an atomic RuntimeData archive under one complete session lease.

        The lease spans the SQLite snapshot, RuntimeData enumeration and reads,
        and manifest/ZIP publication. It only delays close/restore for this
        session; unrelated sessions and ordinary concurrent operations proceed.
        """
        root = Path(library_root).resolve()
        data_dir = library_data_dir(root)
        if not data_dir.is_dir():
            raise FileNotFoundError(data_dir)

        target = Path(destination).resolve(strict=False)
        self._validate_backup_destination(data_dir, target)
        if os.path.lexists(target):
            raise FileExistsError(
                f"Backup destination already exists, refusing to overwrite: {target}"
            )
        if should_cancel is not None and should_cancel():
            raise RuntimeError("Backup cancelled")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"

        try:
            with tempfile.TemporaryDirectory(prefix="assetsmanager-backup-") as work_dir:
                snapshot_path = Path(work_dir) / "assetmanager.db"
                self._snapshot_database(root, snapshot_path)
                manifest_files: list[dict[str, int | str]] = []
                expanded_size = 0
                backup_warnings: list[str] = []
                with zipfile.ZipFile(
                    temporary,
                    mode="w",
                    compression=zipfile.ZIP_DEFLATED,
                    compresslevel=6,
                ) as archive:
                    def add_file(
                        source: Path,
                        archive_path: str,
                        *,
                        containment_root: Path | None = None,
                        warnings: list[str] | None = None,
                    ) -> None:
                        nonlocal expanded_size
                        if should_cancel is not None and should_cancel():
                            raise RuntimeError("Backup cancelled")
                        if len(manifest_files) >= self._MAX_MANIFEST_FILES:
                            raise ValueError(
                                "Backup file count exceeds configured limit: "
                                f"{len(manifest_files)} >= {self._MAX_MANIFEST_FILES}"
                            )
                        if containment_root is not None:
                            self._assert_real_contained(
                                containment_root,
                                source,
                                kind="Backup source file",
                            )
                        entry = self._write_zip_file(
                            archive,
                            source,
                            archive_path,
                            containment_root=containment_root,
                            warnings=warnings,
                        )
                        if entry is None:
                            # Unstable source (kept changing while reading);
                            # the member was skipped and a warning recorded.
                            return
                        expanded_size += int(entry["size"])
                        if expanded_size > self._MAX_EXPANDED_SIZE:
                            raise ValueError(
                                "Backup expanded size exceeds configured limit: "
                                f"{expanded_size} > {self._MAX_EXPANDED_SIZE}"
                            )
                        manifest_files.append(entry)
                        if progress is not None:
                            progress(len(manifest_files), expanded_size)

                    add_file(
                        snapshot_path,
                        f"{self._BACKUP_DATA_ROOT}/assetmanager.db",
                    )
                    for source, archive_path in self._iter_backup_files(
                        data_dir,
                        include_thumbnails=include_thumbnails,
                    ):
                        add_file(
                            source,
                            archive_path,
                            containment_root=data_dir,
                            warnings=backup_warnings,
                        )
                    manifest = {
                        "format": self.BACKUP_FORMAT,
                        "schema_version": self.BACKUP_SCHEMA_VERSION,
                        "created_at": self._utc_timestamp(),
                        "library": {"name": root.name or "library"},
                        "includes_thumbnails": include_thumbnails,
                        "files": manifest_files,
                    }
                    manifest_bytes = (
                        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
                    ).encode("utf-8")
                    if len(manifest_bytes) > self._MAX_MANIFEST_SIZE:
                        raise ValueError("Backup manifest exceeds configured limit")
                    if expanded_size + len(manifest_bytes) > self._MAX_EXPANDED_SIZE:
                        raise ValueError(
                            "Backup expanded size exceeds configured limit: "
                            f"{expanded_size + len(manifest_bytes)} > "
                            f"{self._MAX_EXPANDED_SIZE}"
                        )
                    manifest_info = zipfile.ZipInfo(self._BACKUP_MANIFEST)
                    manifest_info.compress_type = self._compression_type_for_bytes(
                        manifest_bytes
                    )
                    archive.writestr(manifest_info, manifest_bytes)
            if should_cancel is not None and should_cancel():
                raise RuntimeError("Backup cancelled")
            generated_validation = self.validate_backup(
                temporary,
                expected_library_root=root,
                should_cancel=should_cancel,
            )
            if not generated_validation.valid:
                raise ValueError(
                    "Generated backup validation failed: "
                    + "; ".join(generated_validation.errors)
                )
            bytes_written = temporary.stat().st_size
            # Re-check immediately before publish: a file created at the
            # destination while the backup was running must not be silently
            # replaced (initial check ran before the whole backup).
            if os.path.lexists(target):
                raise FileExistsError(
                    f"Backup destination appeared during backup, refusing to overwrite: {target}"
                )
            temporary.replace(target)
        except BaseException:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise

        return LibraryBackupResult(
            destination=target,
            file_count=len(manifest_files),
            bytes_written=bytes_written,
            includes_thumbnails=include_thumbnails,
            warnings=tuple(backup_warnings),
        )

    def validate_backup(
        self,
        archive_path: str | Path,
        *,
        expected_library_root: str | Path | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> BackupValidationResult:
        """Validate a backup archive without extracting or changing any files."""
        try:
            with Path(archive_path).open("rb") as stream:
                self._preflight_archive_path(stream)
                stream.seek(0)
                with zipfile.ZipFile(stream, mode="r") as archive:
                    result, _entries = self._validate_open_backup(
                        archive,
                        expected_library_root=expected_library_root,
                        should_cancel=should_cancel,
                    )
                    return result
        except (FileNotFoundError, OSError, ValueError, zipfile.BadZipFile) as exc:
            return BackupValidationResult(
                valid=False,
                library_name=None,
                file_count=0,
                includes_thumbnails=False,
                database_quick_check=None,
                errors=(f"Cannot read backup archive: {exc}",),
            )

    def _validate_open_backup(
        self,
        archive: zipfile.ZipFile,
        *,
        expected_library_root: str | Path | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> tuple[BackupValidationResult, tuple[tuple[str, dict], ...]]:
        errors: list[str] = []
        library_name: str | None = None
        includes_thumbnails = False
        database_quick_check: str | None = None
        file_count = 0
        valid_entries: list[tuple[str, dict]] = []

        infos = archive.infolist()
        structure_errors, structure_fatal = self._archive_structure_preflight(infos)
        errors.extend(structure_errors)
        hard_member_fatal = structure_fatal and any(
            not error.startswith("Archive expanded size exceeds limit")
            for error in structure_errors
        )
        if hard_member_fatal:
            if any(error.startswith("Unsafe archive member path") for error in structure_errors):
                errors.append("Unsafe backup member path")
            if any(error.startswith("Archive contains canonical Windows path collision") for error in structure_errors):
                errors.append("Duplicate manifest file path")
                errors.append("Canonical Windows path collision")
            return (
                BackupValidationResult(False, None, 0, False, None, tuple(errors)),
                (),
            )
        info_counts: dict[str, int] = {}
        info_by_name: dict[str, zipfile.ZipInfo] = {}
        for info in infos:
            info_counts[info.filename] = info_counts.get(info.filename, 0) + 1
            info_by_name.setdefault(info.filename, info)
        if info_counts.get(self._BACKUP_MANIFEST, 0) != 1:
            errors.append("Archive must contain exactly one manifest.json")
            return (
                BackupValidationResult(False, None, 0, False, None, tuple(errors)),
                (),
            )

        try:
            manifest_bytes = self._read_archive_member(
                archive,
                info_by_name[self._BACKUP_MANIFEST],
                maximum_size=self._MAX_MANIFEST_SIZE,
            )
            manifest = json.loads(manifest_bytes)
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"Invalid backup manifest: {exc}")
            return (
                BackupValidationResult(False, None, 0, False, None, tuple(errors)),
                (),
            )

        if not isinstance(manifest, dict):
            errors.append("Backup manifest must be a JSON object")
            return (
                BackupValidationResult(False, None, 0, False, None, tuple(errors)),
                (),
            )
        if manifest.get("format") != self.BACKUP_FORMAT:
            errors.append("Unsupported backup format")
        if manifest.get("schema_version") != self.BACKUP_SCHEMA_VERSION:
            errors.append("Unsupported backup schema version")

        library = manifest.get("library")
        if isinstance(library, dict) and isinstance(library.get("name"), str):
            library_name = library["name"]
        else:
            errors.append("Backup manifest has no library name")
        if (
            expected_library_root is not None
            and library_name != Path(expected_library_root).resolve().name
        ):
            errors.append("Backup library name does not match the target library")

        includes_value = manifest.get("includes_thumbnails")
        if not isinstance(includes_value, bool):
            errors.append("Backup manifest has invalid thumbnail policy")
        else:
            includes_thumbnails = includes_value

        file_entries = manifest.get("files")
        if not isinstance(file_entries, list):
            errors.append("Backup manifest files must be a list")
            file_entries = []
        file_count = len(file_entries)
        if file_count > self._MAX_MANIFEST_FILES:
            errors.append(
                f"Backup manifest file count exceeds limit: {file_count} > "
                f"{self._MAX_MANIFEST_FILES}"
            )
            file_entries = []

        listed_names: set[str] = set()
        listed_windows_keys: set[tuple[str, ...]] = set()
        for index, entry in enumerate(file_entries):
            if not isinstance(entry, dict):
                errors.append(f"Backup file entry {index} is not an object")
                continue
            member_name = entry.get("path")
            entry_valid = True
            if not self._is_safe_backup_path(member_name):
                errors.append(f"Unsafe backup member path: {member_name!r}")
                continue
            assert isinstance(member_name, str)
            if not member_name.startswith(f"{self._BACKUP_DATA_ROOT}/"):
                errors.append(f"Backup member outside data/: {member_name!r}")
                entry_valid = False
            if member_name in listed_names:
                errors.append(f"Duplicate manifest file path: {member_name}")
                entry_valid = False
            else:
                listed_names.add(member_name)
            windows_key = self._windows_path_key(member_name)
            if windows_key in listed_windows_keys:
                errors.append(f"Canonical Windows path collision: {member_name}")
                entry_valid = False
            else:
                listed_windows_keys.add(windows_key)
            if not self._valid_file_digest(entry):
                errors.append(f"Invalid digest metadata for: {member_name}")
                entry_valid = False
            if entry_valid:
                valid_entries.append((member_name, entry))

        directory_prefixes: set[tuple[str, ...]] = set()
        for windows_key in listed_windows_keys:
            for prefix_length in range(1, len(windows_key)):
                prefix = windows_key[:prefix_length]
                if prefix in listed_windows_keys:
                    directory_prefixes.add(prefix)
        for prefix in sorted(directory_prefixes):
            errors.append(
                "Manifest file path conflicts with a directory prefix: "
                + "/".join(prefix)
            )

        archive_names = set(info_by_name)
        expected_names = listed_names | {self._BACKUP_MANIFEST}
        unexpected_names = archive_names - expected_names
        missing_names = expected_names - archive_names
        if unexpected_names:
            errors.append(
                "Unexpected backup members: " + ", ".join(sorted(unexpected_names))
            )
        if missing_names:
            errors.append("Missing backup members: " + ", ".join(sorted(missing_names)))

        # Once manifest policy is known to be invalid, the manifest is the
        # only member permitted to have been opened.  In particular, do not
        # inspect an otherwise-valid data member after unsafe/duplicate/
        # collision/digest/unexpected/missing-member evidence.
        manifest_policy_fatal = bool(errors)

        database_member = f"{self._BACKUP_DATA_ROOT}/assetmanager.db"
        database_path: Path | None = None
        expanded_size = len(manifest_bytes)
        # No member-level fatal policy violation may reach the member reader.
        # The manifest is the sole permitted read before this gate.
        if structure_fatal or manifest_policy_fatal:
            valid_entries = []
        with tempfile.TemporaryDirectory(prefix="assetsmanager-validate-") as work_dir:
            for member_name, entry in valid_entries:
                if should_cancel is not None and should_cancel():
                    raise RuntimeError("Backup cancelled")
                if info_counts.get(member_name) != 1:
                    continue
                info = info_by_name[member_name]
                is_database = member_name == database_member
                remaining = self._MAX_EXPANDED_SIZE - expanded_size
                if remaining < 0:
                    errors.append("Archive expanded size exceeds limit during validation")
                    break
                capture_to = Path(work_dir) / "assetmanager.db" if is_database else None
                try:
                    size, digest = self._inspect_archive_member(
                        archive,
                        info,
                        maximum_size=min(self._MAX_MEMBER_SIZE, remaining),
                        capture_to=capture_to,
                        should_cancel=should_cancel,
                    )
                except _BackupCancelledError:
                    raise
                except (KeyError, OSError, RuntimeError, ValueError, zipfile.BadZipFile) as exc:
                    errors.append(f"Cannot read backup member {member_name}: {exc}")
                    continue
                expanded_size += size
                if size != entry["size"]:
                    errors.append(f"Backup size mismatch: {member_name}")
                if digest != entry["sha256"]:
                    errors.append(f"Backup checksum mismatch: {member_name}")
                if is_database:
                    database_path = capture_to

            if database_member not in listed_names:
                errors.append("Backup has no assetmanager.db snapshot")
            elif database_path is not None and (
                database_path.stat().st_size > self._MAX_DATABASE_QUICK_CHECK_SIZE
            ):
                database_quick_check = "skipped"
            elif database_path is not None:
                try:
                    # Full-scan quick_check: a single synchronous PRAGMA with
                    # no progress/cancel hook, bounded by the size gate above
                    # and sped up by the enlarged validation page cache.
                    connection = sqlite3.connect(str(database_path))
                    try:
                        self._configure_quick_check_connection(connection)
                        row = connection.execute("PRAGMA quick_check").fetchone()
                    finally:
                        connection.close()
                    database_quick_check = str(row[0]) if row else "error"
                    if database_quick_check != "ok":
                        errors.append(
                            "Backup database quick_check returned: "
                            + database_quick_check
                        )
                except sqlite3.Error as exc:
                    errors.append(f"Backup database is not readable: {exc}")

        result = BackupValidationResult(
            valid=not errors,
            library_name=library_name,
            file_count=file_count,
            includes_thumbnails=includes_thumbnails,
            database_quick_check=database_quick_check,
            errors=tuple(errors),
        )
        return result, tuple(valid_entries) if result.valid else ()

    @classmethod
    def _preflight_archive_path(cls, archive_path: Path | BinaryIO) -> None:
        """Reject impossible/oversized central directories before ZipFile parsing."""
        owns_stream = isinstance(archive_path, Path)
        stream: BinaryIO = (
            archive_path.open("rb")
            if owns_stream
            else cast(BinaryIO, archive_path)
        )
        try:
            stream.seek(0, os.SEEK_END)
            length = stream.tell()
            if length < 22:
                raise zipfile.BadZipFile("ZIP archive is too small")
            tail_size = min(length, 22 + 0xFFFF)
            stream.seek(length - tail_size)
            tail = stream.read(tail_size)
            offset = tail.rfind(b"PK\x05\x06")
            if offset < 0 or offset + 22 > len(tail):
                raise zipfile.BadZipFile("ZIP end-of-central-directory record not found")
            _, disk, cd_disk, disk_count, total_count, cd_size, cd_offset, comment = struct.unpack_from(
                "<4s4H2LH", tail, offset
            )
            if disk != 0 or cd_disk != 0 or disk_count != total_count:
                raise ValueError("Multi-disk ZIP archives are not supported")
            if total_count > cls._MAX_ARCHIVE_MEMBERS:
                raise ValueError(
                    f"Archive member count exceeds limit: {total_count} > {cls._MAX_ARCHIVE_MEMBERS}"
                )
            if cd_size > cls._MAX_CENTRAL_DIRECTORY_SIZE:
                raise ValueError("Archive central directory exceeds configured limit")
            if cd_offset + cd_size > length:
                if total_count != 0xFFFF and cd_size != 0xFFFFFFFF and cd_offset != 0xFFFFFFFF:
                    raise zipfile.BadZipFile("ZIP central directory is outside the file")
            if total_count == 0xFFFF or cd_size == 0xFFFFFFFF or cd_offset == 0xFFFFFFFF:
                locator = tail.rfind(b"PK\x06\x07", 0, offset)
                if locator < 0 or locator + 20 > len(tail):
                    raise ValueError("ZIP64 central-directory preflight record is missing")
                record_offset = struct.unpack_from("<Q", tail, locator + 8)[0]
                if record_offset + 56 > length:
                    raise zipfile.BadZipFile("ZIP64 end record is outside the file")
                stream.seek(record_offset)
                record = stream.read(56)
                if record[:4] != b"PK\x06\x06":
                    raise zipfile.BadZipFile("Invalid ZIP64 end record")
                values = struct.unpack_from("<Q2H2L4Q", record, 4)
                total_count = values[6]
                cd_size = values[7]
                cd_offset = values[8]
                if total_count > cls._MAX_ARCHIVE_MEMBERS:
                    raise ValueError(
                        f"Archive member count exceeds limit: {total_count} > {cls._MAX_ARCHIVE_MEMBERS}"
                    )
                if cd_size > cls._MAX_CENTRAL_DIRECTORY_SIZE:
                    raise ValueError("Archive central directory exceeds configured limit")
                if cd_offset + cd_size > length:
                    raise zipfile.BadZipFile("ZIP64 central directory is outside the file")
        finally:
            if owns_stream:
                stream.close()

    def _archive_structure_preflight(
        self, infos: list[zipfile.ZipInfo]
    ) -> tuple[list[str], bool]:
        errors = self._archive_structure_errors(infos)
        fatal_prefixes = (
            "Archive member count exceeds",
            "Archive contains duplicate",
            "Archive contains canonical Windows path collision",
            "Unsafe archive member path",
            "Archive member is a link or special file",
            "Encrypted archive member",
            "Archive member exceeds size limit",
            "Archive expanded size exceeds limit",
            "Archive member compression ratio exceeds limit",
        )
        return errors, any(error.startswith(fatal_prefixes) for error in errors)

    def _archive_structure_errors(
        self, infos: list[zipfile.ZipInfo]
    ) -> list[str]:
        errors: list[str] = []
        if len(infos) > self._MAX_ARCHIVE_MEMBERS:
            errors.append(
                f"Archive member count exceeds limit: {len(infos)} > "
                f"{self._MAX_ARCHIVE_MEMBERS}"
            )
        names: set[str] = set()
        windows_keys: set[tuple[str, ...]] = set()
        expanded_size = 0
        expanded_limit_reported = False
        for info in infos:
            name = info.filename
            if name in names:
                errors.append(f"Archive contains duplicate member name: {name}")
            else:
                names.add(name)
            if self._is_safe_backup_path(name):
                windows_key = self._windows_path_key(name)
                if windows_key in windows_keys:
                    errors.append(f"Archive contains canonical Windows path collision: {name}")
                else:
                    windows_keys.add(windows_key)
            else:
                errors.append(f"Unsafe archive member path: {name!r}")
            mode = info.external_attr >> 16
            file_type = stat.S_IFMT(mode)
            if info.is_dir() or (file_type and not stat.S_ISREG(mode)):
                errors.append(f"Archive member is a link or special file: {name}")
            if info.flag_bits & 0x1:
                errors.append(f"Encrypted archive member is not supported: {name}")
            if info.file_size > self._MAX_MEMBER_SIZE:
                errors.append(
                    f"Archive member exceeds size limit: {name} "
                    f"({info.file_size} > {self._MAX_MEMBER_SIZE})"
                )
            expanded_size += info.file_size
            if expanded_size > self._MAX_EXPANDED_SIZE and not expanded_limit_reported:
                errors.append("Archive expanded size exceeds limit")
                expanded_limit_reported = True
            if info.file_size and (
                info.compress_size == 0
                or info.file_size / info.compress_size > self._MAX_COMPRESSION_RATIO
            ):
                errors.append(f"Archive member compression ratio exceeds limit: {name}")
        return errors

    @classmethod
    def _inspect_archive_member(
        cls,
        archive: zipfile.ZipFile,
        info: zipfile.ZipInfo,
        *,
        maximum_size: int,
        capture_to: Path | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> tuple[int, str]:
        digest = hashlib.sha256()
        size = 0
        output = capture_to.open("xb") if capture_to is not None else None
        try:
            with archive.open(info, mode="r") as stream:
                while chunk := stream.read(1024 * 1024):
                    if should_cancel is not None and should_cancel():
                        raise _BackupCancelledError("Backup cancelled")
                    size += len(chunk)
                    if size > maximum_size or size > info.file_size:
                        raise ValueError(
                            "Expanded member exceeds declared or configured size: "
                            f"{info.filename}"
                        )
                    digest.update(chunk)
                    if output is not None:
                        output.write(chunk)
        finally:
            if output is not None:
                output.close()
        if size != info.file_size:
            raise ValueError(f"Expanded member size mismatch: {info.filename}")
        if size and (
            info.compress_size == 0
            or size / info.compress_size > cls._MAX_COMPRESSION_RATIO
        ):
            raise ValueError(
                f"Actual member compression ratio exceeds limit: {info.filename}"
            )
        return size, digest.hexdigest()

    @staticmethod
    def _read_archive_member(
        archive: zipfile.ZipFile,
        info: zipfile.ZipInfo,
        *,
        maximum_size: int,
    ) -> bytes:
        if info.file_size > maximum_size:
            raise ValueError(f"Archive member exceeds configured size: {info.filename}")
        data = bytearray()
        with archive.open(info, mode="r") as stream:
            while chunk := stream.read(1024 * 1024):
                if len(data) + len(chunk) > maximum_size or len(data) + len(chunk) > info.file_size:
                    raise ValueError(
                        f"Expanded member exceeds declared or configured size: {info.filename}"
                    )
                data.extend(chunk)
        if len(data) != info.file_size:
            raise ValueError(f"Expanded member size mismatch: {info.filename}")
        return bytes(data)

    def restore_backup(
        self,
        archive_path: str | Path,
        library_root: str | Path,
        *,
        overwrite_existing: bool = False,
    ) -> LibraryRestoreResult:
        """Restore one archive while holding the service's root reservation."""
        self._ensure_restore_admission()
        if self._session is None or self._restore_coordinator is None:
            raise RuntimeError("Restore requires an injected ownership coordinator")
        identity = root_identity(library_root)
        session_context = getattr(self._session, "context", None)
        session_key = getattr(session_context, "root_key", None)
        if session_key is not None and identity.map_key != session_key:
            raise RuntimeError("Restore target does not match the bound library session")
        root = identity.display_path
        if not root.is_dir():
            raise FileNotFoundError(root)

        data_dir = library_data_dir(identity)
        target = Path(archive_path).resolve()
        staging = data_dir.parent / f".{data_dir.name}.restore-{uuid.uuid4().hex}"
        # Admission-only checks happen before the coordinator reservation. This
        # keeps missing/invalid archives and unconfirmed overwrites from being
        # interpreted as process-poisoning restore failures by older owners.
        try:
            self._preflight_archive_path(target)
            if data_dir.exists() or data_dir.is_symlink():
                if self._is_link_or_junction(data_dir):
                    raise ValueError("Refusing to replace a linked or reparse-pointed RuntimeData directory")
                if not overwrite_existing:
                    raise FileExistsError(
                        "Target RuntimeData directory exists; explicit overwrite is required"
                    )
        except BaseException as admission_error:
            self._mark_restore_error_nonpoison(admission_error)
            raise
        with self._restore_coordinator(self._session, identity):
            # A caller may have queued before an earlier restore poisoned state.
            self._ensure_restore_admission()
            try:
                lock = LibraryLock(library_lock_path(identity))
            except BaseException as lock_error:
                self._mark_restore_error_nonpoison(lock_error)
                raise
            try:
                return self._restore_under_reservation(
                    target,
                    root,
                    data_dir,
                    staging,
                    overwrite_existing=overwrite_existing,
                )
            finally:
                active_error = sys.exc_info()[1]
                try:
                    released = lock.release()
                    if not released:
                        raise RuntimeError(f"Failed to release library lock: {lock.path}")
                except BaseException as release_error:
                    self._record_restore_failure(release_error, "library lock release")
                    if active_error is None:
                        raise
                    self._add_restore_secondary_error(
                        active_error, "library lock release", release_error
                    )

    def _restore_under_reservation(
        self,
        target: Path,
        root: Path,
        data_dir: Path,
        staging: Path,
        *,
        overwrite_existing: bool,
    ) -> LibraryRestoreResult:
        previous: Path | None = None
        moved_existing = False
        installed = False
        mutation_phase: str | None = None
        archive_stream: BinaryIO | None = None
        try:
            try:
                archive_stream = target.open("rb")
                self._preflight_archive_path(archive_stream)
                archive_stream.seek(0)
                archive_context = zipfile.ZipFile(archive_stream, mode="r")
            except BaseException as exc:
                self._mark_restore_error_nonpoison(exc)
                raise
            with archive_context as archive:
                validation, entries = self._validate_open_backup(
                    archive, expected_library_root=root
                )
                if not validation.valid:
                    raise ValueError(
                        "Backup validation failed: " + "; ".join(validation.errors)
                    )
                if data_dir.exists() or data_dir.is_symlink():
                    if self._is_link_or_junction(data_dir):
                        raise ValueError("Refusing to replace a linked or reparse-pointed RuntimeData directory")
                    if not overwrite_existing:
                        raise FileExistsError(
                            "Target RuntimeData directory exists; explicit overwrite is required"
                        )

                staging.mkdir(parents=True, exist_ok=False)
                mutation_phase = "staging"
                self._extract_validated_backup(archive, staging, entries)
            if archive_stream is not None:
                try:
                    archive_stream.close()
                except BaseException as close_error:
                    archive_stream = None
                    self._record_restore_failure(close_error, mutation_phase or "staging")
                    raise
                archive_stream = None
            mutation_phase = "staging quick_check"
            self._quick_check_database_file(staging / "assetmanager.db")

            if data_dir.exists():
                mutation_phase = "quarantine"
                previous = self._restore_quarantine_path(data_dir)
                self._assert_real_contained(data_dir.parent, data_dir, kind="RuntimeData directory")
                self._assert_real_contained(data_dir.parent, previous.parent, kind="Restore quarantine directory")
                data_dir.replace(previous)
                moved_existing = True
            mutation_phase = "install"
            self._assert_real_staging_tree(staging, entries)
            self._assert_real_contained(data_dir.parent, data_dir.parent, kind="RuntimeData root directory")
            staging.replace(data_dir)
            installed = True
            mutation_phase = "installed quick_check"
            self._assert_real_contained(data_dir.parent, data_dir, kind="RuntimeData directory")
            self._quick_check_database_file(data_dir / "assetmanager.db")
            return LibraryRestoreResult(
                library_root=root,
                data_dir=data_dir,
                previous_data_dir=previous,
                file_count=validation.file_count,
            )
        except BaseException as primary_error:
            if mutation_phase is None:
                if archive_stream is not None:
                    try:
                        archive_stream.close()
                    except BaseException:
                        pass
                    archive_stream = None
                self._mark_restore_error_nonpoison(primary_error)
                raise
            # Canonical poison is established before any best-effort cleanup or
            # stream close. Cleanup success must not make a mutation failure safe.
            self._record_restore_failure(primary_error, mutation_phase)
            if archive_stream is not None:
                try:
                    archive_stream.close()
                except BaseException as close_error:
                    self._add_restore_secondary_error(
                        primary_error, "archive stream close", close_error
                    )
                finally:
                    archive_stream = None
            try:
                if installed and (data_dir.exists() or data_dir.is_symlink()):
                    self._move_to_restore_quarantine(data_dir, root, "failed-install")
                elif staging.exists() or staging.is_symlink():
                    self._move_to_restore_quarantine(staging, root, "failed-staging")
            except BaseException as quarantine_error:
                self._add_restore_secondary_error(
                    primary_error, "failed restore quarantine", quarantine_error
                )
            if (
                moved_existing
                and previous is not None
                and previous.exists()
                and not data_dir.exists()
                and not data_dir.is_symlink()
            ):
                try:
                    self._restore_previous_data(previous, data_dir)
                except BaseException as rollback_error:
                    self._add_restore_secondary_error(
                        primary_error, "previous RuntimeData rollback", rollback_error
                    )
            raise

    @classmethod
    def _restore_previous_data(cls, previous: Path, data_dir: Path) -> None:
        runtime_root = data_dir.parent
        cls._assert_real_contained(
            runtime_root, previous, kind="Rollback previous RuntimeData directory"
        )
        cls._assert_real_contained(
            runtime_root, runtime_root, kind="Rollback RuntimeData parent directory"
        )
        if cls._is_link_or_junction(previous):
            raise ValueError("Rollback previous path is a link or junction")
        if os.path.lexists(data_dir) and cls._is_link_or_junction(data_dir):
            raise ValueError("Rollback target path is a link or junction")
        cls._assert_real_contained(
            runtime_root, previous, kind="Rollback previous RuntimeData directory"
        )
        cls._assert_real_contained(
            runtime_root, data_dir.parent, kind="Rollback RuntimeData parent directory"
        )
        previous.replace(data_dir)

    @staticmethod
    def _mark_restore_error_retryable(error: BaseException) -> None:
        try:
            setattr(error, "restore_retryable", True)
        except (AttributeError, TypeError):
            pass

    @staticmethod
    def _mark_restore_error_nonpoison(error: BaseException) -> None:
        try:
            setattr(error, "restore_poison", False)
            setattr(error, "restore_recovery_required", False)
        except (AttributeError, TypeError):
            pass

    def _record_restore_failure(self, error: BaseException, phase: str) -> None:
        secondary_errors = tuple(getattr(error, "restore_secondary_errors", ()))
        existing_state = getattr(error, "restore_failure_state", None)
        if isinstance(existing_state, RestoreFailureState):
            token = existing_state.token
            generation = existing_state.generation
            canonical_phase = existing_state.phase
        else:
            token = getattr(error, "restore_token", None) or uuid.uuid4().hex
            external = self._external_restore_state()
            generation = (
                getattr(error, "restore_generation", None)
                if isinstance(getattr(error, "restore_generation", None), int)
                else (external.generation if external is not None else 0)
            )
            canonical_phase = phase
        state = RestoreFailureState(
            phase=canonical_phase,
            message=f"{type(error).__name__}: {error}",
            secondary_errors=secondary_errors,
            generation=generation,
            token=token,
        )
        with self._restore_state_lock:
            self._restore_failure_state = state
        self._mark_restore_error_retryable(error)
        try:
            setattr(error, "restore_admission_blocked", True)
            setattr(error, "restore_recovery_required", True)
            setattr(error, "restore_poison", True)
            setattr(error, "restore_failure_state", state)
            setattr(error, "restore_token", token)
            setattr(error, "restore_generation", generation)
        except (AttributeError, TypeError):
            pass

    def _add_restore_secondary_error(
        self, primary: BaseException, phase: str, secondary: BaseException
    ) -> None:
        detail = f"{phase}: {type(secondary).__name__}: {secondary}"
        existing = tuple(getattr(primary, "restore_secondary_errors", ()))
        try:
            setattr(primary, "restore_secondary_errors", (*existing, detail))
            primary.add_note(f"Restore secondary failure ({detail})")
        except (AttributeError, TypeError):
            pass
        # Preserve the canonical primary token/phase while publishing the new
        # secondary evidence; never rotate global ACK identity during cleanup.
        canonical = getattr(primary, "restore_failure_state", None)
        self._record_restore_failure(
            primary, canonical.phase if isinstance(canonical, RestoreFailureState) else phase
        )

    def list_restore_quarantine(
        self, library_root: str | Path
    ) -> tuple[RestoreQuarantineEntry, ...]:
        """List direct, non-link directories in this library's restore quarantine.

        The result is read-only and deliberately does not recurse into entries.
        The library lock is held for the complete inspection so a concurrent
        restore cannot change the set while it is being enumerated.
        """
        root = Path(library_root).resolve()
        if not root.is_dir():
            raise FileNotFoundError(root)

        data_dir = library_data_dir(root)
        lock = LibraryLock(library_lock_path(root))
        try:
            try:
                quarantine_root = self._safe_restore_quarantine_root(
                    data_dir, create_missing=False
                )
            except ValueError:
                runtime_root = data_dir.parent
                for component in (
                    runtime_root / "_orphaned",
                    runtime_root / "_orphaned" / "restore-backups",
                ):
                    if (
                        component.exists()
                        and not component.is_dir()
                        and not self._is_link_or_junction(component)
                    ):
                        return ()
                raise
            if quarantine_root is None:
                return ()

            entries: list[RestoreQuarantineEntry] = []
            for candidate in sorted(
                quarantine_root.iterdir(),
                key=lambda path: (path.name.casefold(), path.name),
            ):
                if not candidate.is_dir() or self._is_link_or_junction(candidate):
                    continue
                try:
                    canonical = candidate.resolve()
                    canonical.relative_to(quarantine_root)
                    if canonical.parent != quarantine_root:
                        continue
                    modified_at = datetime.fromtimestamp(
                        candidate.stat().st_mtime, tz=timezone.utc
                    )
                    is_empty = next(candidate.iterdir(), None) is None
                except (OSError, RuntimeError, StopIteration):
                    continue
                entries.append(
                    RestoreQuarantineEntry(
                        path=candidate,
                        name=candidate.name,
                        modified_at=modified_at,
                        is_empty=is_empty,
                    )
                )
            return tuple(entries)
        finally:
            active_error = sys.exc_info()[1]
            try:
                released = lock.release()
                if not released:
                    raise RuntimeError(f"Failed to release library lock: {lock.path}")
            except BaseException as release_error:
                if active_error is None:
                    raise
                detail = (
                    f"quarantine lock release: {type(release_error).__name__}: "
                    f"{release_error}"
                )
                existing = tuple(getattr(active_error, "restore_secondary_errors", ()))
                try:
                    setattr(active_error, "restore_secondary_errors", (*existing, detail))
                    active_error.add_note(f"Restore secondary failure ({detail})")
                except (AttributeError, TypeError):
                    pass

    @staticmethod
    def _is_link_or_junction(path: Path) -> bool:
        """Return whether *path* is a link, junction, mount, or reparse point.

        A failed lstat/attribute query is deliberately treated as unsafe.
        This helper is used as an admission check, not as a best-effort
        informational predicate.
        """
        try:
            if os.path.lexists(path) and stat.S_ISLNK(os.lstat(path).st_mode):
                return True
            is_junction = getattr(path, "is_junction", None)
            if is_junction is not None and is_junction():
                return True
            is_mount = getattr(path, "is_mount", None)
            if is_mount is not None and is_mount():
                return True
            attributes = getattr(os.lstat(path), "st_file_attributes", 0)
            return bool(attributes & 0x400)
        except (OSError, RuntimeError, ValueError):
            return True

    @classmethod
    def _assert_real_contained(cls, root: Path, candidate: Path, *, kind: str) -> Path:
        """Check canonical containment and non-reparse status immediately before use."""
        if cls._is_link_or_junction(candidate):
            raise ValueError(f"{kind} is not a real directory (link or junction): {candidate}")
        try:
            canonical_root = root.resolve(strict=True)
            canonical = candidate.resolve(strict=True)
            canonical.relative_to(canonical_root)
            if kind.endswith("file") and not candidate.is_file():
                raise ValueError(f"{kind} is not a regular file: {candidate}")
            if kind.endswith("directory") and not candidate.is_dir():
                raise ValueError(f"{kind} is not a real directory: {candidate}")
            current = candidate
            while True:
                if cls._is_link_or_junction(current):
                    raise ValueError(f"{kind} ancestor is a link or junction: {current}")
                if current == root or current.parent == current:
                    break
                current = current.parent
            return canonical
        except (OSError, RuntimeError, ValueError) as exc:
            if isinstance(exc, ValueError) and str(exc).startswith(kind):
                if "Restore quarantine" in kind and "escapes" not in str(exc):
                    raise ValueError(f"Restore quarantine escapes RuntimeData: {candidate}") from exc
                raise
            if "Restore quarantine" in kind:
                raise ValueError(f"Restore quarantine escapes RuntimeData: {candidate}") from exc
            raise ValueError(f"{kind} escapes its allowed root: {candidate}") from exc

    @classmethod
    def _assert_real_staging_tree(
        cls,
        staging: Path,
        entries: tuple[tuple[str, dict], ...],
    ) -> None:
        """Validate every staging descendant immediately before installation."""
        cls._assert_real_contained(
            staging.parent, staging, kind="Restore staging directory"
        )
        allowed_directories: set[Path] = {Path()}
        allowed_files: set[Path] = set()
        for member_name, _entry in entries:
            relative = PurePosixPath(member_name).relative_to(cls._BACKUP_DATA_ROOT)
            current = Path()
            for part in relative.parts[:-1]:
                current /= part
                allowed_directories.add(current)
            allowed_files.add(Path(*relative.parts))
        allowed = allowed_directories | allowed_files

        stack = [staging]
        while stack:
            current = stack.pop()
            cls._assert_real_contained(
                staging.parent, current, kind="Restore staging directory"
            )
            try:
                children = tuple(os.scandir(current))
            except (OSError, RuntimeError, ValueError) as exc:
                raise ValueError(
                    f"Cannot inspect restore staging directory: {current}"
                ) from exc
            for entry in children:
                child = Path(entry.path)
                try:
                    relative = child.relative_to(staging)
                except ValueError as exc:
                    raise ValueError(
                        f"Restore staging descendant escapes staging directory: {child}"
                    ) from exc
                if relative not in allowed:
                    raise ValueError(
                        f"Unexpected restore staging member: {relative}"
                    )
                if cls._is_link_or_junction(child):
                    raise ValueError(
                        f"Restore staging member is a link or junction: {child}"
                    )
                try:
                    is_directory = entry.is_dir(follow_symlinks=False)
                    is_file = entry.is_file(follow_symlinks=False)
                except OSError as exc:
                    raise ValueError(
                        f"Cannot inspect restore staging member: {child}"
                    ) from exc
                if is_directory:
                    cls._assert_real_contained(
                        staging.parent, child, kind="Restore staging directory"
                    )
                    stack.append(child)
                elif is_file:
                    cls._assert_real_contained(
                        staging.parent, child, kind="Restore staging file"
                    )
                else:
                    raise ValueError(
                        f"Restore staging member is not a regular file or directory: {child}"
                    )

        for relative in allowed_directories:
            candidate = staging / relative
            if not os.path.lexists(candidate):
                raise ValueError(f"Missing restore staging directory: {candidate}")
            cls._assert_real_contained(
                staging.parent, candidate, kind="Restore staging directory"
            )
        for relative in allowed_files:
            candidate = staging / relative
            if not os.path.lexists(candidate):
                raise ValueError(f"Missing restore staging file: {candidate}")
            cls._assert_real_contained(
                staging.parent, candidate, kind="Restore staging file"
            )

    def _extract_validated_backup(
        self,
        archive: zipfile.ZipFile,
        destination: Path,
        entries: tuple[tuple[str, dict], ...],
    ) -> None:
        infos = archive.infolist()
        policy_errors, _fatal = self._archive_structure_preflight(infos)
        if policy_errors:
            raise ValueError(
                "Backup extraction policy failed: " + "; ".join(policy_errors)
            )
        info_by_name = {info.filename: info for info in infos}
        self._assert_real_contained(destination.parent, destination, kind="Extraction destination directory")
        destination_root = destination.resolve(strict=True)
        expanded_size = 0
        seen_names: set[str] = set()
        seen_windows_keys: set[tuple[str, ...]] = set()
        for member_name, entry in entries:
            if not self._is_safe_backup_path(member_name):
                raise ValueError(
                    f"Unsafe backup member path during extraction: {member_name!r}"
                )
            windows_key = self._windows_path_key(member_name)
            if member_name in seen_names or windows_key in seen_windows_keys:
                raise ValueError(
                    f"Duplicate or colliding manifest member during extraction: {member_name}"
                )
            seen_names.add(member_name)
            seen_windows_keys.add(windows_key)
            try:
                info = info_by_name[member_name]
            except KeyError as exc:
                raise ValueError(f"Missing backup member during extraction: {member_name}") from exc
            mode = info.external_attr >> 16
            file_type = stat.S_IFMT(mode)
            if info.is_dir() or (file_type and not stat.S_ISREG(mode)):
                raise ValueError(
                    f"Archive member is a link or special file during extraction: {member_name}"
                )
            if info.file_size > self._MAX_MEMBER_SIZE:
                raise ValueError(
                    f"Archive member exceeds size limit: {member_name} "
                    f"({info.file_size} > {self._MAX_MEMBER_SIZE})"
                )
            if info.file_size and (
                info.compress_size == 0
                or info.file_size / info.compress_size > self._MAX_COMPRESSION_RATIO
            ):
                raise ValueError(
                    f"Archive member compression ratio exceeds limit: {member_name}"
                )
            relative = PurePosixPath(member_name).relative_to(self._BACKUP_DATA_ROOT)
            target = destination.joinpath(*relative.parts)
            try:
                target.resolve(strict=False).relative_to(destination_root)
            except (OSError, RuntimeError, ValueError) as exc:
                raise ValueError(
                    f"Backup member escapes staging directory: {member_name}"
                ) from exc
            current = destination
            for part in relative.parts[:-1]:
                self._assert_real_contained(destination_root, current, kind="Extraction parent directory")
                current = current / part
                if current.exists() and self._is_link_or_junction(current):
                    raise ValueError(f"Backup member parent is a link or junction: {member_name}")
                current.mkdir(exist_ok=True)
                self._assert_real_contained(destination_root, current, kind="Extraction parent directory")
                if self._is_link_or_junction(current):
                    raise ValueError(
                        f"Backup member parent is a link or junction: {member_name}"
                    )

            digest = hashlib.sha256()
            member_size = 0
            self._assert_real_contained(destination_root, target.parent, kind="Extraction parent directory")
            if target.exists():
                if self._is_link_or_junction(target):
                    raise ValueError(f"Extraction target is unsafe: {member_name}")
                raise ValueError(f"Extraction target already exists: {member_name}")
            self._assert_real_contained(
                destination_root, target.parent, kind="Extraction parent directory"
            )
            if os.path.lexists(target) and self._is_link_or_junction(target):
                raise ValueError(f"Extraction target changed before open: {member_name}")
            if target.exists():
                raise ValueError(f"Extraction target changed before open: {member_name}")
            with archive.open(info, mode="r") as source, target.open("xb") as output:
                self._assert_real_contained(
                    destination_root, target, kind="Extraction target file"
                )
                while chunk := source.read(1024 * 1024):
                    member_size += len(chunk)
                    expanded_size += len(chunk)
                    if (
                        member_size > info.file_size
                        or member_size > self._MAX_MEMBER_SIZE
                        or expanded_size > self._MAX_EXPANDED_SIZE
                    ):
                        raise ValueError(
                            f"Expanded backup member exceeds configured limits: "
                            f"{member_name} (member {member_size} > "
                            f"{self._MAX_MEMBER_SIZE} or total {expanded_size} > "
                            f"{self._MAX_EXPANDED_SIZE})"
                        )
                    digest.update(chunk)
                    output.write(chunk)
            if member_size != info.file_size or member_size != entry["size"]:
                raise ValueError(f"Backup size mismatch during extraction: {member_name}")
            if member_size and (
                info.compress_size == 0
                or member_size / info.compress_size > self._MAX_COMPRESSION_RATIO
            ):
                raise ValueError(
                    f"Actual member compression ratio exceeds limit: {member_name}"
                )
            if digest.hexdigest() != entry["sha256"]:
                raise ValueError(
                    f"Backup checksum mismatch during extraction: {member_name}"
                )

    @classmethod
    def _configure_quick_check_connection(cls, connection: Connection) -> None:
        # Full PRAGMA quick_check is kept on purpose: it is the integrity gate
        # for accepting and restoring a backup. quick_check(N) does not sample
        # N pages - N only caps how many problems are reported, so the whole
        # database is scanned either way. The enlarged page cache
        # (_QUICK_CHECK_CACHE_KIB) is the performance lever for that scan.
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA temp_store=FILE")
        connection.execute("PRAGMA mmap_size=0")
        connection.execute(f"PRAGMA cache_size=-{cls._QUICK_CHECK_CACHE_KIB}")

    @classmethod
    def _quick_check_database_file(cls, database_file: Path) -> None:
        if not database_file.is_file():
            raise FileNotFoundError(database_file)
        if database_file.stat().st_size > cls._MAX_DATABASE_QUICK_CHECK_SIZE:
            return
        try:
            connection = sqlite3.connect(str(database_file))
            try:
                cls._configure_quick_check_connection(connection)
                row = connection.execute("PRAGMA quick_check").fetchone()
            finally:
                connection.close()
        except sqlite3.DatabaseError as exc:
            # Deeply corrupted files make PRAGMA quick_check raise directly
            # ("database disk image is malformed") instead of returning a row;
            # surface it under the same ValueError contract as the verify path.
            raise ValueError(f"Restored database is not readable: {exc}") from exc
        result = str(row[0]) if row else "error"
        if result != "ok":
            raise ValueError(f"Restored database quick_check returned: {result}")

    @classmethod
    def _safe_restore_quarantine_root(
        cls, data_dir: Path, *, create_missing: bool = True
    ) -> Path | None:
        runtime_root_path = data_dir.parent
        cls._assert_real_contained(runtime_root_path, runtime_root_path, kind="RuntimeData root directory")
        runtime_root = runtime_root_path.resolve(strict=True)
        current_path = runtime_root_path
        for name in ("_orphaned", "restore-backups"):
            current_path = current_path / name
            if current_path.exists() or current_path.is_symlink():
                cls._assert_real_contained(runtime_root, current_path, kind="Restore quarantine directory")
            else:
                if not create_missing:
                    return None
                current_path.mkdir()
                cls._assert_real_contained(runtime_root, current_path, kind="Restore quarantine directory")
        # Return a canonical path only as a hint. Callers must revalidate the
        # parent/ancestors immediately before every move/open.
        return current_path.resolve(strict=True)

    @classmethod
    def _restore_quarantine_path(cls, data_dir: Path) -> Path:
        root = cls._safe_restore_quarantine_root(data_dir)
        assert root is not None
        cls._assert_real_contained(data_dir.parent, root, kind="Restore quarantine directory")
        return root / (
            f"{data_dir.name}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_"
            f"{uuid.uuid4().hex[:8]}"
        )

    @classmethod
    def _move_to_restore_quarantine(
        cls,
        source: Path,
        library_root: Path,
        label: str,
    ) -> Path:
        data_dir = library_data_dir(library_root)
        runtime_root = data_dir.parent
        cls._assert_real_contained(runtime_root, runtime_root, kind="RuntimeData root directory")
        cls._assert_real_contained(runtime_root, source, kind="Restore quarantine source directory")
        if source.parent.resolve(strict=True) != runtime_root.resolve(strict=True):
            raise ValueError(f"Restore quarantine source is not a direct RuntimeData child: {source}")
        root = cls._safe_restore_quarantine_root(data_dir)
        assert root is not None
        # Re-resolve/recheck the complete destination ancestry immediately before replace.
        cls._assert_real_contained(runtime_root, root, kind="Restore quarantine directory")
        target = root / f"{label}_{source.name}_{uuid.uuid4().hex[:8]}"
        try:
            root.resolve(strict=True).relative_to(runtime_root.resolve(strict=True))
            if cls._is_link_or_junction(root) or cls._is_link_or_junction(root.parent):
                raise ValueError(f"Restore quarantine ancestor changed: {root}")
            source.resolve(strict=True).relative_to(runtime_root.resolve(strict=True))
            if cls._is_link_or_junction(source):
                raise ValueError(f"Refusing to quarantine a link or junction: {source}")
            cls._assert_real_contained(runtime_root, source.parent, kind="Restore quarantine source parent directory")
            cls._assert_real_contained(runtime_root, root, kind="Restore quarantine directory")
            if os.path.lexists(target) and cls._is_link_or_junction(target):
                raise ValueError(f"Restore quarantine target is unsafe: {target}")
            if target.exists():
                raise ValueError(f"Restore quarantine target already exists: {target}")
            source.replace(target)
        except (OSError, RuntimeError, ValueError) as exc:
            if isinstance(exc, ValueError):
                raise
            raise ValueError(f"Restore quarantine move failed safely: {source}") from exc
        return target

    def _snapshot_database(self, library_root: Path, destination: Path) -> None:
        def snapshot() -> None:
            source = self._connection(library_root)
            with db_write_lock(source):
                # The lock is not for snapshot consistency: the SQLite backup
                # API is WAL-aware and produces a consistent copy even while
                # the live database is written. It only guards this read-only
                # open against a concurrent DatabaseManager teardown
                # (db_write_lock holds the global close gate's read side,
                # which close()/close_library() need exclusively) and raises a
                # clean error if the database was already closed. The
                # page-level copy below must stay outside the lock so a large
                # snapshot never blocks every in-process DB writer. The
                # independent read-only connection is unmanaged, so it cannot
                # trip connection-ownership checks.
                source_file = db_path(library_root)
                uri = f"file:{quote(source_file.as_posix(), safe='/:')}?mode=ro"
                read_only = sqlite3.connect(uri, uri=True, timeout=30)
            try:
                backup = sqlite3.connect(str(destination))
                try:
                    read_only.backup(backup)
                    backup.execute("PRAGMA journal_mode=DELETE")
                    backup.commit()
                finally:
                    backup.close()
            finally:
                read_only.close()

        snapshot()

    @classmethod
    def _iter_backup_files(
        cls,
        data_dir: Path,
        *,
        include_thumbnails: bool,
    ):
        """Yield only regular files canonically contained by RuntimeData.

        This deliberately uses ``scandir`` with link following disabled rather
        than ``rglob``.  A junction/reparse point must be rejected before it is
        traversed, and every yielded file is resolved again to close the
        symlink/junction race between enumeration and opening the file.
        """
        data_dir = Path(data_dir)
        cls._assert_real_contained(data_dir.parent, data_dir, kind="Backup source directory")
        canonical_root = data_dir.resolve(strict=True)

        def walk(directory: Path):
            try:
                entries = sorted(os.scandir(directory), key=lambda entry: entry.name.casefold())
            except OSError as exc:
                raise ValueError(f"Cannot enumerate backup source: {directory}") from exc
            for entry in entries:
                source = Path(entry.path)
                if cls._is_link_or_junction(source):
                    raise ValueError(
                        f"Backup source contains a link or junction: {source}"
                    )
                try:
                    canonical = source.resolve(strict=True)
                    canonical.relative_to(canonical_root)
                    current = source.parent
                    while True:
                        if cls._is_link_or_junction(current):
                            raise ValueError(f"Backup source ancestor is a link or junction: {current}")
                        if current == data_dir or current.parent == current:
                            break
                        current = current.parent
                except (OSError, RuntimeError, ValueError) as exc:
                    raise ValueError(
                        f"Backup source escapes RuntimeData: {source}"
                    ) from exc
                if entry.is_dir(follow_symlinks=False):
                    yield from walk(source)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                relative = source.relative_to(data_dir)
                if relative.name in {
                    "assetmanager.db", "assetmanager.db-wal", "assetmanager.db-shm"
                }:
                    continue
                if relative.parts and relative.parts[0] == ".thumbnails" and not include_thumbnails:
                    continue
                # Recheck after enumeration and immediately before the caller
                # opens the file; the caller performs one more check before open.
                if cls._is_link_or_junction(source):
                    raise ValueError(f"Backup source changed to a link or junction: {source}")
                try:
                    source.resolve(strict=True).relative_to(canonical_root)
                except (OSError, RuntimeError, ValueError) as exc:
                    raise ValueError(f"Backup source changed containment: {source}") from exc
                yield source, f"{cls._BACKUP_DATA_ROOT}/{relative.as_posix()}"

        yield from walk(data_dir)

    def _write_zip_file(
        self,
        archive: zipfile.ZipFile,
        source: Path,
        archive_path: str,
        *,
        containment_root: Path | None = None,
        warnings: list[str] | None = None,
    ) -> dict[str, int | str] | None:
        if self._is_link_or_junction(source):
            raise ValueError(f"Backup source changed to a link or junction: {source}")
        try:
            # Revalidate the final path and every ancestor after the generator
            # yielded it, immediately before opening the source.
            if containment_root is not None:
                self._assert_real_contained(
                    containment_root,
                    source,
                    kind="Backup source file",
                )
            source.resolve(strict=True)
            os.lstat(source)
        except (OSError, RuntimeError, ValueError, StopIteration) as exc:
            raise ValueError(f"Backup source cannot be safely opened: {source}") from exc
        with tempfile.SpooledTemporaryFile(
            max_size=8 * 1024 * 1024, mode="w+b"
        ) as staged:
            attempts = 0
            while True:
                attempts += 1
                # Every retry re-opens the path, so containment must be
                # revalidated to close the rename/symlink race before open.
                try:
                    if containment_root is not None:
                        self._assert_real_contained(
                            containment_root,
                            source,
                            kind="Backup source file",
                        )
                except (OSError, RuntimeError, ValueError) as exc:
                    raise ValueError(
                        f"Backup source cannot be safely reopened: {source}"
                    ) from exc
                digest = hashlib.sha256()
                size = 0
                compressed_size = 0
                compressor = zlib.compressobj(level=6, method=zlib.DEFLATED, wbits=-15)
                staged.seek(0)
                staged.truncate(0)
                try:
                    with source.open("rb") as input_stream:
                        # Record the identity of the file behind the opened
                        # handle so a rename-over (the path now names a
                        # different inode) is distinguishable from in-place
                        # writes detected by fstat.
                        handle_stat = os.fstat(input_stream.fileno())
                        while chunk := input_stream.read(1024 * 1024):
                            size += len(chunk)
                            if size > self._MAX_MEMBER_SIZE:
                                raise ValueError(
                                    f"Backup member exceeds size limit: "
                                    f"{archive_path} ({size} > {self._MAX_MEMBER_SIZE})"
                                )
                            digest.update(chunk)
                            staged.write(chunk)
                            compressed_size += len(compressor.compress(chunk))
                        compressed_size += len(compressor.flush())
                        read_stat = os.fstat(input_stream.fileno())
                        path_stat = source.stat()
                except OSError as exc:
                    if attempts >= 3 and warnings is not None:
                        warnings.append(
                            f"Backup source could not be read stably; skipped: "
                            f"{archive_path} ({exc})"
                        )
                        return None
                    raise ValueError(
                        f"Backup source cannot be safely read: {source}"
                    ) from exc
                # The member is stable only when the handle's file did not
                # change during the read (fstat before/after) and the path
                # still names that same file (inode, size, mtime match).
                stable = (
                    read_stat.st_ino == handle_stat.st_ino
                    and read_stat.st_size == handle_stat.st_size
                    and read_stat.st_mtime_ns == handle_stat.st_mtime_ns
                    and path_stat.st_ino == read_stat.st_ino
                    and path_stat.st_size == read_stat.st_size
                    and path_stat.st_mtime_ns == read_stat.st_mtime_ns
                )
                if stable:
                    break
                if attempts >= 3:
                    if warnings is not None:
                        warnings.append(
                            "Backup source kept changing while reading; "
                            f"skipped: {archive_path}"
                        )
                        return None
                    raise ValueError(
                        f"Backup source changed while reading: {archive_path}"
                    )
            compression_type = zipfile.ZIP_DEFLATED
            if size and (
                compressed_size == 0
                or size / compressed_size > self._MAX_COMPRESSION_RATIO
            ):
                # A highly compressible legitimate member must not be rejected
                # by the same ratio guard used for untrusted archives. Store it
                # without compression so the generated archive remains valid.
                compression_type = zipfile.ZIP_STORED
            info = zipfile.ZipInfo(archive_path)
            info.compress_type = compression_type
            staged.seek(0)
            with archive.open(info, mode="w", force_zip64=True) as output_stream:
                while chunk := staged.read(1024 * 1024):
                    output_stream.write(chunk)
        return {"path": archive_path, "size": size, "sha256": digest.hexdigest()}

    def _compression_type_for_bytes(self, data: bytes) -> int:
        """Select DEFLATE unless it would trip our compression-ratio guard."""
        if not data:
            return zipfile.ZIP_DEFLATED
        compressor = zlib.compressobj(level=6, method=zlib.DEFLATED, wbits=-15)
        compressed_size = len(compressor.compress(data)) + len(compressor.flush())
        if compressed_size == 0 or len(data) / compressed_size > self._MAX_COMPRESSION_RATIO:
            return zipfile.ZIP_STORED
        return zipfile.ZIP_DEFLATED

    @staticmethod
    def _validate_backup_destination(data_dir: Path, target: Path) -> None:
        try:
            target.relative_to(data_dir.resolve())
        except ValueError:
            return
        raise ValueError("Backup destination must be outside the library RuntimeData directory")

    @classmethod
    def _is_safe_backup_path(cls, value: object) -> bool:
        if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
            return False
        if value.startswith("/"):
            return False
        path = PurePosixPath(value)
        if path.as_posix() != value or any(part in {"", ".", ".."} for part in path.parts):
            return False
        for part in path.parts:
            if (
                any(character in '<>:"|?*' or ord(character) < 0x20 for character in part)
                or part.endswith((".", " "))
            ):
                return False
            device_stem = part.split(".", 1)[0].casefold()
            if device_stem in cls._WINDOWS_DEVICE_NAMES:
                return False
        return True

    @staticmethod
    def _windows_component_key(value: str) -> str:
        """Return a Win32 case-insensitive key without Unicode expansions.

        On Windows, ``LCMapStringEx`` with invariant lowercase tracks the
        platform's one-to-one case table, including ``Nl``/``So`` pairs that
        Python's Unicode category heuristic cannot recognize. The fallback is
        deliberately conservative so Linux test hosts do not turn ``ß`` into
        ``ss`` or ``K`` into ``k``.
        """
        mapper = _WIN32_LC_MAP_STRING_EX
        if mapper is not None:
            try:
                source_length = len(value.encode("utf-16-le")) // 2
                required = int(
                    mapper(
                        "",
                        _WIN32_LCMAP_LOWERCASE,
                        value,
                        source_length,
                        None,
                        0,
                        None,
                        None,
                        0,
                    )
                )
                if required > 0:
                    buffer = ctypes.create_unicode_buffer(required)
                    mapped = int(
                        mapper(
                            "",
                            _WIN32_LCMAP_LOWERCASE,
                            value,
                            source_length,
                            buffer,
                            required,
                            None,
                            None,
                            0,
                        )
                    )
                    if mapped > 0:
                        return "".join(buffer[:mapped])
            except (OSError, TypeError, ValueError):
                pass

        result: list[str] = []
        for character in value:
            category = unicodedata.category(character)
            name = unicodedata.name(character, "")
            lowered = character.lower()
            if (
                not category.startswith("L")
                or category == "Lt"
                or "SIGN" in name
                or "SYMBOL" in name
                or "SHARP S" in name
                or len(lowered) != 1
            ):
                result.append(character)
            else:
                result.append(lowered)
        return "".join(result)

    @classmethod
    def _windows_path_key(cls, value: str) -> tuple[str, ...]:
        return tuple(
            cls._windows_component_key(part)
            for part in PurePosixPath(value).parts
        )

    @staticmethod
    def _valid_file_digest(entry: dict) -> bool:
        size = entry.get("size")
        digest = entry.get("sha256")
        return (
            isinstance(size, int)
            and not isinstance(size, bool)
            and size >= 0
            and isinstance(digest, str)
            and len(digest) == 64
            and all(char in "0123456789abcdef" for char in digest)
        )

    @staticmethod
    def _utc_timestamp() -> str:
        return (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

    @staticmethod
    def _portable_path(root: Path, file_path: str) -> tuple[str, str]:
        raw_path = str(file_path)
        try:
            candidate = Path(raw_path).resolve(strict=False)
            relative = candidate.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            return raw_path.replace("\\", "/"), "absolute"
        return relative.as_posix(), "relative"
