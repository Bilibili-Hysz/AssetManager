"""Per-library application context."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from sqlite3 import Connection
import threading
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from AssetsManager.core.tag_store import TagStore
    from AssetsManager.core.project_data import ProjectData


ConnectionProvider = Callable[[str | Path], Connection]


@dataclass(frozen=True)
class LibraryContext:
    """Runtime resources for an opened asset library.

    The context intentionally wraps the existing core stores while the project
    migrates toward repositories and application services.
    """

    root: Path
    data_dir: Path
    thumb_dir: Path
    db_conn: Connection
    tag_store: TagStore
    project_data: ProjectData

    @property
    def root_str(self) -> str:
        return str(self.root)

    @property
    def data_dir_str(self) -> str:
        return str(self.data_dir)

    @property
    def thumb_dir_str(self) -> str:
        return str(self.thumb_dir)

    def connection_for(self, library_root: str | Path | None = None) -> Connection:
        """Return this library's DB connection, rejecting mismatched roots."""
        if library_root is not None and Path(library_root).resolve() != self.root:
            raise ValueError(f"Connection requested for different library: {library_root}")
        return self.db_conn


@dataclass
class LibrarySession:
    """Opened library session boundary.

    This is intentionally a thin wrapper while callers migrate away from
    passing raw library resources through presentation and transport layers.

    Callers should use :meth:`close` to release session-owned resources.
    The underlying ``LibraryContext`` and its ``db_conn`` are **not** closed
    here — connection lifetime is still managed by ``DatabaseManager``.
    Closing a session is idempotent.
    """

    context: LibraryContext
    _closed: bool = False
    _active_operations: int = field(default=0, init=False, repr=False)
    _state: threading.Condition = field(
        default_factory=lambda: threading.Condition(threading.RLock()),
        init=False,
        repr=False,
    )
    _leases: threading.local = field(default_factory=threading.local, init=False, repr=False)

    @classmethod
    def from_context(cls, context: LibraryContext) -> LibrarySession:
        return cls(context=context)

    @property
    def root(self) -> Path:
        return self.context.root

    @property
    def data_dir(self) -> Path:
        return self.context.data_dir

    @property
    def thumb_dir(self) -> Path:
        return self.context.thumb_dir

    @property
    def db_conn(self) -> Connection:
        if self._closed and not self._has_lease():
            raise RuntimeError("Cannot use a closed LibrarySession")
        return self.context.db_conn

    @property
    def tag_store(self) -> TagStore:
        if self._closed and not self._has_lease():
            raise RuntimeError("Cannot use a closed LibrarySession")
        return self.context.tag_store

    @property
    def project_data(self) -> ProjectData:
        if self._closed and not self._has_lease():
            raise RuntimeError("Cannot use a closed LibrarySession")
        return self.context.project_data

    @property
    def root_str(self) -> str:
        return self.context.root_str

    @property
    def data_dir_str(self) -> str:
        return self.context.data_dir_str

    @property
    def thumb_dir_str(self) -> str:
        return self.context.thumb_dir_str

    def connection_for(self, library_root: str | Path | None = None) -> Connection:
        if self._closed and not self._has_lease():
            raise RuntimeError("Cannot use a closed LibrarySession")
        return self.context.connection_for(library_root)

    # ── Lifecycle ────────────────────────────────────────────────

    @property
    def is_closed(self) -> bool:
        """Return whether this session has been closed."""
        with self._state:
            return self._closed

    def _has_lease(self) -> bool:
        return getattr(self._leases, "depth", 0) > 0

    @contextmanager
    def operation(self):
        """Keep this session's resources alive for one service operation."""
        with self._state:
            if self._closed:
                raise RuntimeError("Cannot use a closed LibrarySession")
            self._active_operations += 1
        self._leases.depth = getattr(self._leases, "depth", 0) + 1
        try:
            yield self
        finally:
            self._leases.depth -= 1
            with self._state:
                self._active_operations -= 1
                if self._active_operations == 0:
                    self._state.notify_all()

    def close(self) -> None:
        """Close this session and release owned resources.

        Idempotent. The shared ``db_conn`` is **not** closed here because
        the connection is owned by ``DatabaseManager``.
        """
        with self._state:
            already_closed = self._closed
            self._closed = True
            while self._active_operations:
                self._state.wait()
        if not already_closed:
            if hasattr(self.context.tag_store, "clear_cache"):
                self.context.tag_store.clear_cache()


class SessionBoundOperations:
    """Lease every public operation of a service bound to one session."""

    _session: LibrarySession | None = None

    def _bind_session(self, session: LibrarySession) -> None:
        self._session = session

    def __getattribute__(self, name: str):
        value = super().__getattribute__(name)
        if name.startswith("_") or not callable(value):
            return value
        session = super().__getattribute__("_session")
        if session is None:
            return value

        @wraps(value)
        def leased(*args, **kwargs):
            with session.operation():
                return value(*args, **kwargs)

        return leased
