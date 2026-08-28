"""Session-scoped application facade for the lazily populated asset index."""
from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from time import monotonic_ns
from contextlib import contextmanager
from pathlib import Path
from sqlite3 import Connection, OperationalError
from typing import TYPE_CHECKING, Any, Callable, Iterator

from AssetsManager.core.database import DatabaseManager
from AssetsManager.repositories.asset_index_repository import (
    AssetIndexEntry,
    AssetIndexRepository,
    AssetIndexRevisionConflict,
)

if TYPE_CHECKING:
    from AssetsManager.application.context import LibrarySession


# M6a-19: the per-library refresh lock registry is bounded by a small LRU.
# ``RLock`` objects are not weak-referenceable, so instead of a weak map we
# evict the least-recently-used key when the registry exceeds its cap.  An
# evicted lock is only ever held by a caller that already obtained it; a later
# caller for the same key simply creates a fresh lock, which serializes only
# with future scans for that library.
_REFRESH_LOCKS: OrderedDict[str, threading.RLock] = OrderedDict()
_REFRESH_LOCKS_GUARD = threading.Lock()
_REFRESH_LOCKS_MAX = 64


def _refresh_lock_for(session: object | None) -> threading.RLock:
    if session is None:
        return threading.RLock()
    identity = getattr(getattr(session, "context", None), "root_identity", None)
    key = getattr(identity, "map_key", None)
    if not isinstance(key, str) or not key:
        raise TypeError(
            "AssetIndexService canonical session requires a captured root identity"
        )
    with _REFRESH_LOCKS_GUARD:
        lock = _REFRESH_LOCKS.get(key)
        if lock is None:
            if len(_REFRESH_LOCKS) >= _REFRESH_LOCKS_MAX:
                _REFRESH_LOCKS.popitem(last=False)
            lock = threading.RLock()
            _REFRESH_LOCKS[key] = lock
        else:
            _REFRESH_LOCKS.move_to_end(key)
        return lock


class AssetIndexPublishStatus(str, Enum):
    """Outcome of one asset-index scan/publish attempt."""

    PUBLISHED = "published"
    EMPTY = "empty"
    SKIPPED = "skipped"
    SCAN_FAILED = "scan_failed"
    STALE = "stale"
    BUSY = "busy"


@dataclass(frozen=True)
class AssetIndexPublishResult:
    """Detailed publish outcome while legacy APIs continue returning ``int``."""

    status: AssetIndexPublishStatus
    count: int = 0
    revision: int | None = None
    expected_revision: int | None = None
    actual_revision: int | None = None
    retry_count: int = 0
    failure: Exception | None = field(default=None, repr=False, compare=False)
    # ``None`` means the result was not a successful publish attempt (or was
    # constructed by a compatibility double).  Successful result APIs set it
    # explicitly so callers can distinguish staged writes from durable commit.
    committed: bool | None = None

    @property
    def published(self) -> bool:
        return self.status in {
            AssetIndexPublishStatus.PUBLISHED,
            AssetIndexPublishStatus.EMPTY,
        }

    @property
    def stale(self) -> bool:
        return self.status is AssetIndexPublishStatus.STALE

    @property
    def degraded(self) -> bool:
        return self.status in {
            AssetIndexPublishStatus.SCAN_FAILED,
            AssetIndexPublishStatus.STALE,
            AssetIndexPublishStatus.BUSY,
        } or (self.published and self.committed is False)

    @property
    def durable(self) -> bool:
        """Whether this result represents a committed publish."""
        return self.published and self.committed is True


_BUSY_RETRY_LIMIT = 2
_BUSY_RETRY_BASE_DELAY = 0.01

_FILE_ATTRIBUTE_REPARSE_POINT = 0x0400


def _is_busy_error(exc: OperationalError) -> bool:
    message = str(exc).lower()
    return "locked" in message or "busy" in message


def _busy_retry_delay(attempt: int) -> float:
    return _BUSY_RETRY_BASE_DELAY * (2 ** attempt)


def _is_link_or_reparse(entry: object) -> bool:
    """Return True for symlinks/junctions and fail closed on metadata errors."""
    try:
        is_symlink = getattr(entry, "is_symlink", None)
        if callable(is_symlink) and is_symlink():
            return True
        is_junction = getattr(entry, "is_junction", None)
        if callable(is_junction) and is_junction():
            return True
        stat_method = getattr(entry, "stat", None)
        if callable(stat_method):
            if os.name == "nt":
                # os.DirEntry has no is_junction, so junctions/mount points
                # must be caught through their reparse attribute; they never
                # set the symlink tag that is_symlink() reports.
                info = stat_method(follow_symlinks=False)
                if (
                    int(getattr(info, "st_file_attributes", 0))
                    & _FILE_ATTRIBUTE_REPARSE_POINT
                ):
                    return True
            else:
                # Platform difference: POSIX has no reparse attribute, but the
                # fail-closed contract still requires a stat probe — a stat
                # metadata error (OSError) must skip the entry on every
                # platform instead of letting it be indexed with zeroed
                # size/mtime by the caller. os.DirEntry caches the stat, so
                # the caller's own stat reuses it without an extra syscall.
                stat_method(follow_symlinks=False)
        return False
    except OSError:
        return True


class AssetIndexService:
    """Populate and query the assets index through a library-scoped facade.

    ``AssetIndexService.for_session(session)`` is the canonical API.  The
    explicit ``conn, library_root, ...`` call forms remain supported for
    migration and for the existing file-operation callers; those calls are
    deliberately treated as raw compatibility calls and are validated against
    a bound session when one is available.
    """

    def __init__(self, session: LibrarySession | None = None) -> None:
        self._session = session
        self._repository = (
            AssetIndexRepository.for_session(session) if session is not None else None
        )
        # Serialize scan + replacement within one canonical facade so an older
        # filesystem snapshot cannot overwrite a newer scan from this runtime.
        self._refresh_lock = _refresh_lock_for(session)

    @classmethod
    def for_session(cls, session: LibrarySession) -> AssetIndexService:
        """Return the canonical facade bound to one live library session."""
        return cls(session)

    @property
    def session(self) -> LibrarySession | None:
        """Return the bound session, if this is a session-scoped facade."""
        return self._session

    @contextmanager
    def _operation(self) -> Iterator[None]:
        if self._session is None:
            yield
        else:
            with self._session.operation():
                yield
    def _connection(self, conn: Connection | None, library_root: str | Path | None) -> tuple[Connection, str]:

        if self._session is not None:
            requested_root = self._session.root if library_root is None else library_root
            expected = self._session.connection_for(requested_root)
            if conn is not None and conn is not expected:
                raise ValueError("Asset index connection does not belong to this library session")
            return expected, self._root(self._session.root)
        if conn is None or library_root is None:
            raise TypeError("raw asset index calls require conn and library_root")
        root = self._root(library_root)
        conn = DatabaseManager.validate_connection_owner(
            root, conn, allow_unmanaged=True
        )
        return conn, root

    def _repository_for(
        self, conn: Connection, root: str | None
    ) -> AssetIndexRepository:
        if self._session is not None:
            repository = self._repository
            if repository is None or repository._conn is not conn:
                raise RuntimeError("Asset index repository binding is unavailable")
            return repository
        if root is None:
            return AssetIndexRepository(conn)
        return AssetIndexRepository(conn, library_root=root)

    @staticmethod
    def _root(library_root: str | Path) -> str:
        return str(Path(library_root).resolve())

    @staticmethod
    def _path(path: str | Path) -> str:
        return str(Path(path).resolve())

    @classmethod
    def _contained_path(cls, root: str, path: str | Path) -> str:
        target = Path(cls._path(path))
        try:
            target.relative_to(Path(root))
        except ValueError as exc:
            raise ValueError(f"Asset index path is outside library root: {path}") from exc
        return str(target)

    @contextmanager
    def _write_scope(
        self,
        conn: Connection,
        root: str | None,
        *,
        commit: bool,
        savepoint: str | None,
    ) -> Iterator[None]:
        repository = self._repository_for(conn, root)
        with repository.transaction_scope(commit=commit, savepoint=savepoint):
            yield

    @staticmethod
    def _retry_busy_read(
        operation: Callable[[], Any],
    ) -> tuple[Any | None, int, OperationalError | None]:
        """Run a read that may observe SQLite's bounded busy/locked state."""
        retry_count = 0
        while True:
            try:
                return operation(), retry_count, None
            except OperationalError as exc:
                if not _is_busy_error(exc):
                    raise
                if retry_count >= _BUSY_RETRY_LIMIT:
                    return None, retry_count, exc
                time.sleep(_busy_retry_delay(retry_count))
                retry_count += 1

    def _scan_directory_entries(
        self, root: str, target: str, now: float
    ) -> list[tuple[str, str, str, str, int, float, str, str, float, float]] | None:
        entries: list[tuple[str, str, str, str, int, float, str, str, float, float]] = []
        try:
            for entry in os.scandir(target):
                if _is_link_or_reparse(entry):
                    continue
                if entry.name.startswith("."):
                    # M6a-17: hidden entries are excluded from the index,
                    # matching the project_service/asset_service counting
                    # semantics (display counts never include dotfiles).
                    continue
                is_dir = entry.is_dir(follow_symlinks=False)
                ext = os.path.splitext(entry.name)[1].lower() if not is_dir else ""
                kind = "dir" if is_dir else "file"
                try:
                    stat = entry.stat(follow_symlinks=False)
                    size = 0 if is_dir else stat.st_size
                    mtime = stat.st_mtime
                except OSError:
                    size = 0
                    mtime = 0.0
                entries.append((
                    self._contained_path(root, entry.path), entry.name, ext, kind,
                    size, mtime, target, root, now, now,
                ))
        except OSError:
            return None
        return entries

    def index_directory_result(
        self,
        *args: Any,
        force: bool = False,
        commit: bool = True,
    ) -> AssetIndexPublishResult:
        """Scan and publish one directory with an explicit outcome contract."""
        with self._operation(), self._refresh_lock:
            if self._session is not None and len(args) == 1:
                conn, root = self._connection(None, None)
                dir_path = args[0]
            elif len(args) == 3:
                conn, root = self._connection(args[0], args[1])
                dir_path = args[2]
            else:
                raise TypeError("index_directory_result expects dir_path or conn, library_root, dir_path")
            target = self._contained_path(root, dir_path)
            repository = self._repository_for(conn, root)
            outer_transaction = conn.in_transaction
            durable_commit = commit and (
                self._session is None or not outer_transaction
            )
            retry_count = 0

            if not force:
                snapshot, read_retries, read_failure = self._retry_busy_read(
                    lambda: repository.count_by_parent(target, root),
                )
                retry_count += read_retries
                if read_failure is not None:
                    return AssetIndexPublishResult(
                        AssetIndexPublishStatus.BUSY,
                        expected_revision=None,
                        revision=None,
                        retry_count=retry_count,
                        failure=read_failure,
                    )
                existing = snapshot
                assert isinstance(existing, int)
                if existing > 0:
                    # M6a-18: the fast path compares the recorded
                    # directory-mtime snapshot against the live directory.
                    # Equal mtimes mean the directory is unchanged (SKIPPED);
                    # a mismatch or a missing snapshot falls through to a
                    # full rescan below, which also backfills dir_mtime.
                    try:
                        live_mtime = os.stat(target).st_mtime
                    except OSError:
                        live_mtime = None
                    snapshot_mtime, read_retries, read_failure = self._retry_busy_read(
                        lambda: repository.get_dir_mtime(root, target)
                    )
                    retry_count += read_retries
                    if read_failure is not None:
                        return AssetIndexPublishResult(
                            AssetIndexPublishStatus.BUSY,
                            count=existing,
                            expected_revision=None,
                            revision=None,
                            retry_count=retry_count,
                            failure=read_failure,
                        )
                    if (
                        snapshot_mtime is not None
                        and live_mtime is not None
                        and snapshot_mtime == live_mtime
                    ):
                        revision, read_retries, read_failure = self._retry_busy_read(
                            lambda: repository.current_revision(root)
                        )
                        retry_count += read_retries
                        if read_failure is not None:
                            return AssetIndexPublishResult(
                                AssetIndexPublishStatus.BUSY,
                                count=existing,
                                expected_revision=None,
                                revision=None,
                                retry_count=retry_count,
                                failure=read_failure,
                            )
                        assert isinstance(revision, int)
                        return AssetIndexPublishResult(
                            AssetIndexPublishStatus.SKIPPED,
                            count=existing,
                            revision=revision,
                            retry_count=retry_count,
                        )
                    # Snapshot missing or stale: rescan below (backfills).

            try:
                dir_mtime = os.stat(target).st_mtime
            except OSError:
                dir_mtime = None

            expected_revision, read_retries, read_failure = self._retry_busy_read(
                lambda: repository.current_revision(root)
            )
            retry_count += read_retries
            if read_failure is not None:
                return AssetIndexPublishResult(
                    AssetIndexPublishStatus.BUSY,
                    expected_revision=None,
                    revision=None,
                    retry_count=retry_count,
                    failure=read_failure,
                )
            assert isinstance(expected_revision, int)
            entries = self._scan_directory_entries(root, target, time.time())
            if entries is None:
                return AssetIndexPublishResult(
                    AssetIndexPublishStatus.SCAN_FAILED,
                    expected_revision=expected_revision,
                    revision=expected_revision,
                )

            try:
                while True:
                    try:
                        repository.replace_parent_entries(
                            target,
                            root,
                            entries,
                            clear_existing=force,
                            commit=commit,
                            expected_revision=expected_revision,
                        )
                        if dir_mtime is not None:
                            repository.upsert_dir_snapshot(root, target, dir_mtime)
                        break
                    except OperationalError as exc:
                        if not _is_busy_error(exc) or retry_count >= _BUSY_RETRY_LIMIT:
                            raise
                        time.sleep(_busy_retry_delay(retry_count))
                        retry_count += 1
            except AssetIndexRevisionConflict as exc:
                return AssetIndexPublishResult(
                    AssetIndexPublishStatus.STALE,
                    expected_revision=exc.expected,
                    actual_revision=exc.actual,
                    revision=exc.actual,
                    retry_count=retry_count,
                    failure=exc,
                )
            except OperationalError as exc:
                if not _is_busy_error(exc):
                    raise
                return AssetIndexPublishResult(
                    AssetIndexPublishStatus.BUSY,
                    expected_revision=expected_revision,
                    revision=None,
                    retry_count=retry_count,
                    failure=exc,
                )

            revision = expected_revision + 1
            status = (
                AssetIndexPublishStatus.PUBLISHED
                if entries
                else AssetIndexPublishStatus.EMPTY
            )
            return AssetIndexPublishResult(
                status,
                count=len(entries),
                revision=revision,
                expected_revision=expected_revision,
                retry_count=retry_count,
                committed=durable_commit,
            )

    def index_directory(
        self,
        *args: Any,
        force: bool = False,
        commit: bool = True,
    ) -> int:
        """Legacy integer wrapper around :meth:`index_directory_result`."""
        result = self.index_directory_result(*args, force=force, commit=commit)
        if result.failure is not None:
            raise result.failure
        if result.status is AssetIndexPublishStatus.STALE:
            expected = 0 if result.expected_revision is None else result.expected_revision
            actual = (
                expected + 1
                if result.actual_revision is None
                else result.actual_revision
            )
            raise AssetIndexRevisionConflict("", expected, actual)
        if result.status is AssetIndexPublishStatus.BUSY:
            raise OperationalError("asset index publish is busy")
        return result.count

    def index_directory_tree_result(self, *args: Any) -> AssetIndexPublishResult:
        """Force-index a directory tree with one root-level CAS publish."""
        with self._operation(), self._refresh_lock:
            if self._session is not None and len(args) == 1:
                conn, root = self._connection(None, None)
                dir_path = args[0]
            elif len(args) == 3:
                conn, root = self._connection(args[0], args[1])
                dir_path = args[2]
            else:
                raise TypeError("index_directory_tree_result expects dir_path or conn, library_root, dir_path")
            target = self._contained_path(root, dir_path)
            repository = self._repository_for(conn, root)
            outer_transaction = conn.in_transaction
            durable_commit = self._session is None or not outer_transaction
            expected_revision, retry_count, read_failure = self._retry_busy_read(
                lambda: repository.current_revision(root)
            )
            if read_failure is not None:
                return AssetIndexPublishResult(
                    AssetIndexPublishStatus.BUSY,
                    expected_revision=None,
                    revision=None,
                    retry_count=retry_count,
                    failure=read_failure,
                )
            assert isinstance(expected_revision, int)
            snapshots: list[tuple[str, list[tuple[str, str, str, str, int, float, str, str, float, float]]]] = []
            scan_error: OSError | None = None

            def onerror(error: OSError) -> None:
                nonlocal scan_error
                scan_error = error

            for current, directories, _ in os.walk(
                target, followlinks=False, onerror=onerror
            ):
                directories[:] = [
                    name for name in directories
                    if not _is_link_or_reparse(Path(current) / name)
                    and not name.startswith(".")
                ]
                entries = self._scan_directory_entries(root, current, time.time())
                if entries is None:
                    return AssetIndexPublishResult(
                        AssetIndexPublishStatus.SCAN_FAILED,
                        expected_revision=expected_revision,
                        revision=expected_revision,
                    )
                snapshots.append((current, entries))
                if scan_error is not None:
                    return AssetIndexPublishResult(
                        AssetIndexPublishStatus.SCAN_FAILED,
                        expected_revision=expected_revision,
                        revision=expected_revision,
                    )

            if scan_error is not None or not snapshots:
                return AssetIndexPublishResult(
                    AssetIndexPublishStatus.SCAN_FAILED,
                    expected_revision=expected_revision,
                    revision=expected_revision,
                )

            count = sum(len(entries) for _current, entries in snapshots)
            savepoint = f"asset_index_tree_{monotonic_ns():x}"
            try:
                while True:
                    try:
                        with self._write_scope(conn, root, commit=True, savepoint=savepoint):
                            repository.clear_subtree(target, root, commit=False)
                            first = True
                            for current, entries in snapshots:
                                try:
                                    dir_mtime = os.stat(current).st_mtime
                                except OSError:
                                    dir_mtime = None
                                repository.replace_parent_entries(
                                    current,
                                    root,
                                    entries,
                                    clear_existing=True,
                                    commit=False,
                                    expected_revision=expected_revision if first else None,
                                    advance_revision=first,
                                )
                                if dir_mtime is not None:
                                    repository.upsert_dir_snapshot(root, current, dir_mtime)
                                first = False
                        break
                    except OperationalError as exc:
                        if not _is_busy_error(exc) or retry_count >= _BUSY_RETRY_LIMIT:
                            raise
                        time.sleep(_busy_retry_delay(retry_count))
                        retry_count += 1
            except AssetIndexRevisionConflict as exc:
                return AssetIndexPublishResult(
                    AssetIndexPublishStatus.STALE,
                    count=count,
                    expected_revision=exc.expected,
                    actual_revision=exc.actual,
                    revision=exc.actual,
                    retry_count=retry_count,
                    failure=exc,
                )
            except OperationalError as exc:
                if not _is_busy_error(exc):
                    raise
                return AssetIndexPublishResult(
                    AssetIndexPublishStatus.BUSY,
                    count=count,
                    expected_revision=expected_revision,
                    revision=None,
                    retry_count=retry_count,
                    failure=exc,
                )

            revision = expected_revision + 1
            status = (
                AssetIndexPublishStatus.PUBLISHED
                if count
                else AssetIndexPublishStatus.EMPTY
            )
            return AssetIndexPublishResult(
                status,
                count=count,
                revision=revision,
                expected_revision=expected_revision,
                retry_count=retry_count,
                committed=durable_commit,
            )

    def index_directory_tree(self, *args: Any) -> int:
        """Legacy integer wrapper around :meth:`index_directory_tree_result`."""
        result = self.index_directory_tree_result(*args)
        if result.failure is not None:
            raise result.failure
        if result.status is AssetIndexPublishStatus.STALE:
            expected = 0 if result.expected_revision is None else result.expected_revision
            actual = (
                expected + 1
                if result.actual_revision is None
                else result.actual_revision
            )
            raise AssetIndexRevisionConflict("", expected, actual)
        if result.status is AssetIndexPublishStatus.BUSY:
            raise OperationalError("asset index publish is busy")
        return result.count

    def query_by_parent(self, *args: Any) -> list[AssetIndexEntry]:
        """Return indexed entries under a parent directory."""
        with self._operation():
            if self._session is not None and len(args) == 1:
                conn, root = self._connection(None, None)
                parent_path = args[0]
            elif len(args) == 3:
                conn, root = self._connection(args[0], args[1])
                parent_path = args[2]
            else:
                raise TypeError("query_by_parent expects parent_path or conn, library_root, parent_path")
            return self._repository_for(conn, root).query_by_parent(
                root, self._contained_path(root, parent_path)
            )

    def query_by_extension(self, *args: Any) -> list[AssetIndexEntry]:
        """Return indexed entries with a given extension."""
        with self._operation():
            if self._session is not None and len(args) == 1:
                conn, root = self._connection(None, None)
                extension = args[0]
            elif len(args) == 3:
                conn, root = self._connection(args[0], args[1])
                extension = args[2]
            else:
                raise TypeError("query_by_extension expects extension or conn, library_root, extension")
            return self._repository_for(conn, root).query_by_extension(root, extension)

    def search_by_name(self, *args: Any, limit: int = 200) -> list[AssetIndexEntry]:
        """Search indexed entries by name substring."""
        with self._operation():
            if self._session is not None and len(args) == 1:
                conn, root = self._connection(None, None)
                query = args[0]
            elif len(args) in (3, 4):
                conn, root = self._connection(args[0], args[1])
                query = args[2]
                if len(args) == 4:
                    limit = args[3]
            else:
                raise TypeError("search_by_name expects query or conn, library_root, query[, limit]")
            if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
                raise ValueError("limit must be a positive integer")
            return self._repository_for(conn, root).search_by_name(root, query, limit)

    def remove_entry(self, *args: Any, commit: bool = True, savepoint: str | None = None) -> None:
        """Remove one entry, with optional transaction control."""
        with self._operation():
            if self._session is not None and len(args) == 1:
                conn, root = self._connection(None, None)
                file_path = args[0]
            elif len(args) == 2:
                conn, file_path = args
                root = None
                if self._session is not None:
                    conn, root = self._connection(conn, None)
            elif len(args) == 3:
                conn, root = self._connection(args[0], args[1])
                file_path = args[2]
            else:
                raise TypeError("remove_entry expects file_path, conn/file_path, or conn, library_root, file_path")
            path = self._contained_path(root, file_path) if root is not None else self._path(file_path)
            with self._write_scope(conn, root, commit=commit, savepoint=savepoint):
                self._repository_for(conn, root).delete_entry(path, commit=False)

    def remove_directory(self, *args: Any, commit: bool = True, savepoint: str | None = None) -> int:
        """Remove a directory subtree, with optional transaction control."""
        with self._operation():
            if self._session is not None and len(args) == 1:
                conn, root = self._connection(None, None)
                dir_path = args[0]
            elif len(args) == 2:
                conn, dir_path = args
                root = None
                if self._session is not None:
                    conn, root = self._connection(conn, None)
            elif len(args) == 3:
                conn, root = self._connection(args[0], args[1])
                dir_path = args[2]
            else:
                raise TypeError("remove_directory expects dir_path, conn/dir_path, or conn, library_root, dir_path")
            path = self._contained_path(root, dir_path) if root is not None else self._path(dir_path)
            with self._write_scope(conn, root, commit=commit, savepoint=savepoint):
                return self._repository_for(conn, root).delete_path(path, commit=False)

    def count(self, *args: Any) -> int:
        """Return total indexed entries for a library."""
        with self._operation():
            if self._session is not None and len(args) == 0:
                conn, root = self._connection(None, None)
            elif len(args) == 2:
                conn, root = self._connection(args[0], args[1])
            else:
                raise TypeError("count expects no args or conn, library_root")
            return self._repository_for(conn, root).count(root)

    def current_revision(self, *args: Any) -> int:
        """Return the committed root revision (zero for an unseen root)."""
        with self._operation():
            if self._session is not None and len(args) == 0:
                conn, root = self._connection(None, None)
            elif len(args) == 2:
                conn, root = self._connection(args[0], args[1])
            else:
                raise TypeError(
                    "current_revision expects no args or conn, library_root"
                )
            return self._repository_for(conn, root).current_revision(root)

    def get_entry(self, *args: Any) -> AssetIndexEntry | None:
        """Return a single entry by path, or None."""
        with self._operation():
            if self._session is not None and len(args) == 1:
                conn, root = self._connection(None, None)
                file_path = args[0]
            elif len(args) == 2:
                conn, file_path = args
                root = None
                if self._session is not None:
                    conn, root = self._connection(conn, None)
            elif len(args) == 3:
                conn, root = self._connection(args[0], args[1])
                file_path = args[2]
            else:
                raise TypeError("get_entry expects file_path, conn/file_path, or conn, library_root, file_path")
            path = self._contained_path(root, file_path) if root is not None else self._path(file_path)
            return self._repository_for(conn, root).get_entry(path)
