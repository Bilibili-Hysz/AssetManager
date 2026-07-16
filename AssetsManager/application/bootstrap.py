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
from dataclasses import dataclass

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
from AssetsManager.core.plugins import PluginHostContext
from AssetsManager.di import ServiceContainer

_log = logging.getLogger(__name__)


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


class ApplicationBootstrap:
    """Wires all application services into a ``ServiceContainer``.

    Usage::

        bootstrap = ApplicationBootstrap()
        bootstrap.discover_plugins()
        lib_svc = bootstrap.resolve(LibraryService)
    """

    def __init__(self, container: ServiceContainer | None = None):
        self.container = container or ServiceContainer()
        self._plugin_host: PluginHostContext | None = None
        self._plugin_svc: PluginService | None = None
        self._undo_services: dict[int, tuple[LibrarySession, UndoService]] = {}
        self._register_services()
        self.library_service.add_session_close_listener(self._cleanup_session)

    # ── Service registration ─────────────────────────────────────

    def _register_services(self) -> None:
        c = self.container
        # Core infrastructure — no dependencies
        c.register(DatabaseManager)
        # Core services — class-based registration (auto-singleton)
        c.register(LibraryService, deps=[DatabaseManager])
        c.register(AssetService)
        c.register(MetadataService)
        c.register(TagService)
        c.register(FileOperationService)
        c.register(ThumbnailService)
        c.register(SearchService)
        # ProjectService is created directly in for_library() with connection_provider
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

    # ── Convenience accessors ────────────────────────────────────

    def resolve(self, service_type):
        """Resolve a service from the container."""
        return self.container.resolve(service_type)

    def for_library(self, session: LibrarySession) -> LibraryScopedServices:
        """Return a bundle of services scoped to a specific library session."""
        if not self.library_service.owns_live_session(session):
            raise ValueError(
                "LibrarySession must be the live canonical session owned by this bootstrap"
            )
        provider = session.connection_for
        key = id(session)
        cached = self._undo_services.get(key)
        if cached is None or cached[0] is not session:
            cached = (session, UndoService(library_root=session.root_str, session=session))
            self._undo_services[key] = cached
        return LibraryScopedServices(
            session=session,
            asset_service=self.container.resolve(AssetService),
            metadata_service=MetadataService(connection_provider=provider, session=session),
            tag_service=TagService(connection_provider=provider, session=session),
            project_service=ProjectService(connection_provider=provider, session=session),
            thumbnail_service=self.container.resolve(ThumbnailService),
            search_service=self.container.resolve(SearchService),
            file_operation_service=FileOperationService(
                session=session,
                asset_index_service=self.container.resolve(AssetIndexService),
            ),
            undo_service=cached[1],
            plugin_service=self.container.resolve(PluginService),
            asset_index_service=self.container.resolve(AssetIndexService),
        )

    def _cleanup_session(self, session: LibrarySession) -> None:
        cached = self._undo_services.get(id(session))
        if cached is not None and cached[0] is session:
            self._undo_services.pop(id(session))
            cached[1].cleanup()

    def cleanup_library(self, library_root: str) -> None:
        """Clean up undo services for closed sessions at a legacy call site."""
        for session, service in tuple(self._undo_services.values()):
            if session.root_str == library_root and session.is_closed:
                self._undo_services.pop(id(session), None)
                service.cleanup()

    @property
    def library_service(self) -> LibraryService:
        return self.container.resolve(LibraryService)
