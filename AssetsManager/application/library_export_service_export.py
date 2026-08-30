"""Metadata export payload and RuntimeData backup creation.

``ExportMixin`` owns the export-side orchestration: the session-bound
database connection, the schema-versioned metadata payload, atomic JSON
publication, and ZIP backup creation — SQLite snapshot, stable file staging,
the generated-archive validation gate, and the default backup filename.

Archive validation lives in ``_validate.py``; the restore flow lives in
``_restore.py``; ``library_export_service.py`` composes the three.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from sqlite3 import Connection
import tempfile
import uuid
import zipfile
import zlib
from typing import TYPE_CHECKING, Callable
from urllib.parse import quote

from AssetsManager.application.context import LibrarySession, session_operation
from AssetsManager.application.library_export_io import (
    compression_type_for_bytes,
    portable_path,
    utc_timestamp,
    validate_backup_destination,
)
from AssetsManager.application.library_export_service_types import (
    LibraryBackupResult,
    LibraryExportResult,
)
from AssetsManager.core.database import DatabaseManager
from AssetsManager.core.path_resolver import db_path, root_identity
from AssetsManager.repositories.metadata_repository import MetadataRepository
from AssetsManager.repositories.tag_repository import TagRepository

if TYPE_CHECKING:
    from AssetsManager.application.context import ConnectionProvider
    from AssetsManager.application.library_export_service_types import (
        BackupValidationResult,
    )
    from AssetsManager.core.path_resolver import RootIdentity


class ExportMixin:
    """Metadata export payload and backup archive creation."""

    if TYPE_CHECKING:
        # Host surface owned by LibraryExportService / sibling mixins.
        _session: LibrarySession | None
        _connection_provider: ConnectionProvider
        _root_identity: RootIdentity | None

        FORMAT: str
        SCHEMA_VERSION: int
        BACKUP_FORMAT: str
        BACKUP_SCHEMA_VERSION: int
        _BACKUP_MANIFEST: str
        _BACKUP_DATA_ROOT: str
        _MAX_MANIFEST_FILES: int
        _MAX_MANIFEST_SIZE: int
        _MAX_EXPANDED_SIZE: int
        _MAX_MEMBER_SIZE: int
        _MAX_COMPRESSION_RATIO: int

        def validate_backup(
            self,
            archive_path: str | Path,
            *,
            expected_library_root: str | Path | None = None,
            should_cancel: Callable[[], bool] | None = None,
        ) -> BackupValidationResult: ...

        @classmethod
        def _assert_real_contained(
            cls, root: Path, candidate: Path, *, kind: str
        ) -> Path: ...

        @staticmethod
        def _is_link_or_junction(path: Path) -> bool: ...


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
        from AssetsManager.application.library_export_service import (
            library_data_dir,
        )

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

    def _snapshot_database(self, library_root: Path, destination: Path) -> None:
        from AssetsManager.application.library_export_service import db_write_lock

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
                if relative.parts and relative.parts[0] == "undo_backups":
                    # Transient undo-restore material (copies of deleted files
                    # staged by UndoService), never library data.
                    continue
                if relative.parts and relative.parts[0] == "derivatives":
                    # Regenerable media derivatives (viewer images, posters,
                    # contact sheets, waveforms, palettes, sequence
                    # manifests) — re-derivable from the library sources, so
                    # they are not library data either.
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
        return compression_type_for_bytes(
            data, max_compression_ratio=self._MAX_COMPRESSION_RATIO
        )

    @staticmethod
    def _validate_backup_destination(data_dir: Path, target: Path) -> None:
        validate_backup_destination(data_dir, target)

    @staticmethod
    def _utc_timestamp() -> str:
        return utc_timestamp()

    @staticmethod
    def _portable_path(root: Path, file_path: str) -> tuple[str, str]:
        return portable_path(root, file_path)
