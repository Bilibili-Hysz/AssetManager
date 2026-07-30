"""Canonical per-library application runtime."""
from __future__ import annotations

import threading
import uuid

from AssetsManager.application.bootstrap import LibraryScopedServices
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
        self._lifecycle_adapters: list[object] = []
        self.event_router = RuntimeEventRouter(self)

    def register_lifecycle_adapter(self, adapter: object) -> None:
        """Register an adapter that must stop before runtime-owned cleanup."""
        with self._condition:
            if self._state == "open":
                if not any(current is adapter for current in self._lifecycle_adapters):
                    self._lifecycle_adapters.append(adapter)
                return
            stop = getattr(adapter, "stop")
        stop()

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
        with self._condition:
            self._state = "closing"
        if self.event_router.callback_active_on_current_thread():
            self.event_router.defer_after_drain(self._cleanup_adapters)
            return
        self._cleanup_adapters()

    def _cleanup_adapters(self) -> None:
        try:
            with self._condition:
                lifecycle_adapters = tuple(self._lifecycle_adapters)
            for adapter in lifecycle_adapters:
                adapter.stop()
            self.services.undo_service.cleanup()
            with self._condition:
                self._lifecycle_adapters.clear()
        except BaseException:
            with self._condition:
                self._state = "open"
                self._cleanup_in_progress = False
                self._condition.notify_all()
            raise
        with self._condition:
            self._state = "closed"
            self._cleanup_in_progress = False
            self._condition.notify_all()
