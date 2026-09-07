"""Root-confined final-open file snapshots shared across application layers."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from stat import S_ISREG
from typing import BinaryIO, Self

class SnapshotPathEscapeError(ValueError):
    """A snapshot candidate resolves outside its supplied root."""

    def __init__(self, path: str = "", root: str = ""):
        self.path = path
        self.root = root
        super().__init__(f"Path '{path}' escapes root '{root}'")


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def _reject_path_text(text: str) -> None:
    if _CONTROL_CHARS_RE.search(text):
        raise ValueError("Path contains control characters")
    if os.name == "nt" and ":" in text:
        raise ValueError("Path contains a stream separator")


def _assert_under_root(root: str | Path, candidate: str | Path) -> Path:
    resolved_root = Path(root).resolve()
    resolved = Path(candidate).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise SnapshotPathEscapeError(str(resolved), str(resolved_root))
    return resolved


@dataclass(frozen=True)
class FileIdentity:
    device: int
    inode: int
    size: int
    mtime_ns: int

    @classmethod
    def from_stat(cls, value: os.stat_result) -> "FileIdentity":
        return cls(value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.device, self.inode, self.size, self.mtime_ns)


class FileSnapshotError(OSError):
    """Raised when a final-open source cannot be proven stable."""


@dataclass
class OpenedFile:
    file: BinaryIO
    path: Path
    identity: FileIdentity

    @property
    def size(self) -> int:
        return self.identity.size

    def close(self) -> None:
        self.file.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args) -> None:
        self.close()


def _reject_reparse_ancestors(root: Path, target: Path) -> None:
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise SnapshotPathEscapeError(str(target), str(root)) from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise SnapshotPathEscapeError(str(current), str(root))
        if os.name == "nt":
            is_junction = getattr(current, "is_junction", None)
            if callable(is_junction) and is_junction():
                raise SnapshotPathEscapeError(str(current), str(root))
            is_mount = getattr(current, "is_mount", None)
            if callable(is_mount) and is_mount():
                raise SnapshotPathEscapeError(str(current), str(root))
            # Fail closed: an uninspectable component (including a junction
            # whose target vanished) must never be followed.
            try:
                info = os.lstat(current)
            except OSError as exc:
                raise SnapshotPathEscapeError(str(current), str(root)) from exc
            if int(getattr(info, "st_file_attributes", 0)) & 0x400:
                raise SnapshotPathEscapeError(str(current), str(root))


def _open_posix_no_follow(root: Path, target: Path) -> BinaryIO:
    # O_DIRECTORY / O_NOFOLLOW are absent from the Windows runtime and the
    # win32 typeshed stubs; the only caller is guarded by os.name == "posix"
    # (same getattr pattern as core/database.py and application/import_service.py).
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    current_fd = os.open(str(root), flags)
    try:
        parts = target.relative_to(root).parts
        if not parts:
            raise FileSnapshotError("opened path is not a regular file")
        for part in parts[:-1]:
            next_fd = os.open(part, flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        leaf_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        leaf_fd = os.open(parts[-1], leaf_flags, dir_fd=current_fd)
        try:
            return os.fdopen(leaf_fd, "rb")
        except Exception:
            os.close(leaf_fd)
            raise
    finally:
        os.close(current_fd)


def open_under_root(
    root: str | Path,
    admitted_path: str | Path,
    *,
    expected_identity: FileIdentity | tuple[int, int, int, int] | None = None,
    retries: int = 2,
) -> OpenedFile:
    root_path = Path(root).resolve()
    candidate = Path(admitted_path)
    try:
        path_text = str(candidate.relative_to(root_path)) if candidate.is_absolute() else str(candidate)
    except ValueError:
        path_text = str(candidate)
        if os.name == "nt" and candidate.anchor:
            path_text = path_text[len(candidate.anchor):]
    _reject_path_text(path_text)
    if retries < 0:
        raise ValueError("retries must be non-negative")

    for attempt in range(retries + 1):
        target = _assert_under_root(root_path, candidate)
        _reject_reparse_ancestors(root_path, target)
        try:
            if os.name == "posix":
                handle = _open_posix_no_follow(root_path, target)
            else:
                flags = os.O_RDONLY | (os.O_BINARY if hasattr(os, "O_BINARY") else 0)
                handle = os.fdopen(os.open(str(target), flags), "rb")
        except (OSError, ValueError) as exc:
            if attempt == retries:
                raise FileSnapshotError(str(exc)) from exc
            continue
        try:
            stat = os.fstat(handle.fileno())
            if not S_ISREG(stat.st_mode):
                raise FileSnapshotError("opened path is not a regular file")
            identity = FileIdentity.from_stat(stat)
            if expected_identity is not None:
                expected = expected_identity.as_tuple() if isinstance(expected_identity, FileIdentity) else tuple(expected_identity)
                if identity.as_tuple() != expected:
                    raise FileSnapshotError("file identity changed")
            final_target = _assert_under_root(root_path, target)
            _reject_reparse_ancestors(root_path, final_target)
            return OpenedFile(handle, final_target, identity)
        except Exception:
            handle.close()
            if attempt == retries:
                raise
    raise FileSnapshotError("unable to open file safely")


def read_snapshot(
    root: str | Path,
    admitted_path: str | Path,
    *,
    expected_identity: FileIdentity | tuple[int, int, int, int] | None = None,
    max_bytes: int | None = None,
) -> tuple[bytes, FileIdentity]:
    chunks = iter_snapshot(
        root,
        admitted_path,
        expected_identity=expected_identity,
        max_bytes=max_bytes,
    )
    try:
        body = b"".join(chunks)
        return body, chunks.identity
    finally:
        chunks.close()


class _SnapshotIterator:
    """Iterator that owns a final-open handle for bounded streaming reads."""

    def __init__(
        self,
        opened: OpenedFile,
        *,
        chunk_size: int,
    ) -> None:
        self._opened = opened
        self._chunk_size = chunk_size
        self._remaining = opened.size
        self.identity = opened.identity
        self._closed = False

    def __iter__(self) -> "_SnapshotIterator":
        return self

    def __next__(self) -> bytes:
        if self._closed:
            raise StopIteration
        try:
            # Never chase a growing file until EOF: both the bytes exposed
            # and memory consumed are bounded by the admitted handle size.
            chunk = self._opened.file.read(min(self._chunk_size, self._remaining))
        except Exception:
            self.close()
            raise
        if chunk:
            self._remaining -= len(chunk)
            return chunk
        try:
            current = FileIdentity.from_stat(os.fstat(self._opened.file.fileno()))
            if self._remaining or current != self._opened.identity:
                raise FileSnapshotError("file changed while being read")
        finally:
            self.close()
        raise StopIteration

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._opened.close()

    def __del__(self) -> None:
        self.close()


def iter_snapshot(
    root: str | Path,
    admitted_path: str | Path,
    *,
    expected_identity: FileIdentity | tuple[int, int, int, int] | None = None,
    max_bytes: int | None = None,
    chunk_size: int = 1024 * 1024,
) -> _SnapshotIterator:
    """Yield a root-confined snapshot in bounded chunks.

    The final-open handle remains owned by the iterator until EOF (or explicit
    ``close``), so callers such as ZIP writers never materialize an entire
    source file in memory. The opened size caps all reads, even if the source
    grows. Identity and length are checked before successful completion.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    opened = open_under_root(root, admitted_path, expected_identity=expected_identity)
    if max_bytes is not None:
        if max_bytes < 0:
            opened.close()
            raise ValueError("max_bytes must be non-negative")
        if opened.size > max_bytes:
            opened.close()
            raise FileSnapshotError("file exceeds snapshot limit")
    return _SnapshotIterator(opened, chunk_size=chunk_size)
