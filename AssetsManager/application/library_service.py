"""Library lifecycle service."""
from __future__ import annotations

import logging
import threading
import warnings
from pathlib import Path
from typing import Callable

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
        self._lifecycle = threading.Condition(self._lock)
        self._closing = False
        self._closing_roots: set[str] = set()
        self._current: LibraryContext | None = None
        self._contexts: dict[str, LibraryContext] = {}
        self._sessions: dict[str, LibrarySession] = {}
        self._session_close_listeners: list[Callable[[LibrarySession], None]] = []

    def add_session_close_listener(
        self, listener: Callable[[LibrarySession], None]
    ) -> None:
        """Notify an owner when a canonical session is closed."""
        with self._lock:
            self._session_close_listeners.append(listener)

    def _notify_session_closed(self, session: LibrarySession) -> None:
        with self._lock:
            listeners = tuple(self._session_close_listeners)
        for listener in listeners:
            try:
                listener(session)
            except Exception:
                _log.exception("Library session close listener failed")

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
        context, _ = self._open(root_path)
        return context

    def _open(self, root_path: str | Path) -> tuple[LibraryContext, LibrarySession]:
        root = Path(root_path).resolve()
        key = str(root)
        with self._lifecycle:
            self._lifecycle.wait_for(
                lambda: not self._closing and key not in self._closing_roots
            )
            cached = self._contexts.get(key)
            if cached is not None:
                session = self._sessions.get(key)
                if session is None or session.is_closed:
                    session = LibrarySession.from_context(cached, self.close_session)
                    self._sessions[key] = session
                self._current = cached
                return cached, session

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
            session = LibrarySession.from_context(context, self.close_session)
            self._contexts[key] = context
            self._sessions[key] = session
            self._current = context
        get_event_bus().publish(LibraryOpened(library_root=key))
        return context, session

    def open_session(self, root_path: str | Path) -> LibrarySession:
        _, session = self._open(root_path)
        return session

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
            return self._sessions.get(str(self._current.root))

    def owns_live_session(self, session: LibrarySession) -> bool:
        """Return whether session is this service's exact live canonical session."""
        key = str(session.root)
        with self._lock:
            return self._sessions.get(key) is session and not session.is_closed

    def close(self) -> None:
        with self._lifecycle:
            self._lifecycle.wait_for(lambda: not self._closing)
            self._closing = True
            sessions = list(self._sessions.values())
            self._contexts.clear()
            self._sessions.clear()
            self._current = None
        try:
            for session in sessions:
                try:
                    session._close_direct()
                except Exception:
                    pass
                finally:
                    self._notify_session_closed(session)
            self._db.close()
        finally:
            with self._lifecycle:
                self._closing = False
                self._lifecycle.notify_all()

    def close_session(self, session: LibrarySession) -> None:
        """Remove a session's context from the service cache.

        Idempotent — closing an already-removed session is a no-op.
        The session itself is also marked as closed.
        """
        key = str(session.root)
        with self._lifecycle:
            if self._sessions.get(key) is not session:
                current = False
            else:
                current = True
                self._closing_roots.add(key)
                self._sessions.pop(key)
                context = self._contexts.pop(key, None)
                if self._current is context:
                    self._current = None
        if not current:
            session._close_direct()
            return
        try:
            try:
                session._close_direct()
            finally:
                self._notify_session_closed(session)
        finally:
            try:
                self._db.close_library(key)
            finally:
                with self._lifecycle:
                    self._closing_roots.discard(key)
                    self._lifecycle.notify_all()


def get_library_service() -> LibraryService:
    """Return the LibraryService singleton.

    Presentation code should prefer accessing ``bootstrap.library_service``
    directly. This helper remains as a non-Qt fallback for tests and legacy
    callers that still need a process-wide singleton.
    """
    warnings.warn("get_library_service() is deprecated, use Bootstrap.library_service instead", DeprecationWarning, stacklevel=2)
    _log.debug("LibraryService singleton fallback used")
    return ThreadSafeSingleton.get(LibraryService)
