"""Plugin application service."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from AssetsManager.core.plugins import (
    PluginDescriptor,
    PluginHostContext,
    PluginLoadResult,
    PluginManagerService,
)


class PluginService:
    """Application-layer facade for the plugin subsystem.

    Wraps ``PluginManagerService`` and provides a stable API for
    desktop UI and LAN integration.
    """

    def __init__(self, manager: PluginManagerService | None = None):
        self._manager = manager or PluginManagerService.get()

    def discover(self, search_paths: list[Path] | None = None) -> list[PluginDescriptor]:
        """Discover plugins on disk and return their descriptors."""
        return self._manager.discover_plugins(search_paths)

    def list_plugins(self) -> list[PluginDescriptor]:
        """Return descriptors of all known plugins."""
        return self._manager.list_plugins()

    def enable(self, plugin_id: str) -> bool:
        """Enable a plugin by ID."""
        return self._manager.enable_plugin(plugin_id)

    def disable(self, plugin_id: str) -> bool:
        """Disable a plugin by ID (unloads first if active)."""
        return self._manager.disable_plugin(plugin_id)

    def load(self, plugin_id: str, host_context: PluginHostContext | None = None) -> PluginLoadResult:
        """Load a single plugin and optionally call its register()."""
        return self._manager.load_plugin(plugin_id, host_context)

    def unload(self, plugin_id: str) -> bool:
        """Unload a single plugin and call its unregister()."""
        return self._manager.unload_plugin(plugin_id)

    def load_all_enabled(self, host_context: PluginHostContext | None = None) -> list[PluginLoadResult]:
        """Load all enabled plugins."""
        return self._manager.load_all_enabled(host_context)

    @property
    def host_context(self) -> PluginHostContext | None:
        """Return the host context used during plugin loading."""
        return self._manager._host_context

    def get_commands(self) -> list[Any]:
        """Return all command contributions from the host context."""
        ctx = self._manager._host_context
        if ctx is None:
            return []
        return ctx.commands()

    def get_menu_contributions(self, menu_path: str | None = None) -> list[Any]:
        """Return menu contributions, optionally filtered by menu path."""
        ctx = self._manager._host_context
        if ctx is None:
            return []
        return ctx.menu_contributions(menu_path)
