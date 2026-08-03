"""Application bootstrap — explicit service wiring via DI container.

Centralizes service creation and plugin discovery so that ``app.py``
does not scatter singleton calls throughout the startup sequence.

AuthService and ShareService are registered into each per-session Runtime
bundle after its library connection is opened. LAN-only services remain lazy.
"""
from __future__ import annotations

import logging
import secrets
import threading
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING, Callable

from AssetsManager.application.asset_index_service import AssetIndexService
from AssetsManager.application.auth_service import AuthService
from AssetsManager.application.asset_service import AssetService
from AssetsManager.application.context import ConnectionProvider, LibrarySession
from AssetsManager.application.file_operation_service import FileOperationService
from AssetsManager.application.library_service import LibraryService
from AssetsManager.application.metadata_service import MetadataService
from AssetsManager.application.plugin_service import PluginService
from AssetsManager.application.project_service import ProjectService
from AssetsManager.application.search_service import SearchService
from AssetsManager.application.share_service import ShareService
from AssetsManager.application.tag_service import TagService
from AssetsManager.application.thumbnail_service import ThumbnailService
from AssetsManager.application.undo_service import UndoService
from AssetsManager.core.database import DatabaseManager
from AssetsManager.core.directory_cache import DirectoryCache
from AssetsManager.core.performance import PerformanceRecorder
from AssetsManager.core.plugins import PluginHostContext
from AssetsManager.di import ServiceContainer

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from AssetsManager.application.runtime import LibraryRuntime


@dataclass(frozen=True)
class RuntimeSharingServices:
    """Authentication and sharing services bound to one Runtime session."""

    token_secret: str = field(repr=False)
    auth_service: AuthService
    share_service: ShareService


@dataclass(frozen=True)
class LanRuntimeServices:
    """Application services materialized only when a LAN adapter is composed."""

    asset_service: AssetService
    project_service: ProjectService
    search_service: SearchService


_MISSING = object()


class _LanServicesHolder:
    """Single-flight lazy projection owned by one service snapshot.

    A failed attempt is observed by every thread that joined that generation,
    while a later caller may start a new attempt. The mutable holder is kept
    outside the frozen snapshot's repr/equality/hash value semantics.
    """

    def __init__(
        self,
        session: LibrarySession,
        factory: Callable[[LibrarySession], LanRuntimeServices],
    ) -> None:
        self._session = session
        self._factory = factory
        self._condition = threading.Condition(threading.Lock())
        self._state = "empty"
        self._generation = 0
        self._building_thread_id: int | None = None
        self._value: LanRuntimeServices | None = None
        self._failures: dict[int, BaseException] = {}
        self._waiters: dict[int, int] = {}

    def get(self) -> LanRuntimeServices:
        current_thread_id = threading.get_ident()
        while True:
            with self._condition:
                if self._state == "ready":
                    assert self._value is not None
                    return self._value
                if self._state == "building":
                    if self._building_thread_id == current_thread_id:
                        raise RuntimeError(
                            "Recursive LAN service materialization is not allowed"
                        )
                    return self._wait_for_generation(self._generation)

            # Avoid taking the session lifecycle lock while holding the holder
            # lock. Publication intentionally uses the reverse lock order.
            if self._session.is_closed:
                raise RuntimeError(
                    "Cannot materialize LAN services for a closed LibrarySession"
                )

            with self._condition:
                if self._state != "empty":
                    continue
                self._generation += 1
                generation = self._generation
                self._state = "building"
                self._building_thread_id = current_thread_id
                break

        try:
            with self._session.operation():
                value = self._factory(self._session)
                return self._session._publish_while_live(
                    lambda: self._publish(generation, value)
                )
        except BaseException as exc:
            with self._condition:
                if self._state == "building" and self._generation == generation:
                    self._state = "empty"
                    self._building_thread_id = None
                    if self._waiters.get(generation, 0):
                        self._failures[generation] = exc
                    self._condition.notify_all()
            raise

    def _publish(
        self, generation: int, value: LanRuntimeServices
    ) -> LanRuntimeServices:
        with self._condition:
            if self._state != "building" or self._generation != generation:
                raise RuntimeError("LAN service materialization attempt lost ownership")
            self._value = value
            self._state = "ready"
            self._building_thread_id = None
            self._condition.notify_all()
            return value

    def _wait_for_generation(self, generation: int) -> LanRuntimeServices:
        self._waiters[generation] = self._waiters.get(generation, 0) + 1
        while True:
            failure = self._failures.get(generation, _MISSING)
            if failure is not _MISSING:
                self._release_waiter(generation)
                assert isinstance(failure, BaseException)
                raise failure
            if self._state == "ready":
                assert self._value is not None
                self._release_waiter(generation)
                return self._value
            self._condition.wait()

    def _release_waiter(self, generation: int) -> None:
        remaining = self._waiters[generation] - 1
        if remaining:
            self._waiters[generation] = remaining
            return
        self._waiters.pop(generation, None)
        self._failures.pop(generation, None)


@dataclass(frozen=True)
class LibraryScopedServices:
    """Service bundle bound to a specific ``LibrarySession``.

    The snapshot itself and its Desktop/shared fields are created eagerly.
    LAN-only application services are projected once through a private holder
    without changing this frozen snapshot's visible value semantics.
    """

    session: LibrarySession
    sharing_services: RuntimeSharingServices
    metadata_service: MetadataService
    tag_service: TagService
    thumbnail_service: ThumbnailService
    file_operation_service: FileOperationService
    undo_service: UndoService
    plugin_service: PluginService
    asset_index_service: AssetIndexService
    _lan_holder: _LanServicesHolder = field(repr=False, compare=False, hash=False)
    performance_recorder: PerformanceRecorder | None = None

    @property
    def lan_services(self) -> LanRuntimeServices:
        """Return the once-materialized LAN-only application projection."""
        return self._lan_holder.get()

    @property
    def asset_service(self) -> AssetService:
        """Compatibility read-through to the LAN-only service projection."""
        return self.lan_services.asset_service

    @property
    def project_service(self) -> ProjectService:
        """Compatibility read-through to the LAN-only service projection."""
        return self.lan_services.project_service

    @property
    def search_service(self) -> SearchService:
        """Compatibility read-through to the LAN-only service projection."""
        return self.lan_services.search_service

class ApplicationBootstrap:
    """Wires all application services into a ``ServiceContainer``.

    Usage::

        bootstrap = ApplicationBootstrap()
        bootstrap.discover_plugins()
        lib_svc = bootstrap.resolve(LibraryService)
    """

    def __init__(
        self,
        container: ServiceContainer | None = None,
        performance_recorder: PerformanceRecorder | None = None,
    ):
        self.container = container or ServiceContainer()
        self._performance_recorder = performance_recorder
        self._plugin_host: PluginHostContext | None = None
        self._plugin_svc: PluginService | None = None
        self._runtimes: dict[int, "LibraryRuntime"] = {}
        self._runtime_lock = threading.Lock()
        self._runtime_creation: dict[int, threading.Event] = {}
        self._register_services()
        self.library_service.add_session_closing_listener(self._close_runtime)
        self.library_service.add_session_close_listener(self._cleanup_session)

    # ── Service registration ─────────────────────────────────────

    def _register_services(self) -> None:
        c = self.container
        # Core infrastructure — no dependencies
        c.register(DatabaseManager, instance=DatabaseManager(self._performance_recorder))
        # Core services — class-based registration (auto-singleton)
        c.register(LibraryService, deps=[DatabaseManager])
        c.register(AssetService)
        c.register(MetadataService)
        c.register(TagService)
        c.register(FileOperationService)
        c.register(ThumbnailService)
        c.register(SearchService)
        # ProjectService is created in the lazy LAN projection with its
        # session provider.
        c.register(AssetIndexService)
        c.register(UndoService)
        c.register(PluginService)
        # AuthService / ShareService are per-Runtime services because their
        # connection and token secret belong to one opened library session.

    # ── Plugin lifecycle ─────────────────────────────────────────

    def discover_plugins(self) -> list:
        """Discover and load plugins. Returns loaded descriptors."""
        try:
            self._plugin_svc = self.container.resolve(PluginService)
            descriptors = self._plugin_svc.discover()
            if descriptors:
                _log.info("Discovered %d plugin(s): %s",
                          len(descriptors), [d.id for d in descriptors])
                self._plugin_host = PluginHostContext()
                results = self._plugin_svc.load_all_enabled(self._plugin_host)
                loaded = [r.plugin_id for r in results if r.ok]
                if loaded:
                    _log.info("Loaded plugin(s): %s", loaded)
            return descriptors
        except Exception:
            _log.exception("Plugin discovery failed")
            self._plugin_svc = None
            return []

    @property
    def plugin_host_context(self) -> PluginHostContext | None:
        return self._plugin_host

    @property
    def plugin_service(self) -> PluginService | None:
        return self._plugin_svc

    @property
    def performance_recorder(self) -> PerformanceRecorder | None:
        return self._performance_recorder

    # ── Convenience accessors ────────────────────────────────────

    def resolve(self, service_type):
        """Resolve a service from the container."""
        return self.container.resolve(service_type)

    def runtime_for(self, session: LibrarySession) -> "LibraryRuntime":
        """Return the one Runtime owned by this bootstrap for ``session``."""
        if not self.library_service.owns_live_session(session):
            raise ValueError(
                "LibrarySession must be the live canonical session owned by this bootstrap"
            )
        key = id(session)
        from AssetsManager.application.runtime import LibraryRuntime
        while True:
            with self._runtime_lock:
                cached = self._runtimes.get(key)
                if cached is not None and cached.session is session:
                    return cached
                gate = self._runtime_creation.get(key)
                if gate is None:
                    gate = threading.Event()
                    self._runtime_creation[key] = gate
                    creator = True
                else:
                    creator = False
            if creator:
                break
            gate.wait()

        try:
            runtime = LibraryRuntime(session=session, services=self._build_services(session))
            with self._runtime_lock:
                if (
                    not self.library_service.owns_live_session(session)
                    or session.is_closed
                ):
                    reject = True
                    cached = None
                else:
                    reject = False
                    cached = self._runtimes.get(key)
                if not reject and (cached is None or cached.session is not session):
                    self._runtimes[key] = runtime
                    return runtime
            if reject:
                runtime.close()
                raise ValueError(
                    "LibrarySession was closed while its Runtime was being created"
                )
            runtime.close()
            if cached is None:
                raise RuntimeError("Runtime cache disappeared during creation")
            return cached
        finally:
            with self._runtime_lock:
                gate = self._runtime_creation.pop(key, None)
                if gate is not None:
                    gate.set()

    def _build_services(self, session: LibrarySession) -> LibraryScopedServices:
        provider = session.connection_for
        with session.operation():
            connection = provider(session.root)
            token_secret = secrets.token_hex(32)
            sharing_services = RuntimeSharingServices(
                token_secret=token_secret,
                auth_service=AuthService(connection, token_secret, session=session),
                share_service=ShareService(connection, token_secret, session=session),
            )
            sharing_services.auth_service.init_tables()
            sharing_services.share_service.init_table()
            return LibraryScopedServices(
                session=session,
                sharing_services=sharing_services,
                metadata_service=MetadataService(connection_provider=provider, session=session),
                tag_service=TagService(connection_provider=provider, session=session),
                thumbnail_service=ThumbnailService(
                    connection_provider=provider, session=session
                ),
                file_operation_service=FileOperationService(
                    session=session,
                    asset_index_service=self.container.resolve(AssetIndexService),
                    performance_recorder=self._performance_recorder,
                ),
                undo_service=UndoService(
                    library_root=session.root_str,
                    session=session,
                    performance_recorder=self._performance_recorder,
                ),
                plugin_service=self.container.resolve(PluginService),
                asset_index_service=self.container.resolve(AssetIndexService),
                _lan_holder=_LanServicesHolder(
                    session,
                    partial(self._build_lan_services, connection_provider=provider),
                ),
                performance_recorder=self._performance_recorder,
            )

    def _build_lan_services(
        self,
        session: LibrarySession,
        *,
        connection_provider: ConnectionProvider | None = None,
    ) -> LanRuntimeServices:
        provider = (
            connection_provider
            if connection_provider is not None
            else session.connection_for
        )
        return LanRuntimeServices(
            asset_service=AssetService(
                directory_cache=DirectoryCache(provider(session.root)),
                performance_recorder=self._performance_recorder,
                session_token=session.event_token,
            ),
            project_service=ProjectService(connection_provider=provider, session=session),
            search_service=SearchService(
                performance_recorder=self._performance_recorder,
                session_token=session.event_token,
                connection_provider=provider,
            ),
        )

    def _close_runtime(self, session: LibrarySession) -> None:
        with self._runtime_lock:
            runtime = self._runtimes.get(id(session))
        if runtime is not None and runtime.session is session:
            runtime.mark_closing()
            runtime.close_adapters()

    def _cleanup_session(self, session: LibrarySession) -> None:
        with self._runtime_lock:
            runtime = self._runtimes.get(id(session))
        if runtime is not None and runtime.session is session:
            runtime.close()
            with self._runtime_lock:
                if self._runtimes.get(id(session)) is runtime:
                    self._runtimes.pop(id(session), None)

    @property
    def library_service(self) -> LibraryService:
        return self.container.resolve(LibraryService)
