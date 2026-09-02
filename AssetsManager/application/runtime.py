"""Canonical per-library application runtime."""
from __future__ import annotations

import threading
import uuid
from typing import Protocol, cast

from AssetsManager.application.bootstrap import LibraryScopedServices, RuntimeSharingServices
from AssetsManager.application.context import LibrarySession
from AssetsManager.application.runtime_events import RuntimeEventRouter


class _LifecycleAdapter(Protocol):
    def stop(self) -> None: ...


class LibraryRuntime:
    """Own the services and lifecycle adapters for one live session."""

    def __init__(self, *, session: LibrarySession, services: LibraryScopedServices):
        self.session = session
        self.services = services
        self.epoch = uuid.uuid4().hex
        self.revision = 0
        self._condition = threading.Condition(threading.Lock())
        self._state = "open"
        self._cleanup_in_progress = False
        # Set while the router has stopped admission but still has an
        # external callback in flight.  A second close caller must not block
        # forever on a stalled callback; the deferred cleanup is the single
        # owner that will finish once the callback returns.
        self._cleanup_pending = False
        self._adapters_stopped = False
        self._adapter_cleanup_in_progress = False
        self._adapter_cleanup_thread_id: int | None = None
        self._lifecycle_adapters: list[_LifecycleAdapter] = []
        self.event_router = RuntimeEventRouter(self)

    @property
    def sharing_services(self) -> RuntimeSharingServices:
        """Return this Runtime session's immutable sharing service bundle."""
        return self.services_snapshot.sharing_services

    @property
    def services_snapshot(self) -> LibraryScopedServices:
        """Return the immutable service bundle for this runtime's session.

        ``LibraryScopedServices`` is a frozen dataclass.  Keeping this access
        point on the runtime makes the lifetime boundary explicit for UI
        consumers: a panel must capture the bundle belonging to the runtime
        it was bound to, rather than resolving services again after a library
        switch.
        """
        return self.services

    @property
    def is_open(self) -> bool:
        """Return whether this runtime still accepts new work."""
        with self._condition:
            return self._state == "open"

    def register_lifecycle_adapter(self, adapter: object) -> bool:
        """Register an adapter that must stop before runtime-owned cleanup."""
        with self._condition:
            if self._state == "open":
                if not any(current is adapter for current in self._lifecycle_adapters):
                    self._lifecycle_adapters.append(cast(_LifecycleAdapter, adapter))
                return True
            stop = getattr(adapter, "stop")
        stop()
        return False

    def try_register_lifecycle_adapter(self, adapter: object) -> bool:
        """Register an adapter only while this Runtime is still accepting work."""
        with self._condition:
            if self._state != "open":
                return False
            if not any(current is adapter for current in self._lifecycle_adapters):
                self._lifecycle_adapters.append(cast(_LifecycleAdapter, adapter))
            return True

    def unregister_lifecycle_adapter(self, adapter: object) -> None:
        with self._condition:
            self._lifecycle_adapters = [
                current for current in self._lifecycle_adapters if current is not adapter
            ]

    def next_revision(self) -> int:
        # An event callback admitted before close must be allowed to finish
        # publishing its revision.  New callbacks are rejected by the router
        # before they reach this method, so this exception does not reopen the
        # runtime for new work.
        callback_active = self.event_router.callback_active_on_current_thread()
        with self._condition:
            if self._state != "open" and not (
                self._state == "closing" and callback_active
            ):
                raise RuntimeError("Cannot advance a closing or closed LibraryRuntime")
            self.revision += 1
            return self.revision

    def mark_closing(self) -> bool:
        """Reject new runtime work, then begin bounded event-router drain.

        The state transition is the admission linearization point.  Existing
        callbacks are still allowed to finish, while callers can observe a
        ``False`` result when the bounded drain is pending and must defer
        resource teardown until a later retry/callback completion.
        """
        with self._condition:
            if self._state in {"open", "failed"}:
                self._state = "closing"
        return self.event_router.close()

    def close_adapters(self) -> None:
        """Stop external adapters while the owning session is still usable."""
        current_thread_id = threading.get_ident()
        with self._condition:
            if self._state == "closed":
                return
            if self._adapters_stopped:
                return
            while self._adapter_cleanup_in_progress:
                if self._adapter_cleanup_thread_id == current_thread_id:
                    return
                self._condition.wait()
                if self._state == "closed" or self._adapters_stopped:
                    return
            self._state = "closing"
            self._adapter_cleanup_in_progress = True
            self._adapter_cleanup_thread_id = current_thread_id
            lifecycle_adapters = tuple(self._lifecycle_adapters)
        try:
            for adapter in lifecycle_adapters:
                cast(_LifecycleAdapter, adapter).stop()
        except BaseException:
            with self._condition:
                self._state = "failed"
                self._adapters_stopped = False
                self._adapter_cleanup_in_progress = False
                self._adapter_cleanup_thread_id = None
                self._condition.notify_all()
            raise
        with self._condition:
            self._adapters_stopped = True
            self._adapter_cleanup_in_progress = False
            self._adapter_cleanup_thread_id = None
            self._condition.notify_all()

    def close(self) -> bool:
        """Release runtime-owned adapters, without closing the session/DB."""
        callback_thread = self.event_router.callback_active_on_current_thread()
        with self._condition:
            while self._cleanup_in_progress:
                if callback_thread or self._cleanup_pending:
                    return False
                self._condition.wait()
            if self._state == "closed":
                return True
            # Linearize admission before touching the router.  A callback
            # already counted by the router may still finish, but no new
            # caller can advance a revision or register an adapter.
            if self._state == "open":
                self._state = "closing"
            self._cleanup_in_progress = True
        try:
            drained = self.event_router.close()
        except BaseException:
            # The router close is not part of adapter cleanup; keep the
            # guard releasable so later close() calls are not permanently
            # blocked waiting on a flag that never resets.
            with self._condition:
                self._cleanup_in_progress = False
                self._cleanup_pending = False
                self._condition.notify_all()
            raise
        if not drained:
            with self._condition:
                if self._cleanup_pending:
                    return False
                self._cleanup_pending = True
            self.event_router.defer_after_drain(self._cleanup_adapters)
            return False
        self._cleanup_adapters()
        return True

    def _cleanup_adapters(self) -> None:
        with self._condition:
            self._cleanup_pending = False
        try:
            self.close_adapters()
            self.services.undo_service.cleanup()
            # Close already-materialized LAN services that hold event-bus
            # subscriptions (gallery_service), without materializing them if
            # the LAN adapter was never composed for this session.
            self.services.close_lan_services()
        except BaseException:
            with self._condition:
                self._state = "failed"
                self._cleanup_in_progress = False
                self._cleanup_pending = False
                self._adapters_stopped = False
                self._condition.notify_all()
            raise
        with self._condition:
            self._lifecycle_adapters.clear()
            self._adapters_stopped = False
            self._state = "closed"
            self._cleanup_in_progress = False
            self._cleanup_pending = False
            self._condition.notify_all()
