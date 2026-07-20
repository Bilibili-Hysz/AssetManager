"""Plugin manager — discover, load, enable/disable plugins."""
from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from typing import Iterable

from AssetsManager.core.plugins.descriptor import (
    PLUGIN_STATE_ACTIVE, PLUGIN_STATE_DISABLED, PLUGIN_STATE_ERROR,
    PLUGIN_STATE_INVALID, PLUGIN_STATE_LOADED, PLUGIN_STATE_LOADABLE,
    PluginDescriptor, PluginDiagnostic, PluginLoadResult, PluginRecord,
    build_plugin_record,
)
from AssetsManager.core.plugins.host_context import PluginHostContext
from AssetsManager.core.plugins.loader import PluginLoader

_log = logging.getLogger(__name__)


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

    def default_search_paths(self) -> list[Path]:
        """Default plugin search paths: RuntimeData/Shared/plugins/ and Plugins/Addons/."""
        from AssetsManager.core.database import SHARED_DIR
        from AssetsManager.core.path_resolver import addons_dir
        return [SHARED_DIR / "plugins", addons_dir()]

    def discover_plugins(self, search_paths: Iterable[str | Path] | None = None) -> list[PluginDescriptor]:
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
            self._records = discovered
        # Restore persisted disabled state from AppSettings
        try:
            from AssetsManager.core.settings import AppSettings
            disabled_ids = set(AppSettings.instance().get("plugin_disabled_ids", []))
            with self._records_lock:
                for pid, record in self._records.items():
                    if pid in disabled_ids:
                        record.enabled = False
                        from AssetsManager.core.plugins.descriptor import PLUGIN_STATE_DISABLED
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
        record = self.plugin_record(plugin_id)
        if record is None or record.descriptor is None:
            return False
        record.enabled = True
        if record.state not in {PLUGIN_STATE_ACTIVE, PLUGIN_STATE_LOADED}:
            record.state = PLUGIN_STATE_LOADABLE
        self._persist_enabled_state()
        return True

    def disable_plugin(self, plugin_id: str) -> bool:
        record = self.plugin_record(plugin_id)
        if record is None:
            return False
        if not self.unload_plugin(plugin_id):
            return False
        record.enabled = False
        record.state = PLUGIN_STATE_DISABLED
        self._persist_enabled_state()
        return True

    def _persist_enabled_state(self) -> None:
        """Save disabled plugin IDs to AppSettings."""
        try:
            from AssetsManager.core.settings import AppSettings
            with self._records_lock:
                disabled = [pid for pid, r in self._records.items() if not r.enabled]
            settings = AppSettings.instance()
            settings.set("plugin_disabled_ids", disabled)
            settings.save()
        except Exception:
            pass

    def load_plugin(self, plugin_id: str, host_context: PluginHostContext | None = None) -> PluginLoadResult:
        with self._records_lock:
            record = self._records.get(str(plugin_id or "").strip())
            if record is None:
                return PluginLoadResult(False, plugin_id, PLUGIN_STATE_ERROR,
                                        (PluginDiagnostic("error", "plugin.not_found", f"Plugin '{plugin_id}' not found."),))
            if record.descriptor is None or record.state == PLUGIN_STATE_INVALID:
                return PluginLoadResult(False, record.plugin_id, record.state, tuple(record.diagnostics))
            if not record.enabled or record.state == PLUGIN_STATE_DISABLED:
                return PluginLoadResult(False, record.plugin_id, PLUGIN_STATE_DISABLED, tuple(record.diagnostics))

        try:
            loaded = self.loader.load(record.plugin_id, record.root_dir, record.descriptor.entry)
            with self._records_lock:
                record.module = loaded.module
                record.plugin_instance = loaded.plugin_instance
                record.host_context = host_context
                record.state = PLUGIN_STATE_LOADED
                if host_context is not None and hasattr(record.plugin_instance, "register"):
                    register = getattr(record.plugin_instance, "register")
                    with host_context.plugin_registration(record.plugin_id):
                        register(host_context)
                    record.state = PLUGIN_STATE_ACTIVE
                _log.info("Plugin '%s' loaded (%s)", record.plugin_id, record.state)
            return PluginLoadResult(True, record.plugin_id, record.state, tuple(record.diagnostics))
        except Exception as exc:
            _log.exception("Failed to load plugin '%s'", record.plugin_id)
            if host_context is not None:
                host_context.unregister_plugin(record.plugin_id)
            with self._records_lock:
                record.diagnostics.append(PluginDiagnostic(
                    "error", "plugin.load_failed", f"Load failed: {exc}",
                    plugin_id=record.plugin_id, source=record.manifest_path,
                ))
                record.state = PLUGIN_STATE_ERROR
                record.module = None
                record.plugin_instance = None
                record.host_context = None
            return PluginLoadResult(False, record.plugin_id, PLUGIN_STATE_ERROR, tuple(record.diagnostics))

    def unload_plugin(self, plugin_id: str) -> bool:
        plugin_id = str(plugin_id or "").strip()
        with self._records_lock:
            record = self._records.get(plugin_id)
            if record is None:
                return False
            instance = record.plugin_instance
            ctx: PluginHostContext | None = record.host_context  # type: ignore[assignment]
        unregister_failed = False
        if instance is not None and ctx is not None and hasattr(instance, "unregister"):
            try:
                unregister = getattr(instance, "unregister")
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
        # Always clean up host context contributions, even if plugin has no unregister()
        if ctx is not None:
            try:
                ctx.unregister_plugin(plugin_id)
            except Exception:
                # A faulty subscription cleanup must not retain global plugin state.
                _log.exception("Failed to clean host contributions for plugin '%s'", record.plugin_id)
        # Clean up global mutations (categories, theme tokens)
        self.remove_registered_categories(plugin_id)
        self.remove_registered_theme_tokens(plugin_id)
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
        return not unregister_failed

    def load_all_enabled(self, host_context: PluginHostContext | None = None) -> list[PluginLoadResult]:
        """Load all enabled plugins. Returns results for each."""
        self._host_context = host_context
        results = []
        for record in self._records.values():
            if record.enabled and record.state == PLUGIN_STATE_LOADABLE:
                results.append(self.load_plugin(record.plugin_id, host_context))
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

        # 1. Check plugin instances with match/parse
        for record in self._records.values():
            if not record.enabled or record.plugin_instance is None:
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

        # 2. Check file handlers registered via host context
        if self._host_context is not None:
            for handler in self._host_context.file_handlers():
                try:
                    if handler.match(file_path):
                        parsed = handler.parse(file_path)
                        if isinstance(parsed, dict) and parsed:
                            results[handler.plugin_id] = parsed
                except Exception:
                    _log.warning("File handler '%s' failed to parse '%s'", handler.plugin_id, file_path, exc_info=True)

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

        This updates the global FILTER_CATEGORY_EXTS and CATEGORY_MAP
        so the new categories are available in filter dropdowns and search.
        Tracks which plugin registered each category for cleanup on unload.
        """
        if self._host_context is None:
            return
        from AssetsManager.application.asset_filters import FILTER_CATEGORY_EXTS
        from AssetsManager.core.format_utils import CATEGORY_MAP

        for cat in self._host_context.categories():
            if cat.key in FILTER_CATEGORY_EXTS and cat.key not in self._plugin_categories.get(cat.plugin_id, set()):
                continue
            FILTER_CATEGORY_EXTS[cat.key] = set(cat.extensions)
            for ext in cat.extensions:
                CATEGORY_MAP[ext] = cat.key
            self._plugin_categories.setdefault(cat.plugin_id, set()).add(cat.key)
            _log.info("Registered category '%s' with extensions %s (plugin: %s)", cat.key, cat.extensions, cat.plugin_id)

    def remove_registered_categories(self, plugin_id: str) -> None:
        """Remove global category registrations owned by a plugin."""
        from AssetsManager.application.asset_filters import FILTER_CATEGORY_EXTS
        from AssetsManager.core.format_utils import CATEGORY_MAP

        keys = self._plugin_categories.pop(plugin_id, set())
        for key in keys:
            cats = FILTER_CATEGORY_EXTS.pop(key, None)
            if cats:
                for ext in cats:
                    CATEGORY_MAP.pop(ext, None)
            _log.info("Removed category '%s' registered by plugin '%s'", key, plugin_id)

    def apply_registered_theme_tokens(self) -> None:
        """Apply theme tokens registered via PluginHostContext.register_theme_token().

        This updates the global theme fallbacks so the new tokens are available
        in themes.get() and stylesheet generation.
        Tracks which plugin registered each token for cleanup on unload.
        """
        if self._host_context is None:
            return
        from AssetsManager.core.themes import _EXTENDED_FALLBACKS
        for token in self._host_context.theme_tokens():
            if token.token not in _EXTENDED_FALLBACKS:
                _EXTENDED_FALLBACKS[token.token] = lambda _t, _fb=token.fallback: _fb
            self._plugin_theme_tokens.setdefault(token.plugin_id, set()).add(token.token)
            _log.info("Registered theme token '%s' with fallback '%s' (plugin: %s)", token.token, token.fallback, token.plugin_id)

    def remove_registered_theme_tokens(self, plugin_id: str) -> None:
        """Remove global theme token registrations owned by a plugin."""
        from AssetsManager.core.themes import _EXTENDED_FALLBACKS

        tokens = self._plugin_theme_tokens.pop(plugin_id, set())
        for token_name in tokens:
            _EXTENDED_FALLBACKS.pop(token_name, None)
            _log.info("Removed theme token '%s' registered by plugin '%s'", token_name, plugin_id)
