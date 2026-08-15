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
from pathlib import Path
import sqlite3
from typing import TYPE_CHECKING, Callable, cast

from AssetsManager.application.asset_index_service import AssetIndexService
from AssetsManager.application.asset_index_reconciliation_service import AssetIndexReconciliationService
from AssetsManager.application.app_settings_provider import install_app_settings_provider
from AssetsManager.application.auth_service import AuthService
from AssetsManager.application.asset_service import AssetService
from AssetsManager.application.context import ConnectionProvider, LibrarySession
from AssetsManager.application.database_integrity_service import DatabaseIntegrityService
from AssetsManager.application.database_maintenance_service import DatabaseMaintenanceService
from AssetsManager.application.file_operation_service import FileOperationService
from AssetsManager.application.favorite_service import FavoriteService
from AssetsManager.application.gallery_service import GalleryService
from AssetsManager.application.library_export_service import LibraryExportService
from AssetsManager.application.library_watcher_service import LibraryWatcherService
from AssetsManager.application.library_service import LibraryService
from AssetsManager.application.metadata_service import MetadataService
from AssetsManager.application.plugin_service import PluginService
from AssetsManager.application.reconciliation_queue import ReconciliationQueue
from AssetsManager.application.reconciliation_queue_migration import (
    migrate_reconciliation_marker,
)
from AssetsManager.application.reconciliation_queue_store import (
    SQLiteReconciliationQueueStore,
)
from AssetsManager.application.project_service import ProjectService
from AssetsManager.application.search_service import SearchService
from AssetsManager.application.share_service import ShareService
from AssetsManager.application.tag_service import TagService
from AssetsManager.application.thumbnail_service import ThumbnailService
from AssetsManager.application.undo_service import UndoService
from AssetsManager.core.database import DatabaseManager
from AssetsManager.core.directory_cache import DirectoryCache
from AssetsManager.core.performance import PerformanceRecorder
from AssetsManager.core.path_resolver import RootIdentity, library_data_dir
from AssetsManager.core.plugins import PluginHostContext
from AssetsManager.core.plugins.host_context import install_event_bus_provider
from AssetsManager.core.settings import AppSettings
from AssetsManager.di import ServiceContainer
from AssetsManager.domain.event_bus import get_event_bus

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
    gallery_service: GalleryService | None = None
    favorite_service: FavoriteService | None = None


_MISSING = object()


class _LanServicesHolder:
    """Single-flight lazy projection owned by one service snapshot.

    A failed attempt is observed by every thread that joined that generation,
    while a later caller may start a new attempt. The mutable holder is kept
    outside the frozen snapshot's repr/equality/hash value semantics.

    Lock order contract: the session lifecycle condition may be held while
    taking the holder condition only in the publication direction
    (``_publish_while_live`` -> ``_publish``). The holder condition is never
    held while acquiring the session condition: liveness checks in ``get``
    run outside the holder lock (the ``ready`` state is monotonic, so a
    value captured under the holder lock stays valid). Every nested
    acquisition therefore shares one order, and the two call paths cannot
    deadlock against each other.
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
            ready_value = _MISSING
            with self._condition:
                if self._state == "ready":
                    assert self._value is not None
                    ready_value = self._value
                elif self._state == "building":
                    if self._building_thread_id == current_thread_id:
                        raise RuntimeError(
                            "Recursive LAN service materialization is not allowed"
                        )
                    return self._wait_for_generation(self._generation)

            if ready_value is not _MISSING:
                # Session liveness is verified outside the holder lock:
                # "ready" is a monotonic state, so the captured value remains
                # valid. Checking is_closed under the holder lock would nest
                # holder -> session-condition locks — the reverse of the
                # session -> holder order used by _publish_while_live ->
                # _publish — which could deadlock those two call paths.
                if self._session.is_closed:
                    raise RuntimeError(
                        "Cannot use retained LAN services from a closed LibrarySession"
                    )
                return cast(LanRuntimeServices, ready_value)

            # Avoid taking the session lifecycle lock while holding the holder
            # lock. Publication is the only path that nests session -> holder.
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
    integrity_service: DatabaseIntegrityService
    maintenance_service: DatabaseMaintenanceService
    export_service: LibraryExportService
    metadata_service: MetadataService
    tag_service: TagService
    thumbnail_service: ThumbnailService
    file_operation_service: FileOperationService
    undo_service: UndoService
    plugin_service: PluginService
    asset_index_service: AssetIndexService
    _lan_holder: _LanServicesHolder = field(repr=False, compare=False, hash=False)
    performance_recorder: PerformanceRecorder | None = None
    reconciliation_queue: ReconciliationQueue | None = None
    reconciliation_service: AssetIndexReconciliationService | None = None

    @property
    def lan_services(self) -> LanRuntimeServices:
        """Return the once-materialized LAN-only application projection."""
        return self._lan_holder.get()

    def close_lan_services(self) -> None:
        """Close already-materialized LAN services, never materializing them.

        ``GalleryService`` subscribes to the global event bus in its
        constructor; runtime teardown must close it (and any other LAN
        service with subscriptions) when it was composed, otherwise the
        subscription leaks for the life of the process.  Services that were
        never materialized are left untouched.
        """
        if self._lan_holder._state != "ready":
            return
        value = self._lan_holder._value
        assert value is not None  # "ready" always has a published value
        # getattr keeps teardown tolerant of fakes/older snapshots that lack
        # the field (e.g. test doubles using SimpleNamespace).
        gallery = getattr(value, "gallery_service", None)
        if gallery is not None:
            gallery.close()

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
        # G3: the single settings-singleton call site in the application layer.
        # Every other application module resolves settings through the seam.
        self._app_settings = AppSettings.instance()
        install_app_settings_provider(lambda: self._app_settings)
        # G4: core plugin hooks subscribe through this seam instead of
        # importing the domain event bus directly.
        install_event_bus_provider(get_event_bus)
        self._plugin_host: PluginHostContext | None = None
        self._plugin_svc: PluginService | None = None
        self._plugin_load_failures: list[str] = []
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
        """Discover and load plugins. Returns loaded descriptors.

        Individual plugin failures are never swallowed silently: failed plugin
        ids are recorded in :attr:`plugin_load_failures`, and unexpected
        discovery/loading errors are logged with ``_log.exception``. The
        plugin service is dropped (``plugin_service`` becomes ``None``) only
        when the container itself cannot resolve it; a broken or missing
        plugin never tears down an otherwise usable service.
        """
        self._plugin_load_failures = []
        try:
            self._plugin_svc = self.container.resolve(PluginService)
        except Exception:
            _log.exception("Cannot resolve plugin service; plugin support disabled")
            self._plugin_svc = None
            self._plugin_load_failures.append("<resolve>")
            return []
        try:
            descriptors = self._plugin_svc.discover()
        except Exception:
            _log.exception("Plugin discovery failed")
            self._plugin_load_failures.append("<discover>")
            return []
        if not descriptors:
            return []
        _log.info("Discovered %d plugin(s): %s",
                  len(descriptors), [d.id for d in descriptors])
        self._plugin_host = PluginHostContext()
        try:
            results = self._plugin_svc.load_all_enabled(self._plugin_host)
        except Exception:
            _log.exception("Plugin loading failed")
            self._plugin_load_failures.append("<load>")
            return descriptors
        failed = [r.plugin_id for r in results if not r.ok]
        if failed:
            self._plugin_load_failures.extend(failed)
            _log.warning("Failed to load plugin(s): %s", failed)
        loaded = [r.plugin_id for r in results if r.ok]
        if loaded:
            _log.info("Loaded plugin(s): %s", loaded)
        return descriptors

    @property
    def plugin_host_context(self) -> PluginHostContext | None:
        return self._plugin_host

    @property
    def plugin_service(self) -> PluginService | None:
        return self._plugin_svc

    @property
    def plugin_load_failures(self) -> tuple[str, ...]:
        """Return plugins that failed during the last discovery pass."""
        return tuple(self._plugin_load_failures)

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
                    if not cached.is_open:
                        raise RuntimeError(
                            "Cannot return a closing or closed LibraryRuntime"
                        )
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

        runtime = None
        published = False
        try:
            services = self._build_services(session)
            runtime = LibraryRuntime(session=session, services=services)
            for adapter_name in (
                "integrity_service",
                "maintenance_service",
                "reconciliation_service",
            ):
                adapter = getattr(services, adapter_name, None)
                if adapter is not None:
                    runtime.register_lifecycle_adapter(adapter)
            self._start_library_watcher(runtime, session)
            reconciliation_service = getattr(services, "reconciliation_service", None)
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
                    if reconciliation_service is not None:
                        reconciliation_service.start()
                    if (
                        not self.library_service.owns_live_session(session)
                        or session.is_closed
                    ):
                        reject = True
                    else:
                        self._runtimes[key] = runtime
                        published = True
                        return runtime
            if reject:
                raise ValueError(
                    "LibrarySession was closed while its Runtime was being created"
                )
            runtime.close()
            if cached is None:
                raise RuntimeError("Runtime cache disappeared during creation")
            return cached
        except BaseException as error:
            if runtime is not None and not published:
                try:
                    runtime.close()
                except BaseException as cleanup_error:
                    try:
                        error.add_note(
                            f"Runtime construction cleanup is pending: {cleanup_error}"
                        )
                    except (AttributeError, TypeError):
                        pass
            raise
        finally:
            with self._runtime_lock:
                gate = self._runtime_creation.pop(key, None)
                if gate is not None:
                    gate.set()

    def _start_library_watcher(self, runtime: "LibraryRuntime", session: LibrarySession) -> None:
        """Start the resident library watcher when the interval setting enables it.

        A non-positive interval disables the watcher, preserving the previous
        behaviour (only the navigation panel's ``QFileSystemWatcher`` is used).
        The watcher is registered as a lifecycle adapter so ``Runtime.close()``
        calls its ``stop()`` when the session is torn down — no window-level
        bookkeeping is needed for library switches.
        """
        from AssetsManager.core.settings import (
            DEFAULT_LIBRARY_WATCHER_INTERVAL,
            LIBRARY_WATCHER_INTERVAL_KEY,
        )

        interval = self._app_settings.get(
            LIBRARY_WATCHER_INTERVAL_KEY, DEFAULT_LIBRARY_WATCHER_INTERVAL
        )
        if not isinstance(interval, (int, float)) or isinstance(interval, bool) or interval <= 0:
            return
        watcher = LibraryWatcherService(session, interval_seconds=float(interval))
        runtime.register_lifecycle_adapter(watcher)
        watcher.start()

    @staticmethod
    def _strict_connection_provider(
        provider: Callable[..., sqlite3.Connection],
    ) -> Callable[[str | Path | RootIdentity], sqlite3.Connection]:
        """Wrap a canonical provider with fail-closed ownership validation."""

        def strict_provider(
            root: str | Path | RootIdentity,
        ) -> sqlite3.Connection:
            return DatabaseManager.require_managed_connection_owner(root, provider(root))

        return strict_provider

    def _build_services(self, session: LibrarySession) -> LibraryScopedServices:
        identity = session.context.root_identity
        captured_generation = self.library_service._session_generations.get(identity.map_key)

        # Preserve the bound provider identity for runtime/LAN binding checks.
        # Validate its first canonical connection separately so a monkeypatched
        # provider returning an unmanaged raw connection still fails closed.
        provider = session.connection_for

        def restore_state_provider(_root=None):
            return self.library_service.restore_state_provider(identity)

        def restore_acknowledger(_root=None, token=None):
            state = restore_state_provider(identity)
            if state is not None and captured_generation is not None:
                current_generation = self.library_service._root_generation(identity.map_key)
                if state.generation != captured_generation or current_generation != captured_generation:
                    raise RuntimeError(
                        "Restore recovery acknowledgement rejected: stale or unknown token"
                    )
                if token != state.token:
                    raise RuntimeError(
                        "Restore recovery acknowledgement rejected: stale or unknown token"
                    )
            self.library_service.restore_acknowledger(identity, token)
            return None
        with session.operation():
            connection = DatabaseManager.require_managed_connection_owner(
                identity, provider(identity)
            )
            asset_index_service = AssetIndexService.for_session(session)
            reconciliation_marker = library_data_dir(identity) / "reconciliation-queue.json"
            reconciliation_store = SQLiteReconciliationQueueStore(
                connection=connection,
                library_root=session.root,
            )
            migrate_reconciliation_marker(
                marker_path=reconciliation_marker,
                library_root=session.root,
                store=reconciliation_store,
            )
            reconciliation_queue = ReconciliationQueue(
                library_root=session.root_str,
                persistence_store=reconciliation_store,
                # SQLite generation polling is the cross-process wakeup
                # fallback; Condition remains the same-process fast path.
                cross_process_poll_interval=0.5,
            )
            reconciliation_service = AssetIndexReconciliationService(
                session=session,
                asset_index_service=asset_index_service,
                reconciliation_queue=reconciliation_queue,
                # A runtime worker may recover from a bounded burst of
                # unexpected infrastructure failures, but it must still
                # become visibly faulted instead of retrying forever.
                max_worker_restarts=2,
                worker_restart_backoff=1.0,
                max_persistence_conflict_retries=2,
                persistence_conflict_backoff=0.05,
            )
            token_secret = secrets.token_hex(32)
            sharing_services = RuntimeSharingServices(
                token_secret=token_secret,
                auth_service=AuthService(connection, token_secret, session=session),
                share_service=ShareService(connection, token_secret, session=session),
            )
            sharing_services.auth_service.init_tables()
            sharing_services.share_service.init_table()
            export_service = LibraryExportService(
                connection_provider=provider,
                session=session,
                restore_coordinator=self.library_service.restore_reservation,
                restore_state_provider=restore_state_provider,
                restore_acknowledger=restore_acknowledger,
            )

            return LibraryScopedServices(
                session=session,
                sharing_services=sharing_services,
                integrity_service=DatabaseIntegrityService(
                    connection_provider=provider,
                    session=session,
                ),
                maintenance_service=DatabaseMaintenanceService(
                    connection_provider=provider,
                    session=session,
                ),
                export_service=export_service,
                metadata_service=MetadataService.for_session(session),
                tag_service=TagService.for_session(session),
                thumbnail_service=ThumbnailService(
                    connection_provider=provider, session=session
                ),
                file_operation_service=FileOperationService(
                    session=session,
                    asset_index_service=asset_index_service,
                    performance_recorder=self._performance_recorder,
                    reconciliation_queue=reconciliation_queue,
                ),
                undo_service=UndoService(
                    library_root=session.root_str,
                    session=session,
                    performance_recorder=self._performance_recorder,
                ),
                plugin_service=self.container.resolve(PluginService),
                asset_index_service=asset_index_service,
                _lan_holder=_LanServicesHolder(
                    session,
                    partial(self._build_lan_services, connection_provider=provider),
                ),
                performance_recorder=self._performance_recorder,
                reconciliation_queue=reconciliation_queue,
                reconciliation_service=reconciliation_service,
            )

    def _build_lan_services(
        self,
        session: LibrarySession,
        *,
        connection_provider: ConnectionProvider | None = None,
        asset_index_service: AssetIndexService | None = None,
    ) -> LanRuntimeServices:
        provider = connection_provider if connection_provider is not None else session.connection_for
        index_service = asset_index_service
        if index_service is None:
            index_service = (
                AssetIndexService.for_session(session)
                if isinstance(session, LibrarySession)
                else self.container.resolve(AssetIndexService)
            )
        is_canonical_provider = (
            getattr(provider, "__self__", None) is session
            and getattr(provider, "__func__", None) is LibrarySession.connection_for
        )
        if not is_canonical_provider:
            provider = self._strict_connection_provider(provider)
        return LanRuntimeServices(
            asset_service=AssetService(
                directory_cache=DirectoryCache(
                    provider(session.root), library_root=session.root, session=session
                ),
                performance_recorder=self._performance_recorder,
                session_token=session.event_token,
                session=session,
            ),
            project_service=ProjectService(connection_provider=provider, session=session),
            search_service=SearchService(
                performance_recorder=self._performance_recorder,
                session_token=session.event_token,
                connection_provider=provider,
                session=session,
                asset_index_service=index_service,
            ),
            gallery_service=GalleryService(connection_provider=provider, session=session),
            favorite_service=FavoriteService(connection_provider=provider, session=session),
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
            with runtime._condition:
                cleanup_complete = (
                    runtime._state == "closed"
                    and not runtime._cleanup_in_progress
                    and not runtime._adapter_cleanup_in_progress
                )
            if not cleanup_complete:
                raise RuntimeError(
                    "Runtime cleanup is pending; retry close_session after cleanup drains"
                )
            with self._runtime_lock:
                if self._runtimes.get(id(session)) is runtime:
                    self._runtimes.pop(id(session), None)

    @property
    def library_service(self) -> LibraryService:
        return self.container.resolve(LibraryService)
