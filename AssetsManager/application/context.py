"""Per-library application context."""
from __future__ import annotations

from dataclasses import dataclass, field
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from sqlite3 import Connection
import threading
import uuid
import warnings
from typing import TYPE_CHECKING, Any, Callable, Iterator, TypeVar

if TYPE_CHECKING:
    from AssetsManager.core.tag_store import TagStore
    from AssetsManager.core.project_data import ProjectData


ConnectionProvider = Callable[[str | Path], Connection]
R = TypeVar("R")


def session_operation(method: Callable[..., R]) -> Callable[..., R]:
    """Lease a bound session for the complete public service operation."""
    @wraps(method)
    def leased(self: Any, *args: Any, **kwargs: Any) -> R:
        session = getattr(self, "_session", None) or getattr(self, "session", None)
        if session is None:
            return method(self, *args, **kwargs)
        with session.operation():
            return method(self, *args, **kwargs)

    return leased


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


@dataclass(frozen=True)
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
    event_token: str = field(default_factory=lambda: uuid.uuid4().hex, init=False)
    _closed: bool = False
    _close_callback: Callable[[LibrarySession], None] | None = field(
        default=None, repr=False, compare=False
    )
    _operation_condition: threading.Condition = field(
        default_factory=threading.Condition, init=False, repr=False, compare=False
    )
    _operation_local: threading.local = field(
        default_factory=threading.local, init=False, repr=False, compare=False
    )
    _active_operations: int = field(default=0, init=False, repr=False, compare=False)
    _cache_cleared: bool = field(default=False, init=False, repr=False, compare=False)

    @classmethod
    def from_context(
        cls,
        context: LibraryContext,
        close_callback: Callable[[LibrarySession], None] | None = None,
    ) -> LibrarySession:
        return cls(context=context, _close_callback=close_callback)

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
        warnings.warn(
            "LibrarySession.db_conn is deprecated; use connection_for(root) or scoped services.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._ensure_access()
        return self.context.db_conn

    @property
    def tag_store(self) -> TagStore:
        warnings.warn(
            "LibrarySession.tag_store is deprecated; use TagService or TagServiceAdapter.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._ensure_access()
        return self.context.tag_store

    @property
    def project_data(self) -> ProjectData:
        warnings.warn(
            "LibrarySession.project_data is deprecated; use MetadataService.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._ensure_access()
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
        self._ensure_access()
        return self.context.connection_for(library_root)

    # ── Lifecycle ────────────────────────────────────────────────

    @property
    def is_closed(self) -> bool:
        """Return whether this session has been closed."""
        with self._operation_condition:
            return self._closed

    @property
    def has_current_thread_operation(self) -> bool:
        """Return whether the calling thread holds an operation lease."""
        return getattr(self._operation_local, "depth", 0) > 0

    def _ensure_access(self) -> None:
        with self._operation_condition:
            if self._closed and getattr(self._operation_local, "depth", 0) == 0:
                raise RuntimeError("Cannot use a closed LibrarySession")

    @contextmanager
    def operation(self) -> Iterator[None]:
        """Keep session resources alive for one complete scoped operation."""
        depth = getattr(self._operation_local, "depth", 0)
        with self._operation_condition:
            if depth == 0:
                if self._closed:
                    raise RuntimeError("Cannot use a closed LibrarySession")
                object.__setattr__(self, "_active_operations", self._active_operations + 1)
            self._operation_local.depth = depth + 1
        try:
            yield
        finally:
            with self._operation_condition:
                remaining_depth = self._operation_local.depth - 1
                self._operation_local.depth = remaining_depth
                if remaining_depth == 0:
                    object.__setattr__(self, "_active_operations", self._active_operations - 1)
                    self._operation_condition.notify_all()

    def close(self) -> None:
        """Close this session and release owned resources.

        Idempotent. The shared ``db_conn`` is **not** closed here because
        the connection is owned by ``DatabaseManager``.
        """
        if self.has_current_thread_operation:
            raise RuntimeError("Cannot close a LibrarySession from an active operation")
        if self._closed:
            self._close_direct()
            return
        if self._close_callback is not None:
            self._close_callback(self)
            return
        self._close_direct()

    def _begin_close(self) -> None:
        """Mark closed so new operation leases are rejected."""
        if self.has_current_thread_operation:
            raise RuntimeError("Cannot close a LibrarySession from an active operation")
        with self._operation_condition:
            object.__setattr__(self, "_closed", True)

    def _finish_close(self) -> None:
        """Drain existing leases and clear owned caches once."""
        if self.has_current_thread_operation:
            raise RuntimeError("Cannot close a LibrarySession from an active operation")
        with self._operation_condition:
            self._operation_condition.wait_for(lambda: self._active_operations == 0)
            if self._cache_cleared:
                return
            object.__setattr__(self, "_cache_cleared", True)
        if hasattr(self.context.tag_store, "clear_cache"):
            self.context.tag_store.clear_cache()

    def _close_direct(self) -> None:
        """Reject new operations and drain existing ones without service locks."""
        if self.has_current_thread_operation:
            raise RuntimeError("Cannot close a LibrarySession from an active operation")
        self._begin_close()
        self._finish_close()
