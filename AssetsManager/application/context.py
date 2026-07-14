"""Per-library application context."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection
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
    _closed: bool = False

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
        if self._closed:
            raise RuntimeError("Cannot use a closed LibrarySession")
        return self.context.db_conn

    @property
    def tag_store(self) -> TagStore:
        if self._closed:
            raise RuntimeError("Cannot use a closed LibrarySession")
        return self.context.tag_store

    @property
    def project_data(self) -> ProjectData:
        if self._closed:
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
        if self._closed:
            raise RuntimeError("Cannot use a closed LibrarySession")
        return self.context.connection_for(library_root)

    # ── Lifecycle ────────────────────────────────────────────────

    @property
    def is_closed(self) -> bool:
        """Return whether this session has been closed."""
        return self._closed

    def close(self) -> None:
        """Close this session and release owned resources.

        Idempotent. The shared ``db_conn`` is **not** closed here because
        the connection is owned by ``DatabaseManager``.
        """
        already_closed = self._closed
        object.__setattr__(self, "_closed", True)
        if not already_closed:
            if hasattr(self.context.tag_store, "clear_cache"):
                self.context.tag_store.clear_cache()
