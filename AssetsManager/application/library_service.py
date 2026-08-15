"""Library lifecycle service."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable, Iterator

from AssetsManager.application.context import LibraryContext, LibrarySession
from AssetsManager.core.database import DatabaseManager
from AssetsManager.core.library_lock import LibraryLock
from AssetsManager.core.path_resolver import RootIdentity, library_lock_path, root_identity
from AssetsManager.core.project_data import ProjectData
from AssetsManager.core.tag_store import TagStore, install_repository_factory
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import LibraryOpened
from AssetsManager.repositories.tag_repository import TagRepository

_log = logging.getLogger(__name__)


def _tag_repository_factory(conn, *, library_root=None, session=None):
    """Application-layer seam that injects TagRepository into core TagStore."""
    return TagRepository(conn, library_root=library_root, session=session)


install_repository_factory(_tag_repository_factory)


@dataclass
class _RootOwnership:
    service: "LibraryService"
    session: LibrarySession | None
    phase: str
    generation: int


@dataclass
class _TeardownProgress:
    context: LibraryContext
    closing_listener_index: int = 0
    session_finished: bool = False
    close_listener_index: int = 0
    database_closed: bool = False
    lock_released: bool = False


@dataclass
class _OpeningProgress:
    identity: RootIdentity
    generation: int
    previous_generation: int
    lock: LibraryLock | None = None
    database_closed: bool = False
    lock_released: bool = False


@dataclass(frozen=True)
class _RestoreRecoveryState:
    generation: int
    phase: str
    message: str
    token: str
    secondary_errors: tuple[str, ...] = ()


_root_ownership_guard = threading.Lock()
_root_ownership: dict[str, _RootOwnership] = {}
_root_generations: dict[str, int] = {}
_root_restore_recovery: dict[str, _RestoreRecoveryState] = {}


def _lexical_map_key(key: str) -> str:
    """Return a compatibility key without following symlinks or reparse points."""
    return os.path.normcase(os.path.abspath(os.path.normpath(key)))


class _CanonicalRootMap(dict[str, Any]):
    """Root map with raw stable-key access and alias compatibility lookup."""

    def _lookup(self, key: object) -> Any:
        if not isinstance(key, str):
            return key
        if super().__contains__(key):
            return key
        return _lexical_map_key(key)

    def __contains__(self, key: object) -> bool:
        return super().__contains__(self._lookup(key))

    def __getitem__(self, key: str):
        return super().__getitem__(self._lookup(key))

    def __setitem__(self, key: str, value: object) -> None:
        super().__setitem__(key, value)

    def get(self, key: str, default=None):
        return super().get(self._lookup(key), default)

    def pop(self, key: str, default=None):
        return super().pop(self._lookup(key), default)


class LibraryService:
    """Open libraries and own one canonical session per root in this process."""

    def __init__(self, db: DatabaseManager | None = None):
        self._db = db or DatabaseManager()
        self._lock = threading.Lock()
        self._lifecycle = threading.Condition(self._lock)
        self._closing = False
        self._closing_roots: set[str] = set()
        self._closing_sessions = _CanonicalRootMap()
        self._teardown_progress = _CanonicalRootMap()
        self._opening_progress = _CanonicalRootMap()
        self._restore_reservations = _CanonicalRootMap()
        self._committed_closed_sessions = _CanonicalRootMap()
        self._committed_generations = _CanonicalRootMap()
        self._session_generations = _CanonicalRootMap()
        self._current: LibraryContext | None = None
        self._contexts = _CanonicalRootMap()
        self._sessions = _CanonicalRootMap()
        self._library_locks = _CanonicalRootMap()
        self._session_close_listeners: list[Callable[[LibrarySession], None]] = []
        self._session_closing_listeners: list[Callable[[LibrarySession], None]] = []

    @staticmethod
    def canonical_root_identity(root_path: str | Path | RootIdentity) -> tuple[Path, str]:
        identity = root_identity(root_path)
        return identity.display_path, identity.map_key

    @staticmethod
    def _root_generation(key: str) -> int:
        with _root_ownership_guard:
            return _root_generations.get(key, 0)

    @staticmethod
    def _foreign_owner_error(key: str, ownership: _RootOwnership) -> RuntimeError:
        return RuntimeError(
            f"Canonical library root is owned by another LibraryService "
            f"({ownership.phase}): {key}"
        )

    def _claim_root_for_open(self, key: str) -> tuple[int, int]:
        with _root_ownership_guard:
            ownership = _root_ownership.get(key)
            if ownership is not None:
                if ownership.service is not self:
                    raise self._foreign_owner_error(key, ownership)
                if ownership.phase == "opening":
                    raise RuntimeError(
                        f"Canonical library root opening cleanup is pending; "
                        f"retry retry_open_cleanup or close: {key}"
                    )
                raise RuntimeError(
                    f"Canonical library root teardown is pending; retry close_session: {key}"
                )
            previous_generation = _root_generations.get(key, 0)
            generation = previous_generation + 1
            _root_generations[key] = generation
            _root_ownership[key] = _RootOwnership(
                service=self,
                session=None,
                phase="opening",
                generation=generation,
            )
            return generation, previous_generation

    def _publish_root_session(
        self, key: str, session: LibrarySession, generation: int
    ) -> None:
        with _root_ownership_guard:
            ownership = _root_ownership.get(key)
            if (
                ownership is None
                or ownership.service is not self
                or ownership.phase != "opening"
                or ownership.generation != generation
            ):
                raise RuntimeError(f"Canonical root opening reservation was lost: {key}")
            ownership.session = session
            ownership.phase = "live"

    def _rollback_root_open(
        self, key: str, generation: int, previous_generation: int
    ) -> None:
        with _root_ownership_guard:
            ownership = _root_ownership.get(key)
            if (
                ownership is not None
                and ownership.service is self
                and ownership.phase == "opening"
                and ownership.generation == generation
            ):
                _root_ownership.pop(key, None)
                if previous_generation:
                    _root_generations[key] = previous_generation
                else:
                    _root_generations.pop(key, None)

    def _run_opening_cleanup(self, key: str, progress: _OpeningProgress) -> None:
        """Retry cleanup for an open attempt that never published a session."""
        if not progress.database_closed:
            try:
                self._db.close_library(progress.identity)
            except BaseException:
                # Keep the OS lock while the database connection is still
                # live. Releasing it here would let another process open the
                # same RuntimeData while this owner still retains SQLite state.
                _log.exception("Failed to clean up opening database for %s", key)
                raise
            else:
                progress.database_closed = True
        if not progress.lock_released:
            if progress.lock is None:
                progress.lock_released = True
            else:
                try:
                    released = progress.lock.release()
                    if not released:
                        raise RuntimeError(
                            f"Failed to release opening library lock: {progress.lock.path}"
                        )
                except BaseException:
                    _log.exception("Failed to clean up opening library lock for %s", key)
                    raise
                else:
                    progress.lock_released = True
        self._rollback_root_open(
            key, progress.generation, progress.previous_generation
        )
        self._opening_progress.pop(key, None)

    def _mark_root_closing(self, key: str, session: LibrarySession) -> None:
        with _root_ownership_guard:
            ownership = _root_ownership.get(key)
            if ownership is None:
                raise RuntimeError(f"Canonical root ownership is missing: {key}")
            if ownership.service is not self:
                raise self._foreign_owner_error(key, ownership)
            if ownership.session is not session:
                raise RuntimeError(f"Canonical root session ownership changed: {key}")
            ownership.phase = "closing"

    def _release_committed_root(
        self, key: str, session: LibrarySession, generation: int
    ) -> None:
        with _root_ownership_guard:
            ownership = _root_ownership.get(key)
            if (
                ownership is None
                or ownership.service is not self
                or ownership.session is not session
                or ownership.generation != generation
                or ownership.phase != "closing"
            ):
                raise RuntimeError(f"Canonical root close ownership changed: {key}")
            _root_ownership.pop(key, None)

    def _claim_root_for_restore(
        self, key: str, session: LibrarySession, generation: int
    ) -> None:
        with _root_ownership_guard:
            ownership = _root_ownership.get(key)
            if ownership is not None:
                if ownership.service is not self:
                    raise self._foreign_owner_error(key, ownership)
                raise RuntimeError(f"Restore target is still owned ({ownership.phase}): {key}")
            if _root_generations.get(key) != generation:
                raise RuntimeError(
                    "Restore coordinator was superseded by a newer canonical session"
                )
            _root_ownership[key] = _RootOwnership(
                service=self,
                session=session,
                phase="restore",
                generation=generation,
            )

    @staticmethod
    def _restore_blocked_error(
        key: str, state: _RestoreRecoveryState
    ) -> RuntimeError:
        # Keep the existing ExportService exception contract without importing
        # it at module import time (LibraryExportService is wired by Bootstrap).
        try:
            from AssetsManager.application.library_export_service import (
                RestoreAdmissionBlockedError,
                RestoreFailureState,
            )

            return RestoreAdmissionBlockedError(
                RestoreFailureState(
                    phase=state.phase,
                    message=state.message,
                    secondary_errors=state.secondary_errors,
                    generation=state.generation,
                    token=state.token,
                )
            )
        except ImportError:
            return RuntimeError(
                f"Restore admission is blocked for canonical library root: {key}"
            )

    def restore_state_provider(self, library_root: str | Path | RootIdentity):
        _, key = self.canonical_root_identity(library_root)
        with _root_ownership_guard:
            return _root_restore_recovery.get(key)

    def restore_acknowledger(self, library_root: str | Path | RootIdentity, token: str | None = None):
        identity = root_identity(library_root)
        with self._lifecycle:
            with _root_ownership_guard:
                state = _root_restore_recovery.get(identity.map_key)
                if state is None or token is None or state.token != token:
                    raise RuntimeError("Restore recovery acknowledgement rejected: stale or unknown token")
                if identity.map_key in self._restore_reservations:
                    raise RuntimeError("Restore recovery acknowledgement rejected during active reservation")
                ownership = _root_ownership.get(identity.map_key)
                if ownership is not None and ownership.phase == "restore":
                    raise RuntimeError("Restore recovery acknowledgement rejected during restore ownership")
                if identity.map_key in self._teardown_progress:
                    raise RuntimeError("Restore recovery acknowledgement rejected before finalizer completion")
                _root_restore_recovery.pop(identity.map_key, None)
                return None

    def _ensure_restore_admission(self, key: str) -> None:
        with _root_ownership_guard:
            state = _root_restore_recovery.get(key)
        if state is not None:
            raise self._restore_blocked_error(key, state)

    def restore_failure_state(self, library_root: str | Path) -> _RestoreRecoveryState | None:
        return self.restore_state_provider(library_root)

    def acknowledge_restore_failure(self, library_root: str | Path, token: str | None = None):
        return self.restore_acknowledger(library_root, token)

    def _record_restore_failure(
        self, key: str, generation: int, error: BaseException, phase: str
    ) -> None:
        existing_error_state = getattr(error, "restore_failure_state", None)
        existing_token = getattr(existing_error_state, "token", None)
        if not isinstance(existing_token, str) or not existing_token:
            existing_token = getattr(error, "restore_token", None)
        token = (
            existing_token
            if isinstance(existing_token, str) and existing_token
            else f"{key}:{generation}:{os.urandom(16).hex()}:1"
        )
        existing_phase = getattr(existing_error_state, "phase", None)
        canonical_phase = existing_phase if isinstance(existing_phase, str) else phase
        secondary_errors = tuple(getattr(error, "restore_secondary_errors", ()))
        state = _RestoreRecoveryState(
            generation=generation,
            phase=canonical_phase,
            message=f"{type(error).__name__}: {error}",
            token=token,
            secondary_errors=secondary_errors,
        )
        with _root_ownership_guard:
            existing = _root_restore_recovery.get(key)
            if existing is None or generation >= existing.generation:
                _root_restore_recovery[key] = state
        # Make the canonical ACK identity and phase available to the original
        # exception as well as to later provider lookups.
        try:
            setattr(error, "restore_failure_state", state)
            setattr(error, "restore_token", token)
            setattr(error, "restore_generation", generation)
            setattr(error, "restore_phase", canonical_phase)
        except (AttributeError, TypeError):
            pass

    def _release_root_restore(
        self, key: str, session: LibrarySession, generation: int
    ) -> None:
        with _root_ownership_guard:
            ownership = _root_ownership.get(key)
            if not (
                ownership is not None
                and ownership.service is self
                and ownership.session is session
                and ownership.phase == "restore"
                and ownership.generation == generation
            ):
                raise RuntimeError(f"Canonical root restore ownership changed: {key}")
            _root_ownership.pop(key, None)

    def _acquire_library_lock(self, key: str) -> LibraryLock:
        """Acquire the cross-process lock owned by a stable root identity."""
        if key in self._library_locks:
            raise RuntimeError(f"Library lock is already owned by this service: {key}")
        return LibraryLock(library_lock_path(RootIdentity(Path(key), key)))

    def _release_library_lock(self, key: str) -> None:
        """Release the canonical lock, failing closed when unlock is uncertain."""
        lock = self._library_locks.get(key)
        if lock is None:
            raise RuntimeError(f"Library lock ownership is missing: {key}")
        try:
            released = lock.release()
        except BaseException:
            _log.exception("Failed to release library lock for %s", key)
            raise
        if not released:
            raise RuntimeError(f"Failed to release library lock: {lock.path}")
        if self._library_locks.get(key) is lock:
            self._library_locks.pop(key, None)

    def add_session_closing_listener(
        self, listener: Callable[[LibrarySession], None]
    ) -> None:
        """Notify an owner after new operations are rejected, before drain."""
        with self._lock:
            self._session_closing_listeners.append(listener)

    def add_session_close_listener(
        self, listener: Callable[[LibrarySession], None]
    ) -> None:
        """Notify an owner before database and library-lock release."""
        with self._lock:
            self._session_close_listeners.append(listener)

    def _notify_listener_stage(
        self,
        session: LibrarySession,
        progress: _TeardownProgress,
        *,
        closing: bool,
    ) -> None:
        listeners = (
            self._session_closing_listeners
            if closing
            else self._session_close_listeners
        )
        index_attr = "closing_listener_index" if closing else "close_listener_index"
        label = "pre-close" if closing else "close"
        while True:
            with self._lock:
                index = getattr(progress, index_attr)
                if index >= len(listeners):
                    return
                listener = listeners[index]
            try:
                listener(session)
            except BaseException:
                _log.exception("Library session %s listener failed", label)
                raise
            setattr(progress, index_attr, index + 1)

    def _notify_session_closing(self, session: LibrarySession) -> None:
        progress = _TeardownProgress(session.context)
        self._notify_listener_stage(session, progress, closing=True)

    def _notify_session_closed(self, session: LibrarySession) -> None:
        progress = _TeardownProgress(session.context)
        self._notify_listener_stage(session, progress, closing=False)

    def _open(self, root_path: str | Path) -> tuple[LibraryContext, LibrarySession]:
        identity = root_identity(root_path)
        root = identity.display_path
        key = identity.map_key
        opened_session = False
        with self._lifecycle:
            self._lifecycle.wait_for(
                lambda: (
                    not self._closing
                    and key not in self._closing_roots
                    and key not in self._restore_reservations
                )
            )
            if key in self._closing_sessions:
                raise RuntimeError(
                    f"Library teardown is pending; retry close_session before open: {key}"
                )
            self._ensure_restore_admission(key)
            cached = self._contexts.get(key)
            if cached is not None:
                session = self._sessions.get(key)
                if session is None or session.is_closed:
                    raise RuntimeError(f"Canonical cached session is not live: {key}")
                self._current = cached
                result = (cached, session)
            else:
                generation, previous_generation = self._claim_root_for_open(key)
                opening = _OpeningProgress(identity, generation, previous_generation)
                self._opening_progress[key] = opening
                mgr = self._db
                lock: LibraryLock | None = None
                context: LibraryContext | None = None
                session: LibrarySession | None = None
                try:
                    lock = self._acquire_library_lock(key)
                    opening.lock = lock
                    conn = mgr.connection_for(identity)
                    context = LibraryContext(
                        root=root,
                        data_dir=mgr.data_dir_for(identity),
                        thumb_dir=mgr.thumb_dir_for(identity),
                        db_conn=conn,
                        tag_store=TagStore(key, db_conn=conn),
                        project_data=ProjectData(key, db_conn=conn),
                        root_key=key,
                    )
                    session = LibrarySession.from_context(context, self.close_session)
                    for store in (context.tag_store, context.project_data):
                        bind_session = getattr(store, "_bind_session", None)
                        if callable(bind_session):
                            bind_session(session)
                    self._contexts[key] = context
                    self._sessions[key] = session
                    self._library_locks[key] = lock
                    self._session_generations[key] = generation
                    self._committed_closed_sessions.pop(key, None)
                    self._committed_generations.pop(key, None)
                    self._current = context
                    self._publish_root_session(key, session, generation)
                    self._opening_progress.pop(key, None)
                    opened_session = True
                    result = (context, session)
                except BaseException as error:
                    if session is not None and self._sessions.get(key) is session:
                        self._sessions.pop(key, None)
                    if context is not None and self._contexts.get(key) is context:
                        self._contexts.pop(key, None)
                        if self._current is context:
                            self._current = None
                    if lock is not None and self._library_locks.get(key) is lock:
                        self._library_locks.pop(key, None)
                    if self._session_generations.get(key) == generation:
                        self._session_generations.pop(key, None)
                    try:
                        self._run_opening_cleanup(key, opening)
                    except BaseException as cleanup_error:
                        try:
                            error.add_note(
                                f"Opening cleanup is pending for {key}: {cleanup_error}"
                            )
                        except (AttributeError, TypeError):
                            pass
                    raise
        if opened_session:
            get_event_bus().publish(
                LibraryOpened(library_root=str(root), session_token=result[1].event_token)
            )
        return result

    def open_session(self, root_path: str | Path) -> LibrarySession:
        _, session = self._open(root_path)
        return session

    @property
    def current_session(self) -> LibrarySession | None:
        with self._lock:
            if self._current is None:
                return None
            return self._sessions.get(self._current.root_key)

    def owns_live_session(self, session: LibrarySession) -> bool:
        """Return whether session is this service's exact live canonical session."""
        key = session.context.root_key
        with self._lock:
            locally_owned = self._sessions.get(key) is session and not session.is_closed
        if not locally_owned:
            return False
        with _root_ownership_guard:
            ownership = _root_ownership.get(key)
            return bool(
                ownership is not None
                and ownership.service is self
                and ownership.session is session
                and ownership.phase == "live"
            )

    @contextmanager
    def restore_reservation(
        self, session: LibrarySession, library_root: str | Path | RootIdentity
    ) -> Iterator[None]:
        """Reserve a committed, still-current canonical root for restore."""
        identity = root_identity(library_root)
        key = identity.map_key
        session_key = session.context.root_key
        if key != session_key:
            raise RuntimeError("Restore reservation root does not match its session")
        with self._lifecycle:
            self._lifecycle.wait_for(
                lambda: (
                    not self._closing
                    and key not in self._closing_roots
                    and key not in self._restore_reservations
                )
            )
            self._ensure_restore_admission(key)
            if self._committed_closed_sessions.get(key) is not session:
                raise RuntimeError(
                    "Restore requires the target session to be closed with committed teardown"
                )
            generation = self._committed_generations.get(key)
            if generation is None:
                raise RuntimeError(
                    "Restore requires the target session to be closed with committed teardown"
                )
            if (
                key in self._sessions
                or key in self._contexts
                or key in self._library_locks
                or key in self._closing_sessions
            ):
                raise RuntimeError(
                    "Restore target still owns session, database, or library-lock state"
                )
            self._claim_root_for_restore(key, session, generation)
            self._restore_reservations[key] = session
        try:
            try:
                yield
            except BaseException as error:
                if getattr(error, "restore_recovery_required", False) or getattr(
                    error, "restore_admission_blocked", False
                ):
                    self._record_restore_failure(key, generation, error, "restore")
                raise
        finally:
            with self._lifecycle:
                if self._restore_reservations.get(key) is session:
                    self._restore_reservations.pop(key, None)
                self._release_root_restore(key, session, generation)
                self._lifecycle.notify_all()

    @staticmethod
    def _reset_failed_session_finish(session: LibrarySession) -> None:
        condition = session._operation_condition
        with condition:
            object.__setattr__(session, "_cache_cleared", False)

    def _run_owned_teardown(
        self,
        key: str,
        session: LibrarySession,
        progress: _TeardownProgress,
    ) -> None:
        session._begin_close()
        self._notify_listener_stage(session, progress, closing=True)
        finish_error: BaseException | None = None
        if not progress.session_finished:
            try:
                session._finish_close()
            except BaseException as exc:
                self._reset_failed_session_finish(session)
                finish_error = exc
            else:
                progress.session_finished = True
        self._notify_listener_stage(session, progress, closing=False)
        if finish_error is not None:
            raise finish_error
        if not progress.database_closed:
            self._db.close_library(
                RootIdentity(progress.context.root, progress.context.root_key)
            )
            progress.database_closed = True
        if not progress.lock_released:
            self._release_library_lock(key)
            progress.lock_released = True

        # The service owns canonical teardown, so invalidate context-bound
        # stores here as well as through LibrarySession.close(). This keeps
        # direct close_session()/close() callers on the same liveness contract.
        session._invalidate_resources()

        generation = int(self._session_generations[key])
        with self._lifecycle:
            context = progress.context
            if self._sessions.get(key) is session:
                self._sessions.pop(key, None)
            if self._contexts.get(key) is context:
                self._contexts.pop(key, None)
            if self._current is context:
                self._current = None
            self._release_committed_root(key, session, generation)
            self._committed_closed_sessions[key] = session
            self._committed_generations[key] = generation
            self._session_generations.pop(key, None)
            self._teardown_progress.pop(key, None)
            self._closing_sessions.pop(key, None)

    def _start_owned_teardown(
        self, key: str, session: LibrarySession
    ) -> _TeardownProgress:
        progress = self._teardown_progress.get(key)
        if progress is None:
            context = self._contexts.get(key)
            if context is None:
                raise RuntimeError(f"Canonical library context is missing: {key}")
            progress = _TeardownProgress(context=context)
            self._teardown_progress[key] = progress
        self._closing_roots.add(key)
        self._closing_sessions[key] = session
        self._mark_root_closing(key, session)
        return progress

    def retry_open_cleanup(self, root_path: str | Path | RootIdentity) -> None:
        """Retry cleanup for an opening attempt that failed before session publish."""
        identity = root_identity(root_path)
        key = identity.map_key
        with self._lifecycle:
            self._lifecycle.wait_for(lambda: not self._closing)
            progress = self._opening_progress.get(key)
            if progress is None:
                return
            with _root_ownership_guard:
                ownership = _root_ownership.get(key)
                if ownership is None:
                    raise RuntimeError(f"Canonical opening ownership is missing: {key}")
                if ownership.service is not self:
                    raise self._foreign_owner_error(key, ownership)
                if ownership.phase != "opening" or ownership.generation != progress.generation:
                    raise RuntimeError(f"Opening cleanup ownership changed: {key}")
            try:
                self._run_opening_cleanup(key, progress)
            finally:
                self._lifecycle.notify_all()

    def close(self) -> None:
        with self._lifecycle:
            if any(
                session.has_current_thread_operation
                for session in (
                    *self._sessions.values(),
                    *self._closing_sessions.values(),
                )
            ):
                raise RuntimeError(
                    "Cannot close LibraryService from an active operation"
                )
            self._lifecycle.wait_for(lambda: not self._closing)
            self._closing = True
            self._lifecycle.wait_for(
                lambda: not self._closing_roots and not self._restore_reservations
            )
            sessions = list(dict.fromkeys(self._sessions.values()))
            openings = list(self._opening_progress.values())
        first_error: BaseException | None = None
        try:
            for session in sessions:
                key = session.context.root_key
                try:
                    with self._lifecycle:
                        progress = self._start_owned_teardown(key, session)
                    self._run_owned_teardown(key, session, progress)
                except BaseException as exc:
                    if first_error is None:
                        first_error = exc
                    _log.exception("Library teardown failed during service close")
                finally:
                    with self._lifecycle:
                        self._closing_roots.discard(key)
                        self._lifecycle.notify_all()
            for progress in openings:
                key = progress.identity.map_key
                try:
                    with self._lifecycle:
                        self._run_opening_cleanup(key, progress)
                except BaseException as exc:
                    if first_error is None:
                        first_error = exc
                    _log.exception("Library opening cleanup failed during service close")
                finally:
                    with self._lifecycle:
                        self._lifecycle.notify_all()
            if first_error is None:
                self._db.close()
            else:
                raise first_error
        finally:
            with self._lifecycle:
                self._closing = False
                self._lifecycle.notify_all()

    def close_session(self, session: LibrarySession) -> None:
        """Commit teardown only after listeners, DB, and lock all succeed.

        A failed attempt leaves the canonical root in ``closing`` ownership.
        Calling ``close_session(session)`` again is the explicit retry entry.
        """
        if session.has_current_thread_operation:
            raise RuntimeError("Cannot close a LibrarySession from an active operation")
        key = session.context.root_key
        with self._lifecycle:
            self._lifecycle.wait_for(
                lambda: (
                    not self._closing
                    and key not in self._closing_roots
                    and key not in self._restore_reservations
                )
            )
            if session.is_closed and key not in self._closing_sessions:
                return
            if self._sessions.get(key) is not session:
                current = False
            else:
                current = True
                progress = self._start_owned_teardown(key, session)
        if not current:
            with _root_ownership_guard:
                ownership = _root_ownership.get(key)
                if (
                    ownership is not None
                    and ownership.service is not self
                    and ownership.session is session
                ):
                    raise self._foreign_owner_error(key, ownership)
            session._begin_close()
            session._finish_close()
            session._invalidate_resources()
            return
        committed = False
        try:
            self._run_owned_teardown(key, session, progress)
            committed = True
        finally:
            with self._lifecycle:
                self._closing_roots.discard(key)
                if not committed:
                    self._closing_sessions[key] = session
                self._lifecycle.notify_all()