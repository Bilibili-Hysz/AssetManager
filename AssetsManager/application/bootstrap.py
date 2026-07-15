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
        self._undo_services: dict[str, UndoService] = {}
        self._register_services()

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
        c.register(FileOperationService, deps=[AssetIndexService])
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
        provider = session.connection_for
        key = session.root_str
        if key not in self._undo_services:
            self._undo_services[key] = UndoService(library_root=key)
        return LibraryScopedServices(
            session=session,
            asset_service=self.container.resolve(AssetService),
            metadata_service=MetadataService(connection_provider=provider),
            tag_service=TagService(connection_provider=provider),
            project_service=ProjectService(connection_provider=provider),
            thumbnail_service=self.container.resolve(ThumbnailService),
            search_service=self.container.resolve(SearchService),
            file_operation_service=FileOperationService(
                asset_index_service=self.container.resolve(AssetIndexService),
                connection_provider=provider,
                library_root=session.root,
            ),
            undo_service=self._undo_services[key],
            plugin_service=self.container.resolve(PluginService),
            asset_index_service=self.container.resolve(AssetIndexService),
        )

    def cleanup_library(self, library_root: str) -> None:
        """Clean up cached UndoService for a closed library."""
        svc = self._undo_services.pop(library_root, None)
        if svc is not None:
            svc.cleanup()

    @property
    def library_service(self) -> LibraryService:
        return self.container.resolve(LibraryService)
