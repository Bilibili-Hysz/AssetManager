"""Session-scoped domain event routing for runtime projections."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from AssetsManager.domain.event_bus import EventBus, EventSubscription, get_event_bus
from AssetsManager.domain.events import (
    AssetNotesChanged,
    AssetRatingChanged,
    AssetTagsChanged,
    AssetUrlsChanged,
    ActivityChanged,
    CollectionChanged,
    FavoritesChanged,
    FileSystemChanged,
    InviteChanged,
    PresenceChanged,
    QuotaChanged,
    ShareChanged,
    TagCatalogChanged,
    UserChanged,
)

if TYPE_CHECKING:
    from AssetsManager.application.runtime import LibraryRuntime

_log = logging.getLogger(__name__)

#: Maximum time ``_RouterSubscription.close`` waits for in-flight callbacks
#: running on other threads before giving up its local wait.  The router-level
#: drain still remains pending until those callbacks actually return.
_SUBSCRIPTION_DRAIN_TIMEOUT = 2.0
# Router-level close drain bound: close() must never hang forever on a
# stalled in-flight callback (audit 2026-08-28: the two waits in close()
# previously had no deadline, unlike the subscription-level drain).
_CLOSE_DRAIN_TIMEOUT = 2.0


class ProjectionDomain(StrEnum):
    FILES = "files"
    TREE = "tree"
    HOME = "home"
    PROJECT_DETAIL = "project_detail"
    METADATA = "metadata"
    FAVORITES = "favorites"
    TAGS = "tags"
    SHARES = "shares"
    USERS = "users"
    ACTIVITY = "activity"
    ONLINE_USERS = "online_users"
    QUOTA = "quota"
    COLLECTIONS = "collections"


@dataclass(frozen=True)
class InvalidationEvent:
    epoch: str
    revision: int
    domains: tuple[ProjectionDomain, ...]
    paths: tuple[str, ...]


class _RouterSubscription:
    def __init__(self, router: RuntimeEventRouter, callback):
        self._router = router
        self._callback = callback
        self._active = True
        self._inflight = 0
        self._active_by_thread: dict[int, int] = {}

    def close(self) -> None:
        with self._router._lock:
            if self._active:
                self._active = False
                if self in self._router._subscribers:
                    self._router._subscribers.remove(self)
            current_thread = threading.get_ident()
            own_callbacks = self._active_by_thread.get(current_thread, 0)
            deadline = time.monotonic() + _SUBSCRIPTION_DRAIN_TIMEOUT
            while self._inflight > own_callbacks:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _log.warning(
                        "Timed out after %.1fs waiting for in-flight callbacks "
                        "in RouterSubscription.close(); closing anyway",
                        _SUBSCRIPTION_DRAIN_TIMEOUT,
                    )
                    break
                self._router._drain_condition.wait(timeout=remaining)


# Events without a mapping here (e.g. domain.events.MaintenanceChanged, a
# pure UI-notification for maintenance/integrity completion) are invisible
# to the Router by design: the Router only subscribes to the types below,
# and such notifications carry no projection state to invalidate.  Their
# consumers subscribe on the event bus directly.
EVENT_DOMAINS: dict[type, tuple[ProjectionDomain, ...]] = {
    FileSystemChanged: (
        ProjectionDomain.FILES, ProjectionDomain.TREE,
        ProjectionDomain.HOME, ProjectionDomain.PROJECT_DETAIL,
        ProjectionDomain.FAVORITES, ProjectionDomain.COLLECTIONS,
    ),
    # Smart collections can filter the requesting principal's favorites.
    FavoritesChanged: (ProjectionDomain.FAVORITES, ProjectionDomain.COLLECTIONS),
    AssetTagsChanged: (
        ProjectionDomain.METADATA, ProjectionDomain.TAGS,
        ProjectionDomain.PROJECT_DETAIL, ProjectionDomain.HOME,
        ProjectionDomain.COLLECTIONS,
    ),
    TagCatalogChanged: (ProjectionDomain.TAGS, ProjectionDomain.HOME),
    # Notes participate in smart collection FTS queries; URLs do not.
    AssetNotesChanged: (
        ProjectionDomain.METADATA, ProjectionDomain.PROJECT_DETAIL,
        ProjectionDomain.COLLECTIONS,
    ),
    AssetRatingChanged: (
        ProjectionDomain.METADATA, ProjectionDomain.PROJECT_DETAIL,
        ProjectionDomain.COLLECTIONS,
    ),
    AssetUrlsChanged: (ProjectionDomain.METADATA, ProjectionDomain.PROJECT_DETAIL),
    ShareChanged: (ProjectionDomain.SHARES,),
    UserChanged: (ProjectionDomain.USERS,),
    InviteChanged: (ProjectionDomain.USERS,),
    ActivityChanged: (ProjectionDomain.ACTIVITY,),
    PresenceChanged: (ProjectionDomain.ONLINE_USERS,),
    QuotaChanged: (ProjectionDomain.QUOTA,),
    CollectionChanged: (ProjectionDomain.COLLECTIONS,),
}


class RuntimeEventRouter:
    """Route only the current runtime's session-scoped events."""

    def __init__(self, runtime: LibraryRuntime, event_bus: EventBus | None = None):
        self.runtime = runtime
        self._bus = event_bus or get_event_bus()
        self._lock = threading.RLock()
        self._close_state = "accepting"
        self._accepting = True
        self._inflight = 0
        self._active_by_thread: dict[int, int] = {}
        self._drain_condition = threading.Condition(self._lock)
        self._closing_thread_id: int | None = None
        self._deferred_after_drain: list[Callable[[], None]] = []
        self._subscribers: list[_RouterSubscription] = []
        self._event_subscriptions: list[EventSubscription] = []
        for event_type in EVENT_DOMAINS:
            self._event_subscriptions.append(self._bus.subscribe(event_type, self._on_event))

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._close_state != "accepting"

    @property
    def drained(self) -> bool:
        """Whether all callbacks have returned and cleanup may proceed.

        ``closed`` only means that new events/subscribers are rejected.  A
        router can be closed while an already-dispatched callback is still
        using the runtime, so teardown must check this stronger predicate.
        """
        with self._lock:
            return self._close_state == "drained"

    @staticmethod
    def domains_for(event_type: type) -> tuple[ProjectionDomain, ...]:
        return EVENT_DOMAINS[event_type]

    def subscribe(self, handler: Callable[[InvalidationEvent], None]) -> EventSubscription:
        with self._lock:
            if self._close_state != "accepting":
                raise RuntimeError("Cannot subscribe to a closed RuntimeEventRouter")
            subscription = _RouterSubscription(self, handler)
            self._subscribers.append(subscription)
        return subscription  # type: ignore[return-value]

    def _normalize_path(self, raw: str) -> str | None:
        if not isinstance(raw, str):
            return None
        root = self.runtime.session.root.resolve()
        normalized = raw.replace("\\", "/")
        try:
            candidate = (Path(normalized) if Path(normalized).is_absolute() else root / normalized).resolve()
            relative = candidate.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            return None
        return relative.as_posix() if relative != Path(".") else ""

    def _paths_for(self, event) -> tuple[str, ...] | None:
        if isinstance(event, FileSystemChanged):
            raw_paths = (*event.paths, *event.old_paths)
        elif isinstance(event, AssetTagsChanged):
            # Batch form (rename_tag/delete_tag) carries every affected path
            # in ``paths`` with an empty ``file_path``; single-asset form
            # keeps ``file_path`` only.
            raw_paths = (
                (event.file_path, *event.paths) if event.file_path else event.paths
            )
        elif isinstance(event, (AssetNotesChanged, AssetRatingChanged, AssetUrlsChanged)):
            raw_paths = (event.file_path,)
        elif isinstance(event, FavoritesChanged):
            raw_paths = event.paths
        elif isinstance(event, CollectionChanged):
            # Membership changes carry every affected member path; catalog
            # mutations (create/rename/delete/query) carry none.
            raw_paths = event.paths
        else:
            return ()
        paths: list[str] = []
        for raw in raw_paths:
            path = self._normalize_path(raw)
            if path is None:
                _log.debug(
                    "Skipping unnormalizable path %r in invalidation event", raw
                )
                continue
            if path and path not in paths:
                paths.append(path)
        if raw_paths and not paths:
            return None
        return tuple(paths)

    def _on_event(self, event) -> None:
        with self._lock:
            if not self._accepting:
                return
            thread_id = threading.get_ident()
            self._inflight += 1
            self._active_by_thread[thread_id] = self._active_by_thread.get(thread_id, 0) + 1
        try:
            self._dispatch_event(event)
        finally:
            deferred: tuple[Callable[[], None], ...] = ()
            with self._lock:
                self._inflight -= 1
                active = self._active_by_thread[thread_id] - 1
                if active:
                    self._active_by_thread[thread_id] = active
                else:
                    del self._active_by_thread[thread_id]
                if self._inflight == 0 and self._close_state == "closing":
                    self._close_state = "drained"
                    deferred = tuple(self._deferred_after_drain)
                    self._deferred_after_drain.clear()
                self._drain_condition.notify_all()
            for action in deferred:
                try:
                    action()
                except Exception:
                    _log.exception("Deferred RuntimeEventRouter drain action failed")

    def defer_after_drain(self, action: Callable[[], None]) -> None:
        """Run an action after all callbacks, including the caller, return."""
        with self._lock:
            if self._close_state == "drained":
                run_now = True
            else:
                self._deferred_after_drain.append(action)
                run_now = False
        if run_now:
            action()

    def callback_active_on_current_thread(self) -> bool:
        with self._lock:
            return bool(self._active_by_thread.get(threading.get_ident(), 0))

    def _dispatch_event(self, event) -> None:
        with self._lock:
            token = getattr(event, "session_token", "")
            library_root = getattr(event, "library_root", "")
            if not token or not library_root or token != self.runtime.session.event_token:
                return
            try:
                if Path(library_root).resolve() != self.runtime.session.root.resolve():
                    return
            except (OSError, RuntimeError, ValueError):
                return
            paths = self._paths_for(event)
            if paths is None:
                return
            try:
                revision = self.runtime.next_revision()
            except RuntimeError:
                _log.warning(
                    "Dropping invalidation event for runtime %s: runtime is "
                    "closing or closed",
                    self.runtime.epoch,
                )
                return
            invalidation = InvalidationEvent(
                self.runtime.epoch, revision, EVENT_DOMAINS[type(event)], paths,
            )
            subscribers = tuple(self._subscribers)
        for subscription in subscribers:
            if not self._claim_subscription(subscription):
                if not self._accepting and threading.get_ident() == self._closing_thread_id:
                    return
                continue
            try:
                subscription._callback(invalidation)
            except Exception:
                _log.exception("Runtime invalidation subscriber failed")
            finally:
                self._release_subscription(subscription)

    def _claim_subscription(self, subscription: _RouterSubscription) -> bool:
        with self._lock:
            if not self._accepting or not subscription._active:
                return False
            thread_id = threading.get_ident()
            subscription._inflight += 1
            subscription._active_by_thread[thread_id] = (
                subscription._active_by_thread.get(thread_id, 0) + 1
            )
            return True

    def _release_subscription(self, subscription: _RouterSubscription) -> None:
        with self._lock:
            subscription._inflight -= 1
            thread_id = threading.get_ident()
            active = subscription._active_by_thread[thread_id] - 1
            if active:
                subscription._active_by_thread[thread_id] = active
            else:
                del subscription._active_by_thread[thread_id]
            self._drain_condition.notify_all()

    def close(self) -> bool:
        """Stop accepting events and drain callbacks within a bounded wait.

        ``True`` means the router reached ``drained``.  ``False`` means the
        caller is itself an in-flight callback or the bounded wait expired;
        the router deliberately remains in ``closing`` so a later callback
        release (or an explicit retry) can complete deferred cleanup.  A
        timeout must never be represented as ``drained`` because runtime
        resources may still be in use.
        """
        with self._lock:
            current_thread = threading.get_ident()
            own_callbacks = self._active_by_thread.get(current_thread, 0)
            if self._close_state == "drained":
                return True
            if self._close_state == "closing":
                if own_callbacks:
                    return False
                # Bounded wait for the owning close to finish draining; an
                # unbounded wait here deadlocks a second closer when the
                # owner's drain stalls.
                deadline = time.monotonic() + _CLOSE_DRAIN_TIMEOUT
                while self._close_state != "drained":
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        _log.warning(
                            "RuntimeEventRouter close drain timed out after %.1fs "
                            "while another close is in progress; keeping pending",
                            _CLOSE_DRAIN_TIMEOUT,
                        )
                        return False
                    self._drain_condition.wait(timeout=remaining)
                return True

            self._close_state = "closing"
            self._accepting = False
            self._closing_thread_id = current_thread
            subscriptions = tuple(self._event_subscriptions)
            self._event_subscriptions.clear()
            router_subscribers = tuple(self._subscribers)
            self._subscribers.clear()
            for subscription in router_subscribers:
                subscription._active = False

        for subscription in subscriptions:
            subscription.close()

        with self._lock:
            deadline = time.monotonic() + _CLOSE_DRAIN_TIMEOUT
            while self._inflight > own_callbacks:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _log.warning(
                        "RuntimeEventRouter close drain timed out after %.1fs with "
                        "%d in-flight callback(s); keeping pending",
                        _CLOSE_DRAIN_TIMEOUT,
                        self._inflight - own_callbacks,
                    )
                    # Keep ``closing`` until the final callback releases.  A
                    # caller must not proceed to tear down runtime services
                    # while an event callback can still touch them.
                    return False
                self._drain_condition.wait(timeout=remaining)
            if own_callbacks == 0 and self._inflight == 0:
                self._close_state = "drained"
                self._drain_condition.notify_all()
                return True
            # The only remaining callback(s) belong to this close caller.
            # ``_on_event`` will transition to drained and run deferred
            # actions after the callback returns.
            return False
