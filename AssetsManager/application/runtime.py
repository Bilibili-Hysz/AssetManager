"""Canonical per-library application runtime."""
from __future__ import annotations

import threading
import uuid

from AssetsManager.application.bootstrap import LibraryScopedServices, RuntimeSharingServices
from AssetsManager.application.context import LibrarySession
from AssetsManager.application.runtime_events import RuntimeEventRouter


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
        self._adapters_stopped = False
        self._adapter_cleanup_in_progress = False
        self._adapter_cleanup_thread_id: int | None = None
        self._lifecycle_adapters: list[object] = []
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

    def register_lifecycle_adapter(self, adapter: object) -> bool:
        """Register an adapter that must stop before runtime-owned cleanup."""
        with self._condition:
            if self._state == "open":
                if not any(current is adapter for current in self._lifecycle_adapters):
                    self._lifecycle_adapters.append(adapter)
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
                self._lifecycle_adapters.append(adapter)
            return True

    def unregister_lifecycle_adapter(self, adapter: object) -> None:
        with self._condition:
            self._lifecycle_adapters = [
                current for current in self._lifecycle_adapters if current is not adapter
            ]

    def next_revision(self) -> int:
        with self._condition:
            if self._state == "closed":
                raise RuntimeError("Cannot advance a closed LibraryRuntime")
            self.revision += 1
            return self.revision

    def mark_closing(self) -> None:
        """Close the event router before rejecting new runtime revisions."""
        self.event_router.close()
        with self._condition:
            if self._state == "open":
                self._state = "closing"

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
                adapter.stop()
        except BaseException:
            with self._condition:
                self._state = "open"
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

    def close(self) -> None:
        """Release runtime-owned adapters, without closing the session/DB."""
        callback_thread = self.event_router.callback_active_on_current_thread()
        with self._condition:
            while self._cleanup_in_progress:
                if callback_thread:
                    return
                self._condition.wait()
            if self._state == "closed":
                return
            self._cleanup_in_progress = True
        self.event_router.close()
        if self.event_router.callback_active_on_current_thread():
            self.event_router.defer_after_drain(self._cleanup_adapters)
            return
        self._cleanup_adapters()

    def _cleanup_adapters(self) -> None:
        try:
            self.close_adapters()
            self.services.undo_service.cleanup()
        except BaseException:
            with self._condition:
                self._state = "open"
                self._cleanup_in_progress = False
                self._adapters_stopped = False
                self._condition.notify_all()
            raise
        with self._condition:
            self._lifecycle_adapters.clear()
            self._adapters_stopped = False
            self._state = "closed"
            self._cleanup_in_progress = False
            self._condition.notify_all()
