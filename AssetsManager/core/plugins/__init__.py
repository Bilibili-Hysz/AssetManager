"""Plugin system — discover, load, and manage external plugins.

Plugins are directories containing a plugin.json manifest and a Python
entry module.  The manifest declares the plugin's ID, name, version,
entry point, and capabilities.

Example plugin.json:
{
  "id": "my-tool",
  "name": "My Tool",
  "version": "1.0",
  "entry": "main:Plugin",
  "kind": "tool_window"
}

The entry object must expose register(host_context) and optionally
unregister(host_context).  New plugins should import from
``AssetsManager.plugin_api`` and call ``host.register_class(...)``.
"""
from AssetsManager.core.plugins.descriptor import (
    PluginDescriptor, PluginRecord, PluginDiagnostic, PluginLoadResult,
    load_manifest, parse_plugin_descriptor, build_plugin_record,
    PLUGIN_STATE_ACTIVE, PLUGIN_STATE_DISABLED, PLUGIN_STATE_ERROR,
    PLUGIN_STATE_INVALID, PLUGIN_STATE_LOADED, PLUGIN_STATE_LOADABLE,
)
from AssetsManager.core.plugins.host_context import (
    PluginHostContext, CommandContribution, MenuContribution, ToolWindowContribution,
)
from AssetsManager.core.plugins.loader import PluginLoader
from AssetsManager.core.plugins.manager import PluginManagerService

__all__ = [
    "PluginDescriptor", "PluginRecord", "PluginDiagnostic", "PluginLoadResult",
    "PluginHostContext", "CommandContribution", "MenuContribution", "ToolWindowContribution",
    "PluginLoader", "PluginManagerService",
    "load_manifest", "parse_plugin_descriptor", "build_plugin_record",
    "PLUGIN_STATE_ACTIVE", "PLUGIN_STATE_DISABLED", "PLUGIN_STATE_ERROR",
    "PLUGIN_STATE_INVALID", "PLUGIN_STATE_LOADED", "PLUGIN_STATE_LOADABLE",
]
