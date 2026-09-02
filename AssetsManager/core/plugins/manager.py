"""Plugin manager — discover, load, enable/disable plugins."""
from __future__ import annotations

import logging
import sys
import threading
import weakref
from collections.abc import Collection, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterable, Protocol, cast

from AssetsManager.core.plugins.descriptor import (
    PLUGIN_STATE_ACTIVE, PLUGIN_STATE_DISABLED, PLUGIN_STATE_ERROR,
    PLUGIN_STATE_INVALID, PLUGIN_STATE_LOADED, PLUGIN_STATE_LOADABLE,
    PluginDescriptor, PluginDiagnostic, PluginLoadResult, PluginRecord,
    build_plugin_record,
)
from AssetsManager.core.plugins.host_context import PluginHostContext
from AssetsManager.core.plugins.loader import PluginLoader

_log = logging.getLogger(__name__)

# PluginHostContext instances can be shared by independently-created manager
# services. Keep their callback serialization with the host rather than any
# one manager, without requiring a lock field on PluginHostContext itself.
_host_callback_locks_lock = threading.Lock()
_host_callback_locks: weakref.WeakKeyDictionary[PluginHostContext, threading.Lock] = weakref.WeakKeyDictionary()
_host_callback_active = threading.local()


def _host_callback_lock(host_context: PluginHostContext) -> threading.Lock:
    with _host_callback_locks_lock:
        lock = _host_callback_locks.get(host_context)
        if lock is None:
            lock = threading.Lock()
            _host_callback_locks[host_context] = lock
        return lock


# Category registries live in the application layer (asset_filters +
# format_utils); the plugin core receives them through this seam so core
# never imports application modules.  Installed by application.plugin_service.
class _CategoryExtensionRegistry(Protocol):
    """Structural stand-in for the application layer's CategoryExtensionRegistry.

    Test providers may hand over a plain dict instead (handled by the
    ``hasattr`` fallback at the call site), so the seam is typed structurally:
    an object exposing ``rebuild()``.
    """

    def rebuild(
        self,
        contributions: Sequence[tuple[str, str, Collection[str], str]],
        category_map: dict[str, str],
        base_map: Mapping[str, str] | None = None,
    ) -> None: ...


# The declared seam element stays dict[str, set[str] | frozenset[str]] (what
# test providers hand over); registry objects are recovered with the Protocol
# cast at the call site — pyright does not narrow via hasattr on this union.
_CategoryRegistryProvider = Callable[
    [], tuple[dict[str, set[str] | frozenset[str]], dict[str, str]] | None
]
_category_registry_provider: _CategoryRegistryProvider | None = None


def set_category_registry_provider(provider: _CategoryRegistryProvider) -> None:
    """Install the application-layer category registry provider."""
    global _category_registry_provider
    _category_registry_provider = provider


def _category_registries() -> tuple[dict[str, set[str] | frozenset[str]], dict[str, str]] | None:
    provider = _category_registry_provider
    if provider is None:
        return None
    return provider()


class PluginManagerService:
    _instance: PluginManagerService | None = None
    _lock: threading.Lock = threading.Lock()

    @classmethod
    def get(cls) -> PluginManagerService:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(
        self,
        *,
        search_paths: Iterable[str | Path] | None = None,
        loader: PluginLoader | None = None,
    ):
        self.search_paths = [Path(p) for p in (search_paths or self.default_search_paths())]
        self.loader = loader or PluginLoader()
        self._records: dict[str, PluginRecord] = {}
        self._records_lock = threading.RLock()
        self._host_context: PluginHostContext | None = None
        self._plugin_categories: dict[str, set[str]] = {}  # plugin_id -> {category_key, ...}
        self._plugin_theme_tokens: dict[str, set[str]] = {}  # plugin_id -> {token_name, ...}
        # Lifecycle callbacks must not run while _records_lock is held, but
        # load and unload for one record must still be serialized. Conditions
        # use the manager lock so discovery cannot replace a record mid-flight.
        self._record_conditions: dict[str, threading.Condition] = {}
        self._record_transitions: dict[str, tuple[str, int]] = {}
        # None denotes that the latest discovery removed the plugin while its
        # incumbent record was transitioning.
        self._pending_discoveries: dict[str, PluginRecord | None] = {}
        self._disabled_plugin_ids: set[str] = set()
        self._discovery_requested_revision = 0

    def _record_condition_locked(self, plugin_id: str) -> threading.Condition:
        condition = self._record_conditions.get(plugin_id)
        if condition is None:
            condition = threading.Condition(self._records_lock)
            self._record_conditions[plugin_id] = condition
        return condition

    def _begin_record_transition(
        self, plugin_id: str, transition: str,
    ) -> tuple[PluginRecord | None, bool]:
        """Claim one record, waiting only outside lifecycle callbacks."""
        if getattr(_host_callback_active, "plugin_id", None) is not None:
            _log.warning(
                "Plugin '%s' rejected %s requested from a lifecycle callback",
                plugin_id, transition,
            )
            return self.plugin_record(plugin_id), False
        owner = threading.get_ident()
        with self._records_lock:
            record = self._records.get(plugin_id)
            if record is None:
                return None, False
            condition = self._record_condition_locked(plugin_id)
            while plugin_id in self._record_transitions:
                current_transition, current_owner = self._record_transitions[plugin_id]
                if current_owner == owner:
                    _log.warning(
                        "Plugin '%s' rejected re-entrant %s during %s",
                        plugin_id, transition, current_transition,
                    )
                    return record, False
                condition.wait()
                record = self._records.get(plugin_id)
                if record is None:
                    return None, False
            self._record_transitions[plugin_id] = (transition, owner)
            return record, True

    def _end_record_transition(self, plugin_id: str) -> None:
        with self._records_lock:
            transition = self._record_transitions.pop(plugin_id, None)
            if plugin_id in self._pending_discoveries and self._records.get(plugin_id) is not None:
                pending = self._pending_discoveries[plugin_id]
                # A transition owns its incumbent record until callbacks and
                # rollback complete. Keep the latest discovery outcome behind
                # a live instance and apply it only after that instance is gone.
                current = self._records[plugin_id]
                if current.plugin_instance is None:
                    if pending is None:
                        self._records.pop(plugin_id, None)
                    else:
                        if transition is not None and transition[0] == "disable":
                            # Explicit disable intent wins over manifest defaults
                            # from a discovery snapshot that arrived in flight.
                            pending.enabled = False
                            pending.state = PLUGIN_STATE_DISABLED
                        self._records[plugin_id] = pending
                    self._pending_discoveries.pop(plugin_id, None)
            condition = self._record_conditions.get(plugin_id)
            if condition is not None:
                condition.notify_all()

    @contextmanager
    def _host_callback(self, host_context: PluginHostContext, plugin_id: str):
        """Serialize callbacks against a shared PluginHostContext instance."""
        lock = _host_callback_lock(host_context)
        lock.acquire()
        _host_callback_active.plugin_id = plugin_id
        try:
            yield
        finally:
            _host_callback_active.plugin_id = None
            lock.release()

    def _has_live_records_locked(self, *, exclude: str | None = None) -> bool:
        return any(
            pid != exclude and (
                record.plugin_instance is not None or pid in self._record_transitions
            )
            for pid, record in self._records.items()
        )

    def default_search_paths(self) -> list[Path]:
        """Default plugin search paths.

        Writable user locations first (``RuntimeData/Shared/plugins/`` and the
        per-user ``Plugins/Addons/``), then the read-only bundled seed plugins
        (``_MEIPASS/Plugins/Addons`` in frozen builds).  Discovery treats an
        identical plugin id across sources as a conflict (invalidated), so the
        bundled source is appended last and only participates when present.
        """
        from AssetsManager.core.path_resolver import (
            SHARED_DIR,
            addons_dir,
            builtin_plugins_addons_dir,
        )
        paths = [SHARED_DIR / "plugins", addons_dir()]
        builtin = builtin_plugins_addons_dir()
        if builtin is not None:
            paths.append(builtin)
        return paths

    def discover_plugins(self, search_paths: Iterable[str | Path] | None = None) -> list[PluginDescriptor]:
        with self._records_lock:
            self._discovery_requested_revision += 1
            request_revision = self._discovery_requested_revision
        resolved = [Path(p) for p in (search_paths or self.search_paths)]
        discovered: dict[str, PluginRecord] = {}

        for search_path in resolved:
            if not search_path.exists() or not search_path.is_dir():
                continue
            for child in sorted(search_path.iterdir(), key=lambda x: x.name.lower()):
                if not child.is_dir():
                    continue
                manifest_path = child / "plugin.json"
                if not manifest_path.exists():
                    continue
                record = build_plugin_record(manifest_path)
                dup = discovered.get(record.plugin_id)
                if dup is not None:
                    dup.diagnostics.append(PluginDiagnostic(
                        "error", "manifest.duplicate_id",
                        f"Duplicate plugin id '{record.plugin_id}' at {record.manifest_path}.",
                        plugin_id=record.plugin_id, source=record.manifest_path,
                    ))
                    dup.state = PLUGIN_STATE_INVALID
                    dup.enabled = False
                    continue
                discovered[record.plugin_id] = record

        with self._records_lock:
            if request_revision != self._discovery_requested_revision:
                return [r.descriptor for r in self._records.values() if r.descriptor is not None]
            existing = self._records
            merged: dict[str, PluginRecord] = {}
            # Every discovery pass supplies an explicit outcome for every
            # retained record: its fresh descriptor or removal. This replaces
            # any earlier pending outcome even while the record is simply
            # loaded, not only while a transition happens to be active.
            plugin_ids = list(discovered)
            plugin_ids.extend(plugin_id for plugin_id in existing if plugin_id not in discovered)
            for plugin_id in plugin_ids:
                current = existing.get(plugin_id)
                outcome = discovered.get(plugin_id)
                if outcome is not None and plugin_id in self._disabled_plugin_ids:
                    outcome.enabled = False
                    outcome.state = PLUGIN_STATE_DISABLED
                if current is not None and (
                    current.plugin_instance is not None
                    or plugin_id in self._record_transitions
                ):
                    self._pending_discoveries[plugin_id] = outcome
                    merged[plugin_id] = current
                elif outcome is not None:
                    self._pending_discoveries.pop(plugin_id, None)
                    merged[plugin_id] = outcome
                else:
                    self._pending_discoveries.pop(plugin_id, None)
            self._records = merged
        # Restore persisted disabled state from AppSettings
        try:
            from AssetsManager.core.settings import AppSettings
            disabled_ids = set(AppSettings.instance().get("plugin_disabled_ids", []))
            with self._records_lock:
                self._disabled_plugin_ids.update(disabled_ids)
                for pid, record in self._records.items():
                    if (
                        pid in self._disabled_plugin_ids
                        and record.plugin_instance is None
                        and pid not in self._record_transitions
                    ):
                        record.enabled = False
                        record.state = PLUGIN_STATE_DISABLED
        except Exception:
            pass
        with self._records_lock:
            return [r.descriptor for r in self._records.values() if r.descriptor is not None]

    def list_plugins(self) -> list[PluginDescriptor]:
        with self._records_lock:
            return [r.descriptor for r in self._records.values() if r.descriptor is not None]

    def plugin_record(self, plugin_id: str) -> PluginRecord | None:
        with self._records_lock:
            return self._records.get(str(plugin_id or "").strip())

    def enable_plugin(self, plugin_id: str) -> bool:
        normalized_id = str(plugin_id or "").strip()
        record, claimed = self._begin_record_transition(normalized_id, "enable")
        if record is None or not claimed:
            return False
        try:
            with self._records_lock:
                if record.descriptor is None or record.state == PLUGIN_STATE_INVALID:
                    return False
                was_loaded = record.plugin_instance is not None
                self._disabled_plugin_ids.discard(normalized_id)
                record.enabled = True
                if record.state == PLUGIN_STATE_DISABLED:
                    record.state = PLUGIN_STATE_LOADABLE
                host = self._host_context
        finally:
            self._end_record_transition(normalized_id)

        if not was_loaded and host is not None:
            result = self.load_plugin(normalized_id, host)
            if not result.ok:
                with self._records_lock:
                    current = self._records.get(normalized_id)
                    if current is not None and current.plugin_instance is None:
                        current.enabled = False
                        current.state = PLUGIN_STATE_DISABLED
                        self._disabled_plugin_ids.add(normalized_id)
                self._persist_enabled_state()
                return False
        self._persist_enabled_state()
        return True

    def disable_plugin(self, plugin_id: str) -> bool:
        normalized_id = str(plugin_id or "").strip()
        record, claimed = self._begin_record_transition(normalized_id, "disable")
        if record is None or not claimed:
            return False
        try:
            if not self._unload_claimed_record(record, normalized_id):
                return False
            with self._records_lock:
                # The original transition remains claimed until this point, so
                # another load cannot interleave after unregister cleanup.
                record.enabled = False
                record.state = PLUGIN_STATE_DISABLED
                self._disabled_plugin_ids.add(normalized_id)
                # Persist the durable intent before releasing this transition,
                # so discovery cannot publish an enabled replacement in between.
                self._persist_enabled_state_locked()
            return True
        finally:
            self._end_record_transition(normalized_id)

    def _persist_enabled_state_locked(self) -> None:
        """Save disabled IDs while the caller holds ``_records_lock``."""
        try:
            from AssetsManager.core.settings import AppSettings
            disabled = sorted(self._disabled_plugin_ids)
            settings = AppSettings.instance()
            settings.set("plugin_disabled_ids", disabled)
            settings.save()
        except Exception:
            pass

    def _persist_enabled_state(self) -> None:
        """Save disabled plugin IDs to AppSettings."""
        with self._records_lock:
            self._persist_enabled_state_locked()

    def load_plugin(self, plugin_id: str, host_context: PluginHostContext | None = None) -> PluginLoadResult:
        normalized_id = str(plugin_id or "").strip()
        record, claimed = self._begin_record_transition(normalized_id, "load")
        if record is None:
            return PluginLoadResult(False, plugin_id, PLUGIN_STATE_ERROR,
                                    (PluginDiagnostic("error", "plugin.not_found", f"Plugin '{plugin_id}' not found."),))
        if not claimed:
            return PluginLoadResult(
                False, record.plugin_id, record.state,
                (PluginDiagnostic(
                    "error", "plugin.lifecycle_in_progress",
                    "Plugin lifecycle transition is already in progress.",
                ),),
            )

        effective_host: PluginHostContext | None = None
        try:
            with self._records_lock:
                if record.descriptor is None or record.state == PLUGIN_STATE_INVALID:
                    return PluginLoadResult(False, record.plugin_id, record.state, tuple(record.diagnostics))
                if not record.enabled or record.state == PLUGIN_STATE_DISABLED:
                    return PluginLoadResult(False, record.plugin_id, PLUGIN_STATE_DISABLED, tuple(record.diagnostics))
                if record.plugin_instance is not None:
                    # PluginRecord.host_context is declared `object | None` in
                    # core/plugins/descriptor.py; it only ever holds contexts
                    # this manager installed (see below), so the cast is sound.
                    effective_host = cast("PluginHostContext | None", record.host_context)
                    requested_host = host_context if host_context is not None else self._host_context
                    if requested_host is not None and effective_host is not requested_host:
                        return PluginLoadResult(
                            False, record.plugin_id, record.state,
                            (PluginDiagnostic(
                                "error", "plugin.host_context_conflict",
                                "Plugin is already loaded through a different host context.",
                            ),),
                        )
                    return PluginLoadResult(True, record.plugin_id, record.state, tuple(record.diagnostics))

                if host_context is not None:
                    if self._host_context is not None and self._host_context is not host_context:
                        # One manager instance serves exactly one host context.
                        _log.warning(
                            "Plugin '%s' load refused: manager is already bound to a different host context",
                            record.plugin_id,
                        )
                        return PluginLoadResult(
                            False, record.plugin_id, record.state,
                            (PluginDiagnostic(
                                "error", "plugin.host_context_conflict",
                                "Manager is already bound to a different host context.",
                            ),),
                        )
                    self._host_context = host_context
                    host_context.set_apply_hooks(
                        apply_categories=self.apply_registered_categories,
                        apply_theme_tokens=self.apply_registered_theme_tokens,
                    )

                # No host passed: fall back to the bound context rather than
                # storing None on the record and stripping its registration path.
                effective_host = host_context if host_context is not None else self._host_context
                descriptor = record.descriptor
                record_id = record.plugin_id
                root_dir = record.root_dir

            loaded = self.loader.load(record_id, root_dir, descriptor.entry)
            with self._records_lock:
                record.module = loaded.module
                record.plugin_instance = loaded.plugin_instance
                record.host_context = effective_host
                record.state = PLUGIN_STATE_LOADED

            if effective_host is not None:
                # PluginHostContext owns shared contribution registries, so all
                # callback activity through this manager's bound host is global
                # serialized even when different plugin records are loading.
                with self._host_callback(effective_host, record_id):
                    with effective_host._host_identity():
                        effective_host.grant_permissions(record_id, descriptor.permissions)
                    if hasattr(loaded.plugin_instance, "register"):
                        register = getattr(loaded.plugin_instance, "register")
                        with effective_host._host_identity_scope(
                            effective_host._registering_plugin_var, record_id
                        ):
                            register(effective_host)
                        with self._records_lock:
                            record.state = PLUGIN_STATE_ACTIVE
            with self._records_lock:
                state = record.state
                diagnostics = tuple(record.diagnostics)
            _log.info("Plugin '%s' loaded (%s)", record_id, state)
            return PluginLoadResult(True, record_id, state, diagnostics)
        except Exception as exc:
            _log.exception("Failed to load plugin '%s'", record.plugin_id)
            if effective_host is not None:
                # Load-failure cleanup mutates the same shared host registries.
                with self._host_callback(effective_host, record.plugin_id):
                    with effective_host._host_identity():
                        effective_host.unregister_plugin(record.plugin_id)
            with self._records_lock:
                record.diagnostics.append(PluginDiagnostic(
                    "error", "plugin.load_failed", f"Load failed: {exc}",
                    plugin_id=record.plugin_id, source=record.manifest_path,
                ))
                record.state = PLUGIN_STATE_ERROR
                record.module = None
                record.plugin_instance = None
                record.host_context = None
                if not self._has_live_records_locked(exclude=normalized_id):
                    self._host_context = None
                diagnostics = tuple(record.diagnostics)
            return PluginLoadResult(False, record.plugin_id, PLUGIN_STATE_ERROR, diagnostics)
        finally:
            self._end_record_transition(normalized_id)


    def _unload_claimed_record(self, record: PluginRecord, normalized_id: str) -> bool:
        """Unload a record whose lifecycle transition is already claimed."""
        with self._records_lock:
            instance = record.plugin_instance
            ctx: PluginHostContext | None = record.host_context  # type: ignore[assignment]
        unregister_failed = False
        if ctx is not None:
            with self._host_callback(ctx, normalized_id):
                if instance is not None and hasattr(instance, "unregister"):
                    try:
                        unregister = getattr(instance, "unregister")
                        with ctx._host_identity_scope(
                            ctx._registering_plugin_var, normalized_id
                        ):
                            unregister(ctx)
                    except Exception as exc:
                        _log.exception("Failed to unload plugin '%s'", record.plugin_id)
                        with self._records_lock:
                            record.diagnostics.append(PluginDiagnostic(
                                "error", "plugin.unload_failed", f"Unload failed: {exc}",
                                plugin_id=record.plugin_id, source=record.manifest_path,
                            ))
                            record.state = PLUGIN_STATE_ERROR
                        unregister_failed = True
                try:
                    with ctx._host_identity():
                        ctx.unregister_plugin(normalized_id)
                except Exception:
                    _log.exception(
                        "Failed to clean host contributions for plugin '%s'",
                        record.plugin_id,
                    )
                self.remove_registered_categories(normalized_id)
                self.remove_registered_theme_tokens(normalized_id)
        else:
            self.remove_registered_categories(normalized_id)
            self.remove_registered_theme_tokens(normalized_id)
        with self._records_lock:
            if record.module is not None:
                module_name = getattr(record.module, "__name__", None)
                if module_name and module_name in sys.modules:
                    del sys.modules[module_name]
            record.module = None
            record.plugin_instance = None
            record.host_context = None
            record.state = PLUGIN_STATE_ERROR if unregister_failed else (
                PLUGIN_STATE_LOADABLE if record.enabled else PLUGIN_STATE_DISABLED
            )
            if not self._has_live_records_locked(exclude=normalized_id):
                self._host_context = None
        return not unregister_failed

    def unload_plugin(self, plugin_id: str) -> bool:
        normalized_id = str(plugin_id or "").strip()
        record, claimed = self._begin_record_transition(normalized_id, "unload")
        if record is None or not claimed:
            return False
        try:
            return self._unload_claimed_record(record, normalized_id)
        finally:
            self._end_record_transition(normalized_id)

    def unload_all(self) -> bool:
        """Unload every loaded plugin; returns True when all succeeded.

        Iterates a snapshot because ``unload_plugin`` mutates record state
        (and clears the host binding once the last plugin is gone).
        """
        with self._records_lock:
            loaded = [
                record.plugin_id
                for record in tuple(self._records.values())
                if record.plugin_instance is not None
            ]
        succeeded = True
        for plugin_id in loaded:
            try:
                if not self.unload_plugin(plugin_id):
                    succeeded = False
            except Exception:
                _log.exception("Failed to unload plugin '%s'", plugin_id)
                succeeded = False
        return succeeded

    def load_all_enabled(self, host_context: PluginHostContext | None = None) -> list[PluginLoadResult]:
        """Load all enabled plugins. Returns results for each.

        Rebinding to a different host context is refused per plugin by
        ``load_plugin``; assigning it here first would leave the manager
        pointing at the new host while the refused records still reference
        the old one.
        """
        with self._records_lock:
            if host_context is not None and (
                self._host_context is None or self._host_context is host_context
            ):
                self._host_context = host_context
            # Omitting the host preserves the manager's current binding so a
            # later bulk load still registers through the live host.
            if host_context is not None:
                host_context.set_apply_hooks(
                    apply_categories=self.apply_registered_categories,
                    apply_theme_tokens=self.apply_registered_theme_tokens,
                )
            # Snapshot under the manager lock. Each load then claims its own
            # record and runs callbacks without holding the global lock, so a
            # concurrent discovery cannot mutate the dict during iteration.
            plugin_ids = [
                record.plugin_id
                for record in tuple(self._records.values())
                if record.enabled and record.state == PLUGIN_STATE_LOADABLE
            ]
        results = []
        for plugin_id in plugin_ids:
            results.append(self.load_plugin(plugin_id, host_context))
        return results

    # ── File parsing (info.fields extension point) ──────────────

    def parse_file(self, file_path: str) -> dict[str, dict[str, str]]:
        """Run all matching parsers on a file and return merged results.

        Checks both plugin instances with match/parse and file handlers
        registered via PluginHostContext.register_file_handler().

        Returns:
            {plugin_id: {key: value, ...}} for all matching plugins.
        """
        results: dict[str, dict[str, str]] = {}

        # Instance match/parse and host-registered handlers used to run as two
        # independent paths, so a plugin that did both was invoked twice.
        # Prefer the host registry; fall back to the instance only when that
        # plugin has not already registered a handler.
        registered_ids: set[str] = set()
        if self._host_context is not None:
            for handler in self._host_context.file_handlers():
                registered_ids.add(handler.plugin_id)
                try:
                    if handler.match(file_path):
                        parsed = handler.parse(file_path)
                        if isinstance(parsed, dict) and parsed:
                            results[handler.plugin_id] = parsed
                except Exception:
                    _log.warning("File handler '%s' failed to parse '%s'", handler.plugin_id, file_path, exc_info=True)

        for record in self._records.values():
            if not record.enabled or record.plugin_instance is None:
                continue
            if record.plugin_id in registered_ids:
                continue
            instance = record.plugin_instance
            match_fn = getattr(instance, "match", None)
            parse_fn = getattr(instance, "parse", None)
            if match_fn is None or parse_fn is None:
                continue
            try:
                if match_fn(file_path):
                    parsed = parse_fn(file_path)
                    if isinstance(parsed, dict) and parsed:
                        results[record.plugin_id] = parsed
            except Exception:
                _log.warning("Plugin '%s' failed to parse '%s'", record.plugin_id, file_path, exc_info=True)

        return results

    def get_display_fields(self) -> list[dict[str, str]]:
        """Return all display_fields from all enabled plugins, merged."""
        fields: list[dict[str, str]] = []
        for record in self._records.values():
            if not record.enabled or record.descriptor is None:
                continue
            for field in record.descriptor.display_fields:
                fields.append({
                    "plugin_id": record.plugin_id,
                    "key": field.key,
                    "label_key": field.label_key,
                    "type": field.type,
                })
        return fields

    def apply_registered_categories(self) -> None:
        """Apply categories registered via PluginHostContext.register_category().

        The mutation targets are provided by the application composition
        root through :func:`set_category_registry_provider`, so core keeps no
        static dependency on application filter modules.
        """
        if self._host_context is None:
            return
        registries = _category_registries()
        if registries is None:
            _log.warning(
                "Category registry provider is not installed; plugin categories "
                "were not applied"
            )
            return
        filter_category_exts, category_map = registries
        contributions = [
            (cat.key, cat.label, cat.extensions, cat.plugin_id)
            for cat in self._host_context.categories()
        ]
        from AssetsManager.core.format_utils import _BUILTIN_CATEGORY_MAP
        if hasattr(filter_category_exts, "rebuild"):
            # Application-layer CategoryExtensionRegistry (declared to the seam
            # as a plain dict, so recover its rebuild() via the Protocol).
            registry = cast("_CategoryExtensionRegistry", filter_category_exts)
            registry.rebuild(contributions, category_map, _BUILTIN_CATEGORY_MAP)
        else:
            # Compatibility for test/application providers that expose plain
            # dicts. Keep the same built-in and first-owner-wins semantics as
            # CategoryExtensionRegistry.rebuild().
            plugin_keys = (
                set().union(*self._plugin_categories.values())
                if self._plugin_categories else set()
            )
            builtin_keys = set(filter_category_exts) - plugin_keys
            for key in plugin_keys:
                filter_category_exts.pop(key, None)
            category_map.clear()
            category_map.update(_BUILTIN_CATEGORY_MAP)
            occupied_extensions = set(category_map)
            latest_by_key = {}
            for cat in self._host_context.categories():
                key = str(cat.key or "").strip()
                extensions = {
                    str(ext).strip().lower()
                    for ext in cat.extensions
                    if str(ext).strip()
                }
                if key and key not in builtin_keys and extensions:
                    latest_by_key[key] = (key, extensions)
            for key, extensions in latest_by_key.values():
                available = extensions - occupied_extensions
                if not available:
                    continue
                filter_category_exts[key] = available
                category_map.update({ext: key for ext in available})
                occupied_extensions.update(available)
        self._plugin_categories = {}
        for key, _label, _extensions, owner in contributions:
            self._plugin_categories.setdefault(owner, set()).add(key)
            _log.info("Registered category '%s' (plugin: %s)", key, owner)

    def remove_registered_categories(self, plugin_id: str) -> None:
        """Remove one owner's categories and restore remaining/built-in entries."""
        target = str(plugin_id or "").strip()
        self._plugin_categories.pop(target, None)
        if self._host_context is not None:
            self.apply_registered_categories()
        for key in set().union(*self._plugin_categories.values()) if self._plugin_categories else set():
            _log.debug("Retained category '%s' after unloading plugin '%s'", key, target)

    def apply_registered_theme_tokens(self) -> None:
        """Apply theme tokens registered via PluginHostContext.register_theme_token().

        This updates the global theme fallbacks so the new tokens are available
        in themes.get() and stylesheet generation.
        Tracks which plugin registered each token for cleanup on unload.
        """
        if self._host_context is None:
            return
        from AssetsManager.core import themes
        contributions = list(self._host_context.theme_tokens())
        themes.set_plugin_token_fallbacks(contributions)
        self._plugin_theme_tokens = {}
        for token in contributions:
            self._plugin_theme_tokens.setdefault(token.plugin_id, set()).add(token.token)
            _log.info("Registered theme token '%s' with fallback '%s' (plugin: %s)", token.token, token.fallback, token.plugin_id)

    def remove_registered_theme_tokens(self, plugin_id: str) -> None:
        """Remove global theme token registrations owned by a plugin."""
        target = str(plugin_id or "").strip()
        self._plugin_theme_tokens.pop(target, None)
        if self._host_context is not None:
            self.apply_registered_theme_tokens()
