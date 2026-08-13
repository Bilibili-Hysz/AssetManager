"""Per-library application context."""
from __future__ import annotations

from dataclasses import dataclass, field
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from sqlite3 import Connection
import threading
import uuid
from typing import TYPE_CHECKING, Any, Callable, Iterator, TypeVar

from AssetsManager.core.path_resolver import RootIdentity
from AssetsManager.core.session_contract import register_library_session

if TYPE_CHECKING:
    from AssetsManager.core.tag_store import TagStore
    from AssetsManager.core.project_data import ProjectData


ConnectionProvider = Callable[[str | Path], Connection]
R = TypeVar("R")


class _SessionLiveness:
    """Small mutable liveness token shared by a context and its core stores."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._live = True

    def ensure_live(self) -> None:
        with self._lock:
            if not self._live:
                raise RuntimeError("Cannot use resources from a closed LibrarySession")

    def invalidate(self) -> None:
        with self._lock:
            self._live = False


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
    root_key: str = ""
    _liveness: _SessionLiveness = field(
        default_factory=_SessionLiveness, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        # Core stores are constructed before the session wrapper in the
        # canonical bootstrap path, so bind the shared token at context
        # assembly time rather than changing that lifecycle.
        for store in (self.tag_store, self.project_data):
            bind = getattr(store, "_bind_liveness", None)
            if bind is not None:
                bind(self._liveness)

    def _invalidate(self) -> None:
        self._liveness.invalidate()

    @property
    def root_identity(self):
        """Return the identity captured when this context was opened."""
        from AssetsManager.core.path_resolver import RootIdentity, root_identity

        if self.root_key:
            return RootIdentity(self.root, self.root_key)
        return root_identity(self.root, strict=False)

    @property
    def root_str(self) -> str:
        return str(self.root)

    @property
    def data_dir_str(self) -> str:
        return str(self.data_dir)

    @property
    def thumb_dir_str(self) -> str:
        return str(self.thumb_dir)

    def connection_for(
        self, library_root: str | Path | RootIdentity | None = None
    ) -> Connection:
        """Return this library's DB connection, rejecting mismatched roots."""
        self._liveness.ensure_live()
        if library_root is not None:
            from AssetsManager.core.path_resolver import root_identity
            expected_key = self.root_key or root_identity(self.root).map_key
            requested_key = (
                library_root.map_key
                if isinstance(library_root, RootIdentity)
                else root_identity(library_root, strict=False).map_key
            )
            if requested_key != expected_key:
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
    _closed: bool = field(default=False, compare=False, hash=False)
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

    def __post_init__(self) -> None:
        register_library_session(self)

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
    def root_str(self) -> str:
        return self.context.root_str

    @property
    def data_dir_str(self) -> str:
        return self.context.data_dir_str

    @property
    def thumb_dir_str(self) -> str:
        return self.context.thumb_dir_str

    def connection_for(
        self, library_root: str | Path | RootIdentity | None = None
    ) -> Connection:
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

    def _publish_while_live(self, publish: Callable[[], R]) -> R:
        """Publish session-bound state atomically against close admission.

        The caller must already hold an operation lease. Close marks the
        session closed under the same condition, so executing the callback
        gives lazy runtime assembly a precise linearization point: either the
        value is published before close starts, or publication is rejected.
        """
        if not self.has_current_thread_operation:
            raise RuntimeError("Session-bound publication requires an active operation")
        with self._operation_condition:
            if self._closed:
                raise RuntimeError("Cannot publish services for a closing LibrarySession")
            return publish()

    def close(self) -> None:
        """Close this session and release owned resources.

        Idempotent. The shared ``db_conn`` is **not** closed here because
        the connection is owned by ``DatabaseManager``.
        """
        if self.has_current_thread_operation:
            raise RuntimeError("Cannot close a LibrarySession from an active operation")
        if self._closed and self._close_callback is not None:
            self._close_callback(self)
            self._invalidate_resources()
            return
        if self._closed:
            self._close_direct()
            return
        if self._close_callback is not None:
            self._close_callback(self)
            self._begin_close()
            self._invalidate_resources()
            return
        self._close_direct()

    def _begin_close(self) -> None:
        """Mark closed so new operation leases are rejected."""
        if self.has_current_thread_operation:
            raise RuntimeError("Cannot close a LibrarySession from an active operation")
        with self._operation_condition:
            object.__setattr__(self, "_closed", True)

    def _invalidate_resources(self) -> None:
        self.context._invalidate()

    def _finish_close(self) -> None:
        """Drain existing leases and clear owned caches once."""
        if self.has_current_thread_operation:
            raise RuntimeError("Cannot close a LibrarySession from an active operation")
        with self._operation_condition:
            self._operation_condition.wait_for(lambda: self._active_operations == 0)
            if self._cache_cleared:
                return
            object.__setattr__(self, "_cache_cleared", True)
        tag_store = object.__getattribute__(self.context, "tag_store")
        if hasattr(tag_store, "clear_cache"):
            tag_store.clear_cache()

    def _close_direct(self) -> None:
        """Reject new operations and drain existing ones without service locks."""
        if self.has_current_thread_operation:
            raise RuntimeError("Cannot close a LibrarySession from an active operation")
        self._begin_close()
        self._finish_close()
        self._invalidate_resources()
