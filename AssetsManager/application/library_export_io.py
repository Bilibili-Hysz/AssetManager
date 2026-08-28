"""Archive I/O helpers for :class:`LibraryExportService`.

Pure, instance-independent functions extracted from the export service so the
service module stays focused on orchestration.  Every function here was moved
verbatim from ``library_export_service.py``; the service class keeps thin
delegates so call sites are unchanged.  Behavior must stay identical — the
backup/restore contract tests lock these functions down.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import sqlite3
import stat
import struct
import sys
import tempfile
import unicodedata
import uuid
import zipfile
import zlib
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from sqlite3 import Connection
from typing import Any, BinaryIO, Callable, cast


class _BackupCancelledError(RuntimeError):
    """Cancellation signal shared by every backup-phase cancel check.

    A distinct type keeps the signal distinguishable from ordinary member
    read failures, which ``_validate_open_backup`` converts into validation
    errors instead of propagating.
    """


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


def preflight_archive_path(
    archive_path: Path | BinaryIO,
    *,
    max_archive_members: int,
    max_central_directory_size: int,
) -> None:
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
        if total_count > max_archive_members:
            raise ValueError(
                f"Archive member count exceeds limit: {total_count} > {max_archive_members}"
            )
        if cd_size > max_central_directory_size:
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
            if total_count > max_archive_members:
                raise ValueError(
                    f"Archive member count exceeds limit: {total_count} > {max_archive_members}"
                )
            if cd_size > max_central_directory_size:
                raise ValueError("Archive central directory exceeds configured limit")
            if cd_offset + cd_size > length:
                raise zipfile.BadZipFile("ZIP64 central directory is outside the file")
    finally:
        if owns_stream:
            stream.close()


def archive_structure_preflight(
    infos: list[zipfile.ZipInfo],
    *,
    max_archive_members: int,
    max_member_size: int,
    max_expanded_size: int,
    max_compression_ratio: int,
    windows_device_names: set[str],
) -> tuple[list[str], bool]:
    errors = archive_structure_errors(
        infos,
        max_archive_members=max_archive_members,
        max_member_size=max_member_size,
        max_expanded_size=max_expanded_size,
        max_compression_ratio=max_compression_ratio,
        windows_device_names=windows_device_names,
    )
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


def archive_structure_errors(
    infos: list[zipfile.ZipInfo],
    *,
    max_archive_members: int,
    max_member_size: int,
    max_expanded_size: int,
    max_compression_ratio: int,
    windows_device_names: set[str],
) -> list[str]:
    errors: list[str] = []
    if len(infos) > max_archive_members:
        errors.append(
            f"Archive member count exceeds limit: {len(infos)} > "
            f"{max_archive_members}"
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
        if is_safe_backup_path(name, windows_device_names=windows_device_names):
            windows_key = windows_path_key(name)
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
        if info.file_size > max_member_size:
            errors.append(
                f"Archive member exceeds size limit: {name} "
                f"({info.file_size} > {max_member_size})"
            )
        expanded_size += info.file_size
        if expanded_size > max_expanded_size and not expanded_limit_reported:
            errors.append("Archive expanded size exceeds limit")
            expanded_limit_reported = True
        if info.file_size and (
            info.compress_size == 0
            or info.file_size / info.compress_size > max_compression_ratio
        ):
            errors.append(f"Archive member compression ratio exceeds limit: {name}")
    return errors


def inspect_archive_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    maximum_size: int,
    max_compression_ratio: int,
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
        or size / info.compress_size > max_compression_ratio
    ):
        raise ValueError(
            f"Actual member compression ratio exceeds limit: {info.filename}"
        )
    return size, digest.hexdigest()


def read_archive_member(
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


def is_link_or_junction(path: Path) -> bool:
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


def assert_real_contained(root: Path, candidate: Path, *, kind: str) -> Path:
    """Check canonical containment and non-reparse status immediately before use."""
    if is_link_or_junction(candidate):
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
            if is_link_or_junction(current):
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


def assert_real_staging_tree(
    staging: Path,
    entries: tuple[tuple[str, dict], ...],
    *,
    backup_data_root: str,
) -> None:
    """Validate every staging descendant immediately before installation."""
    assert_real_contained(
        staging.parent, staging, kind="Restore staging directory"
    )
    allowed_directories: set[Path] = {Path()}
    allowed_files: set[Path] = set()
    for member_name, _entry in entries:
        relative = PurePosixPath(member_name).relative_to(backup_data_root)
        current = Path()
        for part in relative.parts[:-1]:
            current /= part
            allowed_directories.add(current)
        allowed_files.add(Path(*relative.parts))
    allowed = allowed_directories | allowed_files

    stack = [staging]
    while stack:
        current = stack.pop()
        assert_real_contained(
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
            if is_link_or_junction(child):
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
                assert_real_contained(
                    staging.parent, child, kind="Restore staging directory"
                )
                stack.append(child)
            elif is_file:
                assert_real_contained(
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
        assert_real_contained(
            staging.parent, candidate, kind="Restore staging directory"
        )
    for relative in allowed_files:
        candidate = staging / relative
        if not os.path.lexists(candidate):
            raise ValueError(f"Missing restore staging file: {candidate}")
        assert_real_contained(
            staging.parent, candidate, kind="Restore staging file"
        )


def configure_quick_check_connection(connection: Connection, *, quick_check_cache_kib: int) -> None:
    # Full PRAGMA quick_check is kept on purpose: it is the integrity gate
    # for accepting and restoring a backup. quick_check(N) does not sample
    # N pages - N only caps how many problems are reported, so the whole
    # database is scanned either way. The enlarged page cache is the
    # performance lever for that scan.
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA temp_store=FILE")
    connection.execute("PRAGMA mmap_size=0")
    connection.execute(f"PRAGMA cache_size=-{quick_check_cache_kib}")


def quick_check_database_file(
    database_file: Path,
    *,
    max_database_quick_check_size: int,
    quick_check_cache_kib: int,
) -> None:
    if not database_file.is_file():
        raise FileNotFoundError(database_file)
    if database_file.stat().st_size > max_database_quick_check_size:
        return
    try:
        connection = sqlite3.connect(str(database_file))
        try:
            configure_quick_check_connection(
                connection, quick_check_cache_kib=quick_check_cache_kib
            )
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


def safe_restore_quarantine_root(
    data_dir: Path, *, create_missing: bool = True
) -> Path | None:
    runtime_root_path = data_dir.parent
    assert_real_contained(runtime_root_path, runtime_root_path, kind="RuntimeData root directory")
    runtime_root = runtime_root_path.resolve(strict=True)
    current_path = runtime_root_path
    for name in ("_orphaned", "restore-backups"):
        current_path = current_path / name
        if current_path.exists() or current_path.is_symlink():
            assert_real_contained(runtime_root, current_path, kind="Restore quarantine directory")
        else:
            if not create_missing:
                return None
            current_path.mkdir()
            assert_real_contained(runtime_root, current_path, kind="Restore quarantine directory")
    # Return a canonical path only as a hint. Callers must revalidate the
    # parent/ancestors immediately before every move/open.
    return current_path.resolve(strict=True)


def restore_quarantine_path(data_dir: Path) -> Path:
    root = safe_restore_quarantine_root(data_dir)
    assert root is not None
    assert_real_contained(data_dir.parent, root, kind="Restore quarantine directory")
    return root / (
        f"{data_dir.name}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_"
        f"{uuid.uuid4().hex[:8]}"
    )


# ── Interrupted-restore intent marker ────────────────────────────
#
# The two-step swap (quarantine previous, install staging) has a crash
# window between the replaces where the live data_dir slot is absent and
# the previous copy sits in quarantine.  Without durable evidence on disk
# the next open silently materializes an empty database.  The intent
# marker is written after the quarantine entry path is known and before
# the first replace; it lives as a sibling of data_dir so it survives
# data_dir being moved away.


def restore_intent_path(data_dir: Path) -> Path:
    return data_dir.parent / f".{data_dir.name}.restore-intent.json"


def write_restore_intent(
    data_dir: Path,
    *,
    map_key: str,
    quarantine_entry: Path,
    staging: Path,
) -> str:
    """Atomically persist restore intent; returns the intent token."""
    token = uuid.uuid4().hex
    payload = {
        "version": 1,
        "token": token,
        "map_key": map_key,
        "data_dir_name": data_dir.name,
        "quarantine_entry": str(quarantine_entry),
        "staging": str(staging),
        "started_utc": datetime.now(timezone.utc).isoformat(),
    }
    path = restore_intent_path(data_dir)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".restore-intent-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return token


def read_restore_intent(data_dir: Path) -> dict[str, Any] | None:
    """Return parsed intent payload, or None when absent/unreadable/corrupt.

    A corrupt file deliberately reads as None while the bytes stay on disk:
    callers distinguish "no marker" from "marker present but unusable" via
    :func:`restore_intent_path` existence before trusting this result.
    """
    try:
        text = restore_intent_path(data_dir).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def clear_restore_intent(data_dir: Path) -> None:
    restore_intent_path(data_dir).unlink(missing_ok=True)


# Corrupt markers are isolated, never deleted: the sentinel file is renamed
# in place with this tag so the original bytes stay on disk as evidence.
# The renamed name keeps the ``.{name}.restore-intent`` prefix, so the
# LibraryService residue sweep (which only archives stale staging
# directories and removes ``.tmp`` files) deliberately skips it, and
# :func:`quarantined_restore_intent_marker` lets a later open keep failing
# closed for a still-missing slot instead of silently materializing an
# empty database.
_RESTORE_INTENT_CORRUPT_TAG = ".corrupt-"


def quarantine_restore_intent_marker(data_dir: Path) -> Path:
    """Isolate a corrupt intent marker by renaming it in place.

    Returns the new (evidence) path.  Raises OSError when the rename fails
    so callers can keep the open fail-closed instead of losing the marker
    guard without having restored anything.
    """
    path = restore_intent_path(data_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for _attempt in range(8):
        candidate = path.with_name(
            f"{path.name}{_RESTORE_INTENT_CORRUPT_TAG}{stamp}_{uuid.uuid4().hex[:8]}"
        )
        if os.path.lexists(candidate):
            continue
        os.replace(path, candidate)
        return candidate
    raise OSError(f"Cannot quarantine corrupt restore-intent marker: {path}")


def quarantined_restore_intent_marker(data_dir: Path) -> Path | None:
    """Return the newest quarantined corrupt intent marker, or None.

    Only regular siblings matching the :func:`quarantine_restore_intent_marker`
    naming convention count; links and anything unstatable are ignored.
    """
    prefix = restore_intent_path(data_dir).name + _RESTORE_INTENT_CORRUPT_TAG
    try:
        entries = list(data_dir.parent.iterdir())
    except OSError:
        return None
    newest: tuple[float, Path] | None = None
    for entry in entries:
        if not entry.name.startswith(prefix):
            continue
        try:
            if entry.is_symlink() or not entry.is_file():
                continue
            modified = entry.stat().st_mtime
        except OSError:
            continue
        if newest is None or modified > newest[0]:
            newest = (modified, entry)
    return newest[1] if newest is not None else None


def compression_type_for_bytes(data: bytes, *, max_compression_ratio: int) -> int:
    """Select DEFLATE unless it would trip our compression-ratio guard."""
    if not data:
        return zipfile.ZIP_DEFLATED
    compressor = zlib.compressobj(level=6, method=zlib.DEFLATED, wbits=-15)
    compressed_size = len(compressor.compress(data)) + len(compressor.flush())
    if compressed_size == 0 or len(data) / compressed_size > max_compression_ratio:
        return zipfile.ZIP_STORED
    return zipfile.ZIP_DEFLATED


def validate_backup_destination(data_dir: Path, target: Path) -> None:
    try:
        target.relative_to(data_dir.resolve())
    except ValueError:
        return
    raise ValueError("Backup destination must be outside the library RuntimeData directory")


def is_safe_backup_path(value: object, *, windows_device_names: set[str]) -> bool:
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
        if device_stem in windows_device_names:
            return False
    return True


def windows_component_key(value: str) -> str:
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


def windows_path_key(value: str) -> tuple[str, ...]:
    return tuple(
        windows_component_key(part)
        for part in PurePosixPath(value).parts
    )


def valid_file_digest(entry: dict) -> bool:
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


def utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def portable_path(root: Path, file_path: str) -> tuple[str, str]:
    raw_path = str(file_path)
    try:
        candidate = Path(raw_path).resolve(strict=False)
        relative = candidate.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return raw_path.replace("\\", "/"), "absolute"
    return relative.as_posix(), "relative"
