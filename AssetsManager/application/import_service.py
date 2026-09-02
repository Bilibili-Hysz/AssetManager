"""Explicit import service for bringing external assets into a library.

Importing is deliberately distinct from the in-library ``copy_to_directory``
operation: import walks directory trees from outside (or inside) the library
and reports a single ``FileSystemChanged(kind='import')`` event for the whole
batch, so a large directory import does not flood the event bus with one
``copied`` event per file.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Mapping, cast
from uuid import uuid4

from AssetsManager.application.file_operation_service import unique_destination
from AssetsManager.application.context import LibrarySession, session_operation
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import FileSystemChanged

ProgressCallback = Callable[[int, int], None]
CancelCheck = Callable[[], bool]


# Import is a user-facing filesystem boundary.  Keep the defaults generous
# enough for a normal photo/video library, while making an accidental (or
# hostile) recursive source finite before any destination file is created.
DEFAULT_IMPORT_MAX_FILES = 100_000
DEFAULT_IMPORT_MAX_TOTAL_BYTES = 512 * 1024**3
DEFAULT_IMPORT_MAX_FILE_BYTES = 64 * 1024**3
DEFAULT_IMPORT_MAX_DEPTH = 64


@dataclass(frozen=True, slots=True)
class ImportBudget:
    """Bound the planning phase of one import.

    ``max_depth`` counts directories below each directory source (a file
    directly inside the source directory is depth 0).  A value of ``0``
    therefore permits direct children but rejects nested directories.  The
    limits are deliberately per-call/per-service and are not persisted in a
    manifest, so changing policy cannot make an existing intent unreadable.
    """

    max_files: int = DEFAULT_IMPORT_MAX_FILES
    max_total_bytes: int = DEFAULT_IMPORT_MAX_TOTAL_BYTES
    max_file_bytes: int = DEFAULT_IMPORT_MAX_FILE_BYTES
    max_depth: int = DEFAULT_IMPORT_MAX_DEPTH

    def __post_init__(self) -> None:
        for name in ("max_files", "max_total_bytes", "max_file_bytes", "max_depth"):
            value = getattr(self, name)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                raise ValueError(f"{name} must be a non-negative integer")
        if self.max_files == 0:
            raise ValueError("max_files must be positive")
        if self.max_total_bytes == 0:
            raise ValueError("max_total_bytes must be positive")
        if self.max_file_bytes == 0:
            raise ValueError("max_file_bytes must be positive")


# ``ImportLimits`` was the name used in the design notes; keep it as a public
# alias so integrations can adopt the budget without a needless migration.
ImportLimits = ImportBudget


class ImportBudgetExceeded(OSError):
    """Raised while planning when an import budget would be exceeded."""

    def __init__(
        self,
        limit: str,
        observed: int,
        maximum: int,
        *,
        scanned_files: int = 0,
        scanned_bytes: int = 0,
    ) -> None:
        self.limit = limit
        self.observed = int(observed)
        self.maximum = int(maximum)
        self.scanned_files = int(scanned_files)
        self.scanned_bytes = int(scanned_bytes)
        super().__init__(
            f"import budget exceeded for {limit}: {self.observed} > {self.maximum}"
        )


class _BudgetReader:
    """File-like adapter enforcing copy-time byte ceilings.

    The scan is only a snapshot; a source can grow before or during copying.
    This adapter keeps the hard boundary on bytes actually read, including
    imports without a manifest store and replay of legacy manifests.
    """

    def __init__(
        self,
        handle,
        *,
        max_file_bytes: int,
        max_total_bytes: int,
        total_before: int,
    ) -> None:
        self._handle = handle
        self._max_file_bytes = max_file_bytes
        self._max_total_bytes = max_total_bytes
        self._total_before = total_before
        self.file_bytes = 0

    def read(self, size: int = -1):
        if size is None or size < 0:
            size = 1024 * 1024
        file_remaining = self._max_file_bytes - self.file_bytes
        total_remaining = self._max_total_bytes - self._total_before - self.file_bytes
        allowed = min(int(size), file_remaining, total_remaining)
        if allowed < 0:
            allowed = 0
        # Probe one byte beyond the boundary.  If it exists, raise before any
        # over-budget byte reaches the destination stream.
        probe = self._handle.read(allowed + 1)
        if len(probe) > allowed:
            if file_remaining <= total_remaining:
                raise ImportBudgetExceeded(
                    "max_file_bytes",
                    self.file_bytes + len(probe),
                    self._max_file_bytes,
                    scanned_files=0,
                    scanned_bytes=self._total_before + self.file_bytes,
                )
            raise ImportBudgetExceeded(
                "max_total_bytes",
                self._total_before + self.file_bytes + len(probe),
                self._max_total_bytes,
                scanned_files=0,
                scanned_bytes=self._total_before + self.file_bytes,
            )
        self.file_bytes += len(probe)
        return probe

    def __getattr__(self, name: str):
        return getattr(self._handle, name)


def _reject_link_or_reparse_ancestors(
    root: Path,
    candidate: Path,
) -> None:
    """Reject existing link/reparse components below a session root.

    Missing trailing directories are allowed so the caller can create a new
    destination tree. The session root itself is the trust anchor and is not
    inspected, preserving its existing lexical alias contract.
    """
    root_lexical = Path(os.path.abspath(str(root)))
    candidate_lexical = Path(os.path.abspath(str(candidate)))
    try:
        relative = candidate_lexical.relative_to(root_lexical)
    except ValueError as exc:
        raise OSError(
            f"Import path escapes the session root: {candidate}"
        ) from exc

    current = root_lexical
    for part in relative.parts:
        current /= part
        try:
            try:
                info = os.lstat(current)
            except FileNotFoundError:
                # Missing trailing directories are allowed so the caller can
                # create a new destination tree.
                break
            # Platform difference: the previous existence probe used
            # os.path.lexists(), which maps *any* lstat error to False on
            # POSIX (ntpath propagates it), so an ancestor whose metadata
            # could not be inspected (EACCES, EIO, ...) silently became a
            # "missing" component and failed open on Linux. Probing with
            # os.lstat directly keeps the inspection fail-closed: only a
            # genuinely missing component breaks, every other OSError
            # propagates like on Windows.
            if stat.S_ISLNK(info.st_mode):
                raise OSError(f"Import path passes through a symlink: {current}")
            if os.name == "nt":
                is_junction = getattr(current, "is_junction", None)
                if callable(is_junction) and is_junction():
                    raise OSError(f"Import path passes through a junction: {current}")
                is_mount = getattr(current, "is_mount", None)
                if callable(is_mount) and is_mount():
                    raise OSError(f"Import path passes through a mount: {current}")
                if int(getattr(info, "st_file_attributes", 0)) & 0x400:
                    raise OSError(
                        f"Import path passes through a reparse point: {current}"
                    )
            if not stat.S_ISDIR(info.st_mode):
                raise OSError(f"Import path component is not a directory: {current}")
        except (OSError, RuntimeError, ValueError):
            raise
        except Exception as exc:
            raise OSError(f"Unable to inspect import path component: {current}") from exc


class ImportCancelled(Exception):
    """Raised when an import observes its cancellation check returning True."""

    def __init__(self, partial_result: "ImportResult | None" = None) -> None:
        super().__init__("Import cancelled")
        self.partial_result = partial_result


@dataclass
class ImportResult:
    """Outcome of one import_sources() call."""

    copied: int
    skipped: int
    failed: list[str] = field(default_factory=list)
    processed: int = 0
    total: int = 0
    degraded: bool = False
    cancelled: bool = False
    operation_id: str | None = None
    refresh_warnings: tuple[object, ...] = ()
    budget_exceeded: bool = False
    budget_limit: str | None = None
    budget_observed: int | None = None
    budget_maximum: int | None = None
    scanned_files: int = 0
    scanned_bytes: int = 0

    @property
    def files_scanned(self) -> int:
        """Compatibility/readability alias for callers using noun-first names."""
        return self.scanned_files

    @property
    def bytes_scanned(self) -> int:
        return self.scanned_bytes


@dataclass(frozen=True, slots=True)
class RecoveryEnqueueOutcome:
    """Result of handing an import recovery intent to the durable queue.

    ``task_id`` is present only when the queue returned an asynchronous task
    and the manifest was successfully bound to it.  ``bool(outcome)`` keeps
    legacy callers/fakes working while allowing import completion logic to
    distinguish an ACK-gated hand-off from an old synchronous adapter.
    """

    accepted: bool
    task_id: str | None = None

    def __bool__(self) -> bool:
        return self.accepted


class ImportService:
    """Import files/folders into a destination inside an open library session.

    The service owns the batch boundary: it validates sources/destination,
    expands directory sources into (source, relative-path) pairs preserving
    the directory structure (skipping dot-prefixed entries), copies each file
    with name-conflict renaming, and emits exactly one
    ``FileSystemChanged(kind='import')`` event on completion.
    """

    def __init__(
        self,
        session: LibrarySession,
        file_operations,
        budget: ImportBudget | None = None,
    ) -> None:
        self.session = session
        self.file_operations = file_operations
        self.budget = budget or ImportBudget()

    # ── helpers ────────────────────────────────────────────────

    @classmethod
    def _collect_files(
        cls,
        sources: list[str | Path],
        should_cancel: CancelCheck | None = None,
        budget: ImportBudget | None = None,
    ) -> list[tuple[Path, Path]]:
        """Expand sources into (source, relative-path) pairs, skipping dot entries.

        Directory sources are walked recursively with ``os.scandir``; each
        file keeps its path relative to the directory source so the imported
        tree structure is preserved.  File sources get an empty relative path.
        """
        limits = budget or ImportBudget()
        collected: list[tuple[Path, Path]] = []
        total_bytes = 0

        def _is_reparse(info: os.stat_result) -> bool:
            return os.name == "nt" and bool(
                int(getattr(info, "st_file_attributes", 0)) & 0x400
            )

        def _regular_stat(path: Path) -> os.stat_result:
            """lstat one source component and reject links/reparse points."""
            try:
                info = os.lstat(path)
            except FileNotFoundError:
                raise
            except OSError:
                # Do not turn an inaccessible source into an apparent empty
                # directory.  The caller reports this as a degraded import.
                raise
            if stat.S_ISLNK(info.st_mode):
                raise OSError(f"{path}: source symlink is not allowed")
            if _is_reparse(info):
                raise OSError(f"{path}: source reparse point is not allowed")
            return info

        def _record_file(path: Path, relative: Path, info: os.stat_result) -> None:
            nonlocal total_bytes
            if not stat.S_ISREG(info.st_mode):
                raise OSError(f"{path}: source is not a regular file")
            size = int(info.st_size)
            if size < 0:
                raise OSError(f"{path}: source has an invalid size")
            if size > limits.max_file_bytes:
                raise ImportBudgetExceeded(
                    "max_file_bytes", size, limits.max_file_bytes,
                    scanned_files=len(collected), scanned_bytes=total_bytes,
                )
            next_total = total_bytes + size
            if next_total > limits.max_total_bytes:
                raise ImportBudgetExceeded(
                    "max_total_bytes", next_total, limits.max_total_bytes,
                    scanned_files=len(collected), scanned_bytes=total_bytes,
                )
            next_count = len(collected) + 1
            if next_count > limits.max_files:
                raise ImportBudgetExceeded(
                    "max_files", next_count, limits.max_files,
                    scanned_files=len(collected), scanned_bytes=total_bytes,
                )
            total_bytes = next_total
            collected.append((path, relative))

        def walk_dir(directory: Path, base: Path, depth: int) -> None:
            _regular_stat(directory)
            with os.scandir(directory) as it:
                for entry in it:
                    if should_cancel is not None and should_cancel():
                        raise ImportCancelled()
                    if entry.name.startswith("."):
                        continue
                    path = Path(entry.path)
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except OSError:
                        raise
                    if stat.S_ISLNK(info.st_mode) or _is_reparse(info):
                        raise OSError(f"{path}: source link/reparse point is not allowed")
                    if stat.S_ISDIR(info.st_mode):
                        if depth >= limits.max_depth:
                            raise ImportBudgetExceeded(
                                "max_depth", depth + 1, limits.max_depth,
                                scanned_files=len(collected), scanned_bytes=total_bytes,
                            )
                        walk_dir(path, base, depth + 1)
                    elif stat.S_ISREG(info.st_mode):
                        _record_file(path, path.relative_to(base), info)
                    else:
                        # Devices, sockets and fifos are never importable.  A
                        # special file must not be opened as if it were bytes.
                        raise OSError(f"{path}: source is not a regular file")

        for source in sources:
            if should_cancel is not None and should_cancel():
                raise ImportCancelled()
            src = Path(source)
            info = _regular_stat(src)
            if stat.S_ISDIR(info.st_mode):
                walk_dir(src, src, 0)
            elif stat.S_ISREG(info.st_mode):
                _record_file(src, Path(), info)
            else:
                raise OSError(f"{src}: source is not a regular file or directory")
        return collected

    @staticmethod
    def _under_root(path: str | Path, root: str | Path) -> bool:
        # application-layer containment check (the LAN PathGuard lives in the
        # lan layer, which application must not import).
        try:
            Path(path).resolve().relative_to(Path(root).resolve())
            return True
        except ValueError:
            return False

    def _read_source(self, src: Path):
        """Open a source for reading; injectable seam for fault tests."""
        return open(src, "rb")

    def _source_fingerprint(
        self,
        src: Path,
        *,
        budget: ImportBudget | None = None,
        total_bytes_before: int = 0,
    ) -> dict[str, object]:
        """Read a stable content fingerprint for one regular source file."""
        before = os.lstat(src)
        if stat.S_ISLNK(before.st_mode):
            raise OSError(f"{src}: source symlink is not allowed")
        if os.name == "nt" and int(getattr(before, "st_file_attributes", 0)) & 0x400:
            raise OSError(f"{src}: source reparse point is not allowed")
        if not stat.S_ISREG(before.st_mode):
            raise OSError(f"{src}: source is not a regular file")
        digest = hashlib.sha256()
        size = 0
        with self._read_source(src) as handle:
            reader = handle
            budget_reader: _BudgetReader | None = None
            if budget is not None:
                budget_reader = _BudgetReader(
                    handle,
                    max_file_bytes=budget.max_file_bytes,
                    max_total_bytes=budget.max_total_bytes,
                    total_before=total_bytes_before,
                )
                reader = budget_reader
            while chunk := reader.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
            after_handle = os.fstat(handle.fileno())
        after_path = os.lstat(src)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after_handle.st_dev,
            after_handle.st_ino,
            after_handle.st_size,
            after_handle.st_mtime_ns,
        ) or (
            after_path.st_dev,
            after_path.st_ino,
            after_path.st_size,
            after_path.st_mtime_ns,
        ) != (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ):
            raise OSError(f"{src}: source changed while fingerprinting")
        return {
            "size": size,
            "mtime_ns": int(before.st_mtime_ns),
            "sha256": digest.hexdigest(),
            # Device/inode are optional in persisted manifests for backwards
            # compatibility, but new intents record them to close the
            # same-size/same-mtime replacement race.
            "device": int(before.st_dev),
            "inode": int(before.st_ino),
        }

    def _replay_target_fingerprint(
        self,
        target: Path,
        *,
        budget: ImportBudget | None = None,
        total_bytes_before: int = 0,
    ) -> dict[str, object]:
        """Fingerprint an existing replay target without following links."""
        root = Path(self.session.root).resolve()
        _reject_link_or_reparse_ancestors(root, target.parent)
        if not os.path.lexists(target):
            raise FileNotFoundError(str(target))
        info = os.lstat(target)
        if stat.S_ISLNK(info.st_mode):
            raise OSError(f"{target}: replay target is a symlink")
        if os.name == "nt" and int(getattr(info, "st_file_attributes", 0)) & 0x400:
            raise OSError(f"{target}: replay target is a reparse point")
        if not stat.S_ISREG(info.st_mode):
            raise OSError(f"{target}: replay target is not a regular file")
        return self._source_fingerprint(
            target,
            budget=budget,
            total_bytes_before=total_bytes_before,
        )

    @staticmethod
    def _fingerprints_match(
        current: Mapping[str, object], expected: Mapping[str, object]
    ) -> bool:
        """Compare required fingerprint fields plus any identity fields present.

        v2 manifests created before device/inode hardening are still valid;
        requiring the new keys unconditionally would make every such intent
        look like a source replacement on replay.
        """
        for key in ("size", "mtime_ns", "sha256"):
            if current.get(key) != expected.get(key):
                return False
        for key in ("device", "inode"):
            if key in expected and current.get(key) != expected.get(key):
                return False
        return True

    def _copy_one(
        self,
        src: Path,
        rel: Path,
        destination_dir: Path,
        target: Path | None = None,
        *,
        expected_fingerprint: Mapping[str, object] | None = None,
        budget: ImportBudget | None = None,
        total_bytes_before: int = 0,
        total_bytes_counter: list[int] | None = None,
    ) -> Path:
        """Copy one file through an exclusive-create write boundary.

        The target is materialized with ``O_CREAT|O_EXCL`` so a rival file
        that appears after planning is never overwritten, and a dangling
        symlink at the planned path is rejected instead of followed. Cleanup
        removes only a target this call created inside the verified planned
        directory; an escaped resolution is left untouched rather than
        deleting through an unknown external path.
        """
        session_root = Path(self.session.root).resolve()
        _reject_link_or_reparse_ancestors(session_root, destination_dir)
        target_dir = destination_dir / rel.parent
        _reject_link_or_reparse_ancestors(session_root, target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        _reject_link_or_reparse_ancestors(session_root, target_dir)
        target = target or unique_destination(target_dir / src.name)
        target = Path(target)
        target_parent = target.parent
        _reject_link_or_reparse_ancestors(session_root, target_parent)
        if os.path.lexists(target):
            raise FileExistsError(str(target))
        expected_parent = Path(os.path.realpath(target_parent))
        created_fd: int | None = None
        verify_fd: int | None = None
        target_dir_fd: int | None = None
        created_identity: tuple[int, int] | None = None
        copied_bytes_this_item = 0
        owned = False
        escaped = False

        def path_is_ours() -> bool:
            if created_identity is None:
                return False
            try:
                current = os.stat(str(target), follow_symlinks=False)
            except OSError:
                return False
            return (current.st_dev, current.st_ino) == created_identity

        try:
            # Validate the lexical source immediately before opening it.  The
            # handle identity check below catches a replacement between this
            # lstat and open; O_NOFOLLOW (where available) additionally makes
            # a last-component symlink fail closed at the kernel boundary.
            source_path_stat = os.lstat(src)
            if stat.S_ISLNK(source_path_stat.st_mode):
                raise OSError(f"{src}: source symlink is not allowed")
            if os.name == "nt" and int(
                getattr(source_path_stat, "st_file_attributes", 0)
            ) & 0x400:
                raise OSError(f"{src}: source reparse point is not allowed")
            if not stat.S_ISREG(source_path_stat.st_mode):
                raise OSError(f"{src}: source is not a regular file")
            with self._read_source(src) as source_handle:
                opened_source_stat = os.fstat(source_handle.fileno())
                if not stat.S_ISREG(opened_source_stat.st_mode):
                    raise OSError(f"{src}: opened source is not a regular file")
                expected_identity = (
                    expected_fingerprint.get("device"),
                    expected_fingerprint.get("inode"),
                ) if expected_fingerprint is not None else (None, None)
                if (opened_source_stat.st_dev, opened_source_stat.st_ino) != (
                    source_path_stat.st_dev,
                    source_path_stat.st_ino,
                ):
                    raise OSError(f"{src}: source changed before copying")
                if expected_fingerprint is not None and (
                    opened_source_stat.st_size != expected_fingerprint.get("size")
                    or int(opened_source_stat.st_mtime_ns)
                    != expected_fingerprint.get("mtime_ns")
                    or (
                        expected_identity != (None, None)
                        and (opened_source_stat.st_dev, opened_source_stat.st_ino)
                        != expected_identity
                    )
                ):
                    raise OSError(f"{src}: source changed since manifest fingerprint")
                # Verification hashes the same owned file descriptor after
                # copying.  It must therefore be readable as well as
                # writable; a duplicate of an O_WRONLY descriptor remains
                # write-only on Windows and makes the verification fail with
                # EBADF after the copy succeeds.
                flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
                if hasattr(os, "O_BINARY"):
                    flags |= getattr(os, "O_BINARY", 0)
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= getattr(os, "O_NOFOLLOW", 0)
                # On POSIX, pin the already-validated parent directory and
                # create by basename.  This closes the parent-swap race where
                # a rival replaces ``target_dir`` with a symlink between the
                # lexical checks and a path-based open.  Windows has no
                # portable openat equivalent; its reparse checks and the
                # post-open realpath check remain the fallback there.
                use_dir_fd = (
                    os.name != "nt"
                    and getattr(os, "O_DIRECTORY", 0) != 0
                    and getattr(os, "O_NOFOLLOW", 0) != 0
                    and hasattr(os, "supports_dir_fd")
                    and os.open in os.supports_dir_fd
                )
                if use_dir_fd:
                    target_dir_fd = os.open(
                        str(target_parent),
                        os.O_RDONLY
                        | int(getattr(os, "O_DIRECTORY", 0))
                        | int(getattr(os, "O_NOFOLLOW", 0)),
                    )
                    created_fd = os.open(
                        target.name,
                        flags,
                        0o600,
                        dir_fd=target_dir_fd,
                    )
                else:
                    created_fd = os.open(str(target), flags, 0o600)
                owned = True
                created_stat = os.fstat(created_fd)
                if not stat.S_ISREG(created_stat.st_mode):
                    raise OSError(
                        f"{target}: exclusive create did not yield a regular file"
                    )
                created_identity = (created_stat.st_dev, created_stat.st_ino)
                # Keep an owned descriptor for post-copy verification.  A
                # path-based reopen here would reintroduce a rival-swap race.
                verify_fd = os.dup(created_fd)
                if Path(os.path.realpath(target)).parent != expected_parent:
                    escaped = True
                    raise OSError(f"{target}: resolved outside its planned directory")
                with os.fdopen(created_fd, "wb") as target_handle:
                    created_fd = None
                    budget_reader: _BudgetReader | None = None
                    reader = source_handle
                    if budget is not None:
                        budget_reader = _BudgetReader(
                            source_handle,
                            max_file_bytes=budget.max_file_bytes,
                            max_total_bytes=budget.max_total_bytes,
                            total_before=total_bytes_before,
                        )
                        reader = budget_reader
                    shutil.copyfileobj(reader, target_handle)
                    if budget_reader is not None:
                        copied_bytes_this_item = budget_reader.file_bytes
                if not path_is_ours():
                    escaped = True
                    raise OSError(f"{target}: target identity changed during copy")
                if expected_fingerprint is not None and opened_source_stat is not None:
                    # Same-handle stability recheck after streaming: a source
                    # replaced mid-copy must not land under the manifest's
                    # recorded fingerprint.
                    copied_bytes = source_handle.tell()
                    final_source_stat = os.fstat(source_handle.fileno())
                    if (
                        final_source_stat.st_size != opened_source_stat.st_size
                        or int(final_source_stat.st_mtime_ns)
                        != int(opened_source_stat.st_mtime_ns)
                    ):
                        raise OSError(f"{src}: source changed while copying")
                    if copied_bytes != expected_fingerprint.get("size"):
                        raise OSError(
                            f"{src}: copied byte count diverges from manifest fingerprint"
                        )
                    # Hash the materialized bytes as a final content check.
                    # This catches a replacement that preserves size and
                    # timestamps on filesystems where inode checks are not
                    # available to an older manifest.
                    digest = hashlib.sha256()
                    os.lseek(verify_fd, 0, os.SEEK_SET)
                    while chunk := os.read(verify_fd, 1024 * 1024):
                        digest.update(chunk)
                    verified_stat = os.fstat(verify_fd)
                    if (verified_stat.st_dev, verified_stat.st_ino) != created_identity:
                        raise OSError(f"{target}: target identity changed during verification")
                    if digest.hexdigest() != expected_fingerprint.get("sha256"):
                        raise OSError(f"{src}: copied content diverges from manifest fingerprint")
                # The owned descriptor has served its purpose.  Releasing it
                # before metadata propagation avoids holding a Windows share
                # lock across ``copystat`` (or a user-visible rival rename).
                # Cleanup still verifies the target's identity by path, so a
                # replacement is never unlinked as if it were ours.
                if verify_fd is not None:
                    os.close(verify_fd)
                    verify_fd = None
                final_path_stat = os.lstat(src)
                if (
                    stat.S_ISLNK(final_path_stat.st_mode)
                    or (os.name == "nt" and int(
                        getattr(final_path_stat, "st_file_attributes", 0)
                    ) & 0x400)
                    or (final_path_stat.st_dev, final_path_stat.st_ino)
                    != (opened_source_stat.st_dev, opened_source_stat.st_ino)
                    or final_path_stat.st_size != opened_source_stat.st_size
                    or int(final_path_stat.st_mtime_ns)
                    != int(opened_source_stat.st_mtime_ns)
                ):
                    raise OSError(f"{src}: source changed while copying")
                shutil.copystat(src, str(target), follow_symlinks=False)
                if total_bytes_counter is not None:
                    total_bytes_counter[0] = total_bytes_before + copied_bytes_this_item
        except OSError:
            if created_fd is not None:
                os.close(created_fd)
            if verify_fd is not None:
                try:
                    os.close(verify_fd)
                except OSError:
                    pass
            if owned and not escaped and path_is_ours():
                # Remove only our own partial result inside the verified
                # directory; never unlink a rival or an escaped path.
                try:
                    if target_dir_fd is not None:
                        os.unlink(target.name, dir_fd=target_dir_fd)
                    else:
                        os.unlink(str(target))
                except OSError:
                    pass
            if target_dir_fd is not None:
                try:
                    os.close(target_dir_fd)
                except OSError:
                    pass
            raise
        finally:
            if verify_fd is not None:
                try:
                    os.close(verify_fd)
                except OSError:
                    pass
            if target_dir_fd is not None:
                try:
                    os.close(target_dir_fd)
                except OSError:
                    pass
        return target

    @staticmethod
    def _plan_targets(
        files: list[tuple[Path, Path]], destination: Path
    ) -> list[Path]:
        """Choose deterministic targets without mutating the filesystem."""
        planned: set[Path] = set()
        targets: list[Path] = []
        for source, relative in files:
            target_dir = destination / relative.parent
            candidate = target_dir / source.name
            if candidate.exists() or candidate in planned:
                base = candidate.stem
                suffix = candidate.suffix
                for index in range(1, 1001):
                    candidate = target_dir / f"{base}_{index}{suffix}"
                    if not candidate.exists() and candidate not in planned:
                        break
                else:
                    raise OSError(f"Could not reserve a unique destination for {source}")
            planned.add(candidate)
            targets.append(candidate)
        return targets

    def _manifest_finish(
        self,
        store,
        operation_id: str,
        *,
        state: str,
        error: str | None = None,
    ) -> bool:
        if store is None:
            return True
        try:
            return bool(store.finish(operation_id, state=state, error=error))
        except Exception:
            return False

    @staticmethod
    def _manifest_needs_recovery_enqueue(store, operation_id: str) -> bool:
        """Avoid replacing a task that already completed or is bound.

        A queue worker may ACK the manifest between the caller's final
        ``finish`` CAS and this fallback branch.  Re-enqueueing in that race
        would replace the succeeded task and regress a truthful completion to
        a new pending task.  Only an unresolved row with no task binding needs
        another enqueue attempt.
        """
        if store is None:
            return False
        try:
            try:
                record = store.get(operation_id, include_items=False)
            except TypeError:
                record = store.get(operation_id)
        except Exception:
            return True
        if record is None or record.get("malformed"):
            return True
        state = str(record.get("state"))
        if state == "completed":
            return False
        if state == "recovery_pending":
            payload = record.get("payload")
            return not (
                isinstance(payload, Mapping)
                and payload.get("recovery_task_id")
            )
        return True

    def _publish_cancelled_import(self, destination: Path) -> None:
        """Publish the single compensating invalidation for a cancelled import.

        Mirrors the completed-import batch boundary: one event, destination
        scoped.  ``kind`` is pass-through data (no consumer branches on it);
        the runtime router maps it like any other FileSystemChanged.
        """
        get_event_bus().publish(FileSystemChanged(
            library_root=self.session.root_str,
            session_token=self.session.event_token,
            kind="cancelled_import",
            paths=(str(destination),),
        ))

    # ── public API ─────────────────────────────────────────────

    @session_operation
    def import_sources(
        self,
        sources: list[str | Path],
        destination_dir: str | Path,
        *,
        progress: ProgressCallback | None = None,
        should_cancel: CancelCheck | None = None,
        budget: ImportBudget | None = None,
    ) -> ImportResult:
        """Import sources while holding the session operation lease."""
        operation_id = f"import-{uuid4().hex}"
        if self.session.is_closed:
            raise RuntimeError("Cannot use a closed LibrarySession")
        if not sources:
            return ImportResult(
                copied=0, skipped=0, failed=[], operation_id=operation_id
            )

        root = self.session.root
        manifest_store = getattr(self.file_operations, "_import_manifest_store", None)
        if not self._under_root(destination_dir, root):
            raise ValueError(
                f"Import destination escapes the library root: {destination_dir}"
            )
        destination = Path(destination_dir).resolve()
        if destination.exists() and not destination.is_dir():
            return ImportResult(
                copied=0,
                skipped=0,
                failed=[f"{destination}: is not a directory"],
                degraded=True,
                operation_id=operation_id,
            )
        try:
            # Check the lexical destination before using its canonical form so
            # an alias through an existing link is rejected rather than erased
            # by Path.resolve(). The session root itself remains the trust
            # anchor and is intentionally not inspected.
            _reject_link_or_reparse_ancestors(Path(root), Path(destination_dir))
        except OSError as exc:
            raise ValueError(f"Import destination is not a real directory: {destination_dir}") from exc

        in_library: list[str | Path] = []
        external: list[str | Path] = []
        for source in sources:
            # Inspect the lexical source before resolving containment.  A
            # symlink outside the library that points into it must not be
            # silently counted as a harmless in-library skip.
            unsafe_source = False
            try:
                source_info = os.lstat(source)
                unsafe_source = stat.S_ISLNK(source_info.st_mode) or (
                    os.name == "nt"
                    and bool(int(getattr(source_info, "st_file_attributes", 0)) & 0x400)
                ) or not (
                    stat.S_ISREG(source_info.st_mode)
                    or stat.S_ISDIR(source_info.st_mode)
                )
            except OSError:
                # Let the normal collector produce the diagnostic/degraded
                # result for missing or inaccessible sources.
                unsafe_source = False
            if not unsafe_source and self._under_root(source, root):
                in_library.append(source)
            else:
                external.append(source)

        skipped = len(in_library)
        effective_budget = budget or self.budget
        try:
            files = self._collect_files(external, should_cancel, effective_budget)
        except ImportCancelled as exc:
            partial = ImportResult(
                copied=0,
                skipped=skipped,
                failed=[],
                processed=0,
                total=0,
                cancelled=True,
                operation_id=operation_id,
            )
            raise ImportCancelled(partial) from exc
        except ImportBudgetExceeded as exc:
            # Budget failures happen during the read-only planning phase, so
            # no destination bytes exist to reconcile.  Return a structured,
            # visibly degraded result rather than silently truncating the
            # source tree or attempting a partial unsafe import.
            return ImportResult(
                copied=0,
                skipped=skipped,
                failed=[f"source scan budget: {exc}"],
                processed=0,
                total=exc.scanned_files,
                degraded=True,
                operation_id=operation_id,
                budget_exceeded=True,
                budget_limit=exc.limit,
                budget_observed=exc.observed,
                budget_maximum=exc.maximum,
                scanned_files=exc.scanned_files,
                scanned_bytes=exc.scanned_bytes,
            )
        except OSError as exc:
            files = []
            failed = [f"source scan: {exc}"]
            result = ImportResult(
                copied=0,
                skipped=skipped,
                failed=failed,
                degraded=True,
                operation_id=operation_id,
            )
            self._enqueue_index_rescan(operation_id, "import_partial")
            return result

        total = len(files)
        try:
            targets = self._plan_targets(files, destination)
        except OSError as exc:
            result = ImportResult(
                copied=0,
                skipped=skipped,
                failed=[f"destination planning: {exc}"],
                processed=0,
                total=total,
                degraded=True,
                operation_id=operation_id,
            )
            if manifest_store is not None:
                try:
                    manifest_store.create(
                        operation_id=operation_id,
                        destination=destination,
                        payload={
                            "payload_version": 1,
                            "destination": str(destination),
                            "items": [
                                {
                                    "source": str(source),
                                    "target": str(destination / relative.parent / source.name),
                                    "state": "failed",
                                    "error": str(exc),
                                }
                                for source, relative in files
                            ],
                        },
                        state="recovery_pending",
                    )
                except Exception:
                    pass
            self._enqueue_index_rescan(operation_id, "import_partial")
            return result

        fingerprints: list[dict[str, object] | None] = []
        fingerprint_errors: list[str | None] = []
        use_v2 = False
        if manifest_store is not None and files:
            fingerprint_total_bytes = 0
            for source, _relative in files:
                try:
                    fingerprint = self._source_fingerprint(
                        source,
                        budget=effective_budget,
                        total_bytes_before=fingerprint_total_bytes,
                    )
                    fingerprints.append(fingerprint)
                    fingerprint_size = fingerprint.get("size")
                    if not isinstance(fingerprint_size, int):
                        raise OSError(f"{source}: fingerprint size is invalid")
                    fingerprint_total_bytes += fingerprint_size
                    fingerprint_errors.append(None)
                except Exception as exc:
                    # Do not silently downgrade the whole batch to a v1
                    # manifest when one item cannot be fingerprinted.  Keep
                    # that item terminally failed in a v2 manifest and skip
                    # its copy; all siblings retain their TOCTOU checks.
                    fingerprints.append(None)
                    fingerprint_errors.append(str(exc))
            use_v2 = True
            try:
                items = []
                for index, ((source, relative), target) in enumerate(
                    zip(files, targets, strict=True)
                ):
                    item: dict[str, object] = {
                        "source": str(source),
                        "relative": str(relative),
                        "target": str(target),
                        "state": (
                            "failed" if fingerprint_errors[index] is not None else "pending"
                        ),
                    }
                    item["copy_id"] = f"{operation_id}:{index}"
                    if fingerprints[index] is not None:
                        item["source_fingerprint"] = fingerprints[index]
                    if fingerprint_errors[index] is not None:
                        item["error"] = fingerprint_errors[index]
                    items.append(item)
                manifest_payload = {
                    "payload_version": 2 if use_v2 else 1,
                    "destination": str(destination),
                    "items": items,
                }
                if (
                    use_v2
                    and callable(getattr(manifest_store, "create_stream", None))
                    and bool(
                        getattr(manifest_store, "requires_stream", lambda _payload: False)(
                            manifest_payload
                        )
                    )
                ):
                    manifest_store.create_stream(
                        operation_id=operation_id,
                        destination=destination,
                        items=items,
                        item_count=len(items),
                        state="running",
                    )
                else:
                    manifest_store.create(
                        operation_id=operation_id,
                        destination=destination,
                        payload=manifest_payload,
                        state="running",
                    )
            except Exception as exc:
                return ImportResult(
                    copied=0,
                    skipped=skipped,
                    failed=[f"manifest prepare: {exc}"],
                    processed=0,
                    total=total,
                    degraded=True,
                    operation_id=operation_id,
                )

        try:
            destination.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._manifest_finish(
                manifest_store,
                operation_id,
                state="recovery_pending",
                error=str(exc),
            )
            return ImportResult(
                copied=0,
                skipped=skipped,
                failed=[f"{destination}: {exc}"],
                processed=0,
                total=total,
                degraded=True,
                operation_id=operation_id,
            )

        copied = 0
        failed: list[str] = []
        done = 0
        actual_total_bytes = 0
        budget_error: ImportBudgetExceeded | None = None
        if progress is not None:
            progress(done, total)

        for src, rel in files:
            if should_cancel is not None and should_cancel():
                partial = ImportResult(
                    copied=copied,
                    skipped=skipped,
                    failed=failed,
                    processed=done,
                    total=total,
                    cancelled=True,
                    operation_id=operation_id,
                )
                # Compensation must be durable before the terminal cancelled
                # state can hide already-copied files from every future
                # recovery pass.
                recovery_outcome = (
                    RecoveryEnqueueOutcome(True)
                    if copied == 0
                    else self._enqueue_index_rescan(operation_id, "import_partial")
                )
                if copied == 0 or (
                    bool(recovery_outcome)
                    and not getattr(recovery_outcome, "task_id", None)
                ):
                    self._manifest_finish(
                        manifest_store,
                        operation_id,
                        state="cancelled",
                    )
                else:
                    self._manifest_finish(
                        manifest_store,
                        operation_id,
                        state="recovery_pending",
                        error="import cancelled while index rescan was unavailable",
                    )
                if copied:
                    # Compensating invalidation: already-copied files exist
                    # under the destination, so live projections must refresh
                    # even though the batch never completed.
                    self._publish_cancelled_import(destination)
                raise ImportCancelled(partial)
            copied_this_item = False
            stop_after_item = False
            byte_counter = [actual_total_bytes]
            fingerprint_error = (
                fingerprint_errors[done]
                if manifest_store is not None and use_v2
                else None
            )
            if fingerprint_error is not None:
                failed.append(f"{src}: {fingerprint_error}")
            else:
                try:
                    self._copy_one(
                        src,
                        rel,
                        destination,
                        targets[done],
                        expected_fingerprint=(
                            fingerprints[done] if use_v2 else None
                        ),
                        budget=effective_budget,
                        total_bytes_before=actual_total_bytes,
                        total_bytes_counter=byte_counter,
                    )
                    copied += 1
                    copied_this_item = True
                    actual_total_bytes = byte_counter[0]
                except ImportBudgetExceeded as exc:
                    budget_error = exc
                    failed.append(f"{src}: {exc}")
                    stop_after_item = True
                except OSError as exc:
                    failed.append(f"{src}: {exc}")
            if manifest_store is not None:
                try:
                    update_ok = manifest_store.update_item(
                        operation_id,
                        item_index=done,
                        state="copied" if copied_this_item else "failed",
                        error=None if copied_this_item else failed[-1],
                    )
                except Exception as exc:
                    update_ok = False
                    failed.append(f"manifest update {src}: {exc}")
                if not update_ok:
                    failed.append(f"manifest update unavailable: {src}")
            done += 1
            if progress is not None:
                progress(done, total)
            if stop_after_item:
                # Keep later manifest items pending for a future explicit
                # retry; never continue copying after the hard byte ceiling.
                break

        if should_cancel is not None and should_cancel():
            partial = ImportResult(
                copied=copied,
                skipped=skipped,
                failed=failed,
                processed=done,
                total=total,
                cancelled=True,
                operation_id=operation_id,
            )
            recovery_outcome = (
                RecoveryEnqueueOutcome(True)
                if copied == 0
                else self._enqueue_index_rescan(operation_id, "import_partial")
            )
            if copied == 0 or (
                bool(recovery_outcome)
                and not getattr(recovery_outcome, "task_id", None)
            ):
                self._manifest_finish(
                    manifest_store,
                    operation_id,
                    state="cancelled",
                )
            else:
                self._manifest_finish(
                    manifest_store,
                    operation_id,
                    state="recovery_pending",
                    error="import cancelled while index rescan was unavailable",
                )
            if copied:
                # Same compensating invalidation as the mid-loop cancellation.
                self._publish_cancelled_import(destination)
            raise ImportCancelled(partial)

        refresh_warnings: tuple[object, ...] = ()
        refresh_failed: list[str] = []
        begin = getattr(self.file_operations, "_begin_refresh_diagnostics", None)
        if callable(begin):
            begin()
        try:
            self.file_operations._refresh_directory_tree(destination)
            self.file_operations._refresh_parents(destination.parent)
        except Exception as exc:
            refresh_failed.append(f"refresh: {exc}")
        refresh_warnings = tuple(
            getattr(self.file_operations, "last_refresh_warnings", ())
        )
        degraded = bool(failed or refresh_failed or refresh_warnings)
        all_failed = [*failed, *refresh_failed]
        manifest_state = "degraded" if degraded else "completed"
        queue_ok = True
        recovery_outcome: RecoveryEnqueueOutcome | object | None = None
        if degraded:
            recovery_outcome = self._enqueue_index_rescan(
                operation_id,
                "import_refresh_degraded" if refresh_warnings or refresh_failed else "import_partial",
            )
            queue_ok = bool(recovery_outcome)
            if not queue_ok or getattr(recovery_outcome, "task_id", None):
                manifest_state = "recovery_pending"
        if not self._manifest_finish(
            manifest_store,
            operation_id,
            state=manifest_state,
            error=("; ".join(all_failed) if all_failed else None),
        ) and self._manifest_needs_recovery_enqueue(
            manifest_store, operation_id
        ):
            self._enqueue_index_rescan(operation_id, "import_manifest_recovery")
        result = ImportResult(
            copied=copied,
            skipped=skipped,
            failed=all_failed,
            processed=done,
            total=total,
            degraded=degraded,
            operation_id=operation_id,
            refresh_warnings=refresh_warnings,
            budget_exceeded=budget_error is not None,
            budget_limit=budget_error.limit if budget_error else None,
            budget_observed=budget_error.observed if budget_error else None,
            budget_maximum=budget_error.maximum if budget_error else None,
            scanned_files=total,
            scanned_bytes=actual_total_bytes,
        )
        get_event_bus().publish(FileSystemChanged(
            library_root=self.session.root_str,
            session_token=self.session.event_token,
            kind="import",
            paths=(str(destination),),
        ))
        # One activity row per completed import (cancelled/failed-only runs
        # raise or return without a copy and record nothing).
        if result.copied > 0:
            recorder = getattr(self.file_operations, "activity_recorder", None)
            if recorder is not None:
                details = f"{result.copied} files -> {destination}"
                if all_failed:
                    details += f" ({len(all_failed)} failed)"
                try:
                    recorder.record("import", details)
                except Exception:
                    # Activity recording must never fail the import itself.
                    pass
        return result

    @session_operation
    def replay_import(self, operation_id: str) -> ImportResult:
        """Replay only uncertain v2 items from one persisted import intent.

        Existing targets are adopted only when their stable content fingerprint
        matches the manifest snapshot; otherwise the target is preserved and
        the item is recorded as a deterministic conflict.
        """
        if self.session.is_closed:
            raise RuntimeError("Cannot use a closed LibrarySession")
        manifest_store = getattr(self.file_operations, "_import_manifest_store", None)
        if manifest_store is None:
            return ImportResult(0, 0, ["import manifest store unavailable"], degraded=True, operation_id=operation_id)
        try:
            existing = manifest_store.get(operation_id, include_items=False)
        except TypeError:
            # Compatibility seam for older embedders that expose get(id) only.
            existing = manifest_store.get(operation_id)
        eligible = False
        if existing is not None and not existing.get("malformed"):
            payload = existing.get("payload")
            if (
                isinstance(payload, Mapping)
                and payload.get("payload_version") in {2, 3}
                and (
                    bool(
                        getattr(manifest_store, "has_pending_items", lambda _id: any(
                            isinstance(item, Mapping) and item.get("state") == "pending"
                            for item in payload.get("items", ())
                        ))(operation_id)
                    )
                )
                and str(existing["state"])
                in {"completed", "degraded", "recovery_pending"}
            ):
                eligible = True
        record = manifest_store.begin_replay(operation_id)
        if record is None:
            if eligible:
                # A concurrent replay won the CAS; report the race instead of
                # an empty success the caller cannot distinguish.
                return ImportResult(
                    0, 0, [f"{operation_id}: replay claim lost to a concurrent writer"],
                    degraded=True, operation_id=operation_id,
                )
            return ImportResult(0, 0, [], operation_id=operation_id)
        payload = record["payload"]
        if not isinstance(payload, Mapping):
            return ImportResult(
                0,
                0,
                [f"{operation_id}: replay manifest payload is malformed"],
                degraded=True,
                operation_id=operation_id,
            )
        destination = Path(str(record["destination"]))
        copied = 0
        failed: list[str] = []
        processed = 0
        actual_total_bytes = 0
        fingerprint_total_bytes = 0
        budget_error: ImportBudgetExceeded | None = None
        pending_items: Iterator[tuple[int, Mapping[str, object]]]
        item_iterator = getattr(manifest_store, "iter_items", None)
        if callable(item_iterator):
            pending_items = cast(
                Iterator[tuple[int, Mapping[str, object]]],
                item_iterator(operation_id, states={"pending"}),
            )
        else:
            raw_items = payload.get("items", ())
            legacy_items = (
                raw_items if isinstance(raw_items, (list, tuple)) else ()
            )
            pending_items = (
                (index, raw_item)
                for index, raw_item in enumerate(legacy_items)
                if isinstance(raw_item, Mapping) and raw_item.get("state") == "pending"
            )
        for index, raw_item in pending_items:
            item = dict(raw_item)
            processed += 1
            source = Path(str(item["source"]))
            target = Path(str(item["target"]))
            fingerprint = item.get("source_fingerprint")
            error: str | None = None
            copied_this_item = False
            if not isinstance(fingerprint, dict):
                error = "legacy import manifest item has no replay fingerprint"
            else:
                try:
                    current_source = self._source_fingerprint(
                        source,
                        budget=self.budget,
                        total_bytes_before=fingerprint_total_bytes,
                    )
                    fingerprint_size = current_source.get("size")
                    if not isinstance(fingerprint_size, int):
                        raise OSError(f"{source}: fingerprint size is invalid")
                    fingerprint_total_bytes += fingerprint_size
                    if not self._fingerprints_match(current_source, fingerprint):
                        error = f"{source}: source_changed"
                    elif os.path.lexists(target):
                        current_target = self._replay_target_fingerprint(
                            target,
                            budget=self.budget,
                        )
                        if (
                            current_target.get("size") == fingerprint.get("size")
                            and current_target.get("sha256") == fingerprint.get("sha256")
                        ):
                            copied_this_item = True
                        else:
                            error = f"{target}: replay_conflict"
                    else:
                        byte_counter = [actual_total_bytes]
                        self._copy_one(
                            source,
                            Path(str(item.get("relative", ""))),
                            destination,
                            target,
                            expected_fingerprint=fingerprint,
                            budget=self.budget,
                            total_bytes_before=actual_total_bytes,
                            total_bytes_counter=byte_counter,
                        )
                        actual_total_bytes = byte_counter[0]
                        copied_this_item = True
                except ImportBudgetExceeded as exc:
                    budget_error = exc
                    error = f"{source}: {exc}"
                except OSError as exc:
                    error = f"{source}: {exc}"
            next_state = "copied" if copied_this_item else "failed"
            if copied_this_item:
                copied += 1
            else:
                failed.append(error or f"{source}: replay failed")
            try:
                update_ok = manifest_store.update_item(
                    operation_id,
                    item_index=index,
                    state=next_state,
                    error=None if copied_this_item else error,
                )
            except Exception as exc:
                update_ok = False
                failed.append(f"manifest replay update {source}: {exc}")
            if not update_ok:
                failed.append(f"manifest replay update unavailable: {source}")
            if budget_error is not None:
                # Do not consume later pending items after a hard byte limit;
                # their manifest state remains pending for an explicit retry
                # with a larger/approved budget.
                break
        begin = getattr(self.file_operations, "_begin_refresh_diagnostics", None)
        if callable(begin):
            begin()
        refresh_failed: list[str] = []
        try:
            self.file_operations._refresh_directory_tree(destination)
            self.file_operations._refresh_parents(destination.parent)
        except Exception as exc:
            refresh_failed.append(f"refresh: {exc}")
        all_failed = [*failed, *refresh_failed]
        final_state = "degraded" if all_failed else "completed"
        queue_ok = True
        recovery_outcome: RecoveryEnqueueOutcome | object | None = None
        if all_failed:
            recovery_outcome = self._enqueue_index_rescan(
                operation_id,
                "import_refresh_degraded" if refresh_failed else "import_partial",
            )
            queue_ok = bool(recovery_outcome)
        try:
            finished = manifest_store.finish(
                operation_id,
                state=(
                    "recovery_pending"
                    if (
                        all_failed
                        and (
                            not queue_ok
                            or getattr(recovery_outcome, "task_id", None)
                        )
                    )
                    else final_state
                ),
                error="; ".join(all_failed) if all_failed else None,
            )
        except Exception:
            finished = False
        if not finished and self._manifest_needs_recovery_enqueue(
            manifest_store, operation_id
        ):
            self._enqueue_index_rescan(operation_id, "import_manifest_recovery")
            all_failed.append(f"{operation_id}: manifest replay finish unavailable")
        get_event_bus().publish(FileSystemChanged(
            library_root=self.session.root_str,
            session_token=self.session.event_token,
            kind="import",
            paths=(str(destination),),
        ))
        return ImportResult(
            copied=copied,
            skipped=0,
            failed=all_failed,
            processed=processed,
            total=processed,
            degraded=bool(all_failed),
            operation_id=operation_id,
            budget_exceeded=budget_error is not None,
            budget_limit=budget_error.limit if budget_error else None,
            budget_observed=budget_error.observed if budget_error else None,
            budget_maximum=budget_error.maximum if budget_error else None,
            scanned_files=processed,
            scanned_bytes=actual_total_bytes,
        )

    def _enqueue_index_rescan(
        self, operation_id: str, reason: str
    ) -> RecoveryEnqueueOutcome:
        queue = getattr(self.file_operations, "_reconciliation_queue", None)
        if queue is None:
            return RecoveryEnqueueOutcome(False)
        try:
            task = queue.enqueue_or_merge(
                path=self.session.root,
                reason=reason,
                operation_id=operation_id,
            )
            task_id = getattr(task, "task_id", None)
            if not isinstance(task_id, str) or not task_id:
                # Compatibility path for pre-durable queues whose enqueue is
                # documented as synchronous and returns no task object.
                return RecoveryEnqueueOutcome(True)
            manifest_store = getattr(
                self.file_operations, "_import_manifest_store", None
            )
            if manifest_store is None:
                return RecoveryEnqueueOutcome(True, task_id=task_id)
            try:
                bound = manifest_store.bind_existing_recovery_task(
                    operation_id, task_id
                )
            except AttributeError:
                # Older stores cannot bind task metadata; retain their prior
                # bool contract rather than claiming ACK-gated ownership.
                return RecoveryEnqueueOutcome(True, task_id=task_id)
            if not bound:
                return RecoveryEnqueueOutcome(False, task_id=task_id)
            return RecoveryEnqueueOutcome(True, task_id=task_id)
        except Exception:
            # Import results remain truthful while the manifest stays
            # unresolved for restart-time recovery.
            return RecoveryEnqueueOutcome(False)
