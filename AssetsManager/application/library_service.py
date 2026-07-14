"""Library lifecycle service."""
from __future__ import annotations

import logging
import threading
import warnings
from pathlib import Path

from AssetsManager.application.context import LibraryContext, LibrarySession
from AssetsManager.core.database import DatabaseManager
from AssetsManager.core.project_data import ProjectData
from AssetsManager.core.singleton import ThreadSafeSingleton
from AssetsManager.core.tag_store import TagStore
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import LibraryOpened

_log = logging.getLogger(__name__)


class LibraryService:
    """Open libraries and expose their shared runtime context.

    This service is intentionally small for the first refactor phase. It
    centralizes existing database/store initialization without changing the
    underlying persistence behavior.
    """

    def __init__(self, db: DatabaseManager | None = None):
        self._db = db or DatabaseManager()
        self._lock = threading.Lock()
        self._current: LibraryContext | None = None
        self._contexts: dict[str, LibraryContext] = {}

    def open_library(self, root_path: str | Path) -> LibraryContext:
        """Open or reuse a library and return its raw context.

        .. deprecated::
            Use ``open_session()`` instead.  ``LibraryContext`` is now an
            internal implementation detail and ``LibrarySession`` is the sole
            public opened-library boundary.
        """
        import warnings
        warnings.warn(
            "LibraryService.open_library() is deprecated. Use LibraryService.open_session() instead.",
            DeprecationWarning, stacklevel=2,
        )
        return self._open_library(root_path)

    def _open_library(self, root_path: str | Path) -> LibraryContext:
        root = Path(root_path).resolve()
        key = str(root)
        with self._lock:
            cached = self._contexts.get(key)
            if cached is not None:
                self._current = cached
                return cached

            mgr = self._db
            conn = mgr.connection_for(key)

            context = LibraryContext(
                root=root,
                data_dir=mgr.data_dir_for(key),
                thumb_dir=mgr.thumb_dir_for(key),
                db_conn=conn,
                tag_store=TagStore(key, db_conn=conn),
                project_data=ProjectData(key, db_conn=conn),
            )
            self._contexts[key] = context
            self._current = context
        get_event_bus().publish(LibraryOpened(library_root=key))
        return context

    def open_session(self, root_path: str | Path) -> LibrarySession:
        return LibrarySession.from_context(self._open_library(root_path))

    @property
    def current(self) -> LibraryContext | None:
        """Return the current raw context for legacy compatibility.

        .. deprecated::
            Use ``current_session`` instead.  ``LibraryContext`` is now an
            internal detail and ``LibrarySession`` is the sole public boundary.
        """
        import warnings
        warnings.warn(
            "LibraryService.current is deprecated. Use LibraryService.current_session instead.",
            DeprecationWarning, stacklevel=2,
        )
        with self._lock:
            return self._current

    @property
    def current_session(self) -> LibrarySession | None:
        with self._lock:
            if self._current is None:
                return None
            return LibrarySession.from_context(self._current)

    def close(self) -> None:
        with self._lock:
            contexts = list(self._contexts.values())
            self._contexts.clear()
            self._current = None
        for ctx in contexts:
            try:
                LibrarySession.from_context(ctx).close()
            except Exception:
                pass
        self._db.close()

    def close_session(self, session: LibrarySession) -> None:
        """Remove a session's context from the service cache.

        Idempotent — closing an already-removed session is a no-op.
        The session itself is also marked as closed.
        """
        key = str(session.root)
        with self._lock:
            self._contexts.pop(key, None)
            if self._current is not None and str(self._current.root) == key:
                self._current = None
        try:
            session.close()
        finally:
            self._db.close_library(key)


def get_library_service() -> LibraryService:
    """Return the LibraryService singleton.

    Presentation code should prefer accessing ``bootstrap.library_service``
    directly. This helper remains as a non-Qt fallback for tests and legacy
    callers that still need a process-wide singleton.
    """
    warnings.warn("get_library_service() is deprecated, use Bootstrap.library_service instead", DeprecationWarning, stacklevel=2)
    _log.debug("LibraryService singleton fallback used")
    return ThreadSafeSingleton.get(LibraryService)
