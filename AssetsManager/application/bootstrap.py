"""Application bootstrap — explicit service wiring via DI container.

Centralizes service creation and plugin discovery so that ``app.py``
does not scatter singleton calls throughout the startup sequence.

Note: AuthService and ShareService are NOT registered here because they
require a ``db_conn`` and ``token_secret`` that are only available after
a library is opened and the LAN server is started.  They are created by
``_LanServerImpl._startup()`` and passed to route handlers at runtime.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from AssetsManager.application.asset_index_service import AssetIndexService
from AssetsManager.application.asset_service import AssetService
from AssetsManager.application.context import LibrarySession
from AssetsManager.application.file_operation_service import FileOperationService
from AssetsManager.application.library_service import LibraryService
from AssetsManager.application.metadata_service import MetadataService
from AssetsManager.application.plugin_service import PluginService
from AssetsManager.application.project_service import ProjectService
from AssetsManager.application.search_service import SearchService
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
class LibraryScopedServices:
    """Service bundle bound to a specific ``LibrarySession``.

    Services that need per-library database access receive
    ``session.connection_for`` as their connection provider. Stateless services
    are resolved from the application container.
    """

    session: LibrarySession
    asset_service: AssetService
    metadata_service: MetadataService
    tag_service: TagService
    project_service: ProjectService
    thumbnail_service: ThumbnailService
    search_service: SearchService
    file_operation_service: FileOperationService
    undo_service: UndoService
    plugin_service: PluginService
    asset_index_service: AssetIndexService
    performance_recorder: PerformanceRecorder | None = None


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
        # ProjectService is created directly in _build_services() with connection_provider
        c.register(AssetIndexService)
        c.register(UndoService)
        c.register(PluginService)
        # AuthService / ShareService are NOT registered here — they require
        # db_conn + token_secret from the LAN server at runtime.

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
        return LibraryScopedServices(
            session=session,
            asset_service=AssetService(
                directory_cache=DirectoryCache(session.connection_for(session.root)),
                performance_recorder=self._performance_recorder,
                session_token=session.event_token,
            ),
            metadata_service=MetadataService(connection_provider=provider, session=session),
            tag_service=TagService(connection_provider=provider, session=session),
            project_service=ProjectService(connection_provider=provider, session=session),
            thumbnail_service=ThumbnailService(connection_provider=provider),
            search_service=SearchService(
                performance_recorder=self._performance_recorder,
                session_token=session.event_token,
                connection_provider=provider,
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
            performance_recorder=self._performance_recorder,
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
