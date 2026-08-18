"""Backup archive validation, structure policy and safe extraction.

``ValidateMixin`` owns every read of an untrusted archive: central-directory
preflight, manifest and member validation with digest checks, the database
quick_check, the policy-checked extraction used by restore, and the shared
filesystem-safety predicates (link/reparse detection, canonical containment).

Export-side archive creation lives in ``_export.py``; restore orchestration
lives in ``_restore.py``; ``library_export_service.py`` composes the three.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
from sqlite3 import Connection
import stat
import tempfile
import zipfile
from typing import TYPE_CHECKING, BinaryIO, Callable

from AssetsManager.application.library_export_io import (
    _BackupCancelledError,
    archive_structure_errors,
    archive_structure_preflight,
    assert_real_contained,
    configure_quick_check_connection,
    inspect_archive_member,
    is_link_or_junction,
    is_safe_backup_path,
    preflight_archive_path,
    read_archive_member,
    valid_file_digest,
    windows_component_key,
    windows_path_key,
)
from AssetsManager.application.library_export_service_types import (
    BackupValidationResult,
)


class ValidateMixin:
    """Read-only backup validation and policy-checked archive extraction."""

    if TYPE_CHECKING:
        # Host constants owned by LibraryExportService.
        BACKUP_FORMAT: str
        BACKUP_SCHEMA_VERSION: int
        _BACKUP_MANIFEST: str
        _BACKUP_DATA_ROOT: str
        _MAX_ARCHIVE_MEMBERS: int
        _MAX_CENTRAL_DIRECTORY_SIZE: int
        _MAX_MANIFEST_FILES: int
        _MAX_MANIFEST_SIZE: int
        _MAX_MEMBER_SIZE: int
        _MAX_EXPANDED_SIZE: int
        _MAX_COMPRESSION_RATIO: int
        _MAX_DATABASE_QUICK_CHECK_SIZE: int
        _QUICK_CHECK_CACHE_KIB: int
        _WINDOWS_DEVICE_NAMES: set[str]


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
        preflight_archive_path(
            archive_path,
            max_archive_members=cls._MAX_ARCHIVE_MEMBERS,
            max_central_directory_size=cls._MAX_CENTRAL_DIRECTORY_SIZE,
        )

    def _archive_structure_preflight(
        self, infos: list[zipfile.ZipInfo]
    ) -> tuple[list[str], bool]:
        return archive_structure_preflight(
            infos,
            max_archive_members=self._MAX_ARCHIVE_MEMBERS,
            max_member_size=self._MAX_MEMBER_SIZE,
            max_expanded_size=self._MAX_EXPANDED_SIZE,
            max_compression_ratio=self._MAX_COMPRESSION_RATIO,
            windows_device_names=self._WINDOWS_DEVICE_NAMES,
        )

    def _archive_structure_errors(
        self, infos: list[zipfile.ZipInfo]
    ) -> list[str]:
        return archive_structure_errors(
            infos,
            max_archive_members=self._MAX_ARCHIVE_MEMBERS,
            max_member_size=self._MAX_MEMBER_SIZE,
            max_expanded_size=self._MAX_EXPANDED_SIZE,
            max_compression_ratio=self._MAX_COMPRESSION_RATIO,
            windows_device_names=self._WINDOWS_DEVICE_NAMES,
        )

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
        return inspect_archive_member(
            archive,
            info,
            maximum_size=maximum_size,
            max_compression_ratio=cls._MAX_COMPRESSION_RATIO,
            capture_to=capture_to,
            should_cancel=should_cancel,
        )

    @staticmethod
    def _read_archive_member(
        archive: zipfile.ZipFile,
        info: zipfile.ZipInfo,
        *,
        maximum_size: int,
    ) -> bytes:
        return read_archive_member(archive, info, maximum_size=maximum_size)

    @classmethod
    def _configure_quick_check_connection(cls, connection: Connection) -> None:
        # Full PRAGMA quick_check is kept on purpose: it is the integrity gate
        # for accepting and restoring a backup. quick_check(N) does not sample
        # N pages - N only caps how many problems are reported, so the whole
        # database is scanned either way. The enlarged page cache
        # (_QUICK_CHECK_CACHE_KIB) is the performance lever for that scan.
        configure_quick_check_connection(
            connection, quick_check_cache_kib=cls._QUICK_CHECK_CACHE_KIB
        )

    @classmethod
    def _is_safe_backup_path(cls, value: object) -> bool:
        return is_safe_backup_path(
            value, windows_device_names=cls._WINDOWS_DEVICE_NAMES
        )

    @staticmethod
    def _windows_component_key(value: str) -> str:
        """Return a Win32 case-insensitive key without Unicode expansions.

        See ``AssetsManager.application.library_export_io.windows_component_key``.
        """
        return windows_component_key(value)

    @classmethod
    def _windows_path_key(cls, value: str) -> tuple[str, ...]:
        return windows_path_key(value)

    @staticmethod
    def _valid_file_digest(entry: dict) -> bool:
        return valid_file_digest(entry)

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

    @staticmethod
    def _is_link_or_junction(path: Path) -> bool:
        """Return whether *path* is a link, junction, mount, or reparse point.

        A failed lstat/attribute query is deliberately treated as unsafe.
        This helper is used as an admission check, not as a best-effort
        informational predicate.
        """
        return is_link_or_junction(path)

    @classmethod
    def _assert_real_contained(cls, root: Path, candidate: Path, *, kind: str) -> Path:
        """Check canonical containment and non-reparse status immediately before use."""
        return assert_real_contained(root, candidate, kind=kind)
