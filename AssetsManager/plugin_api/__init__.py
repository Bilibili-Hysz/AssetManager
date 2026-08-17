"""Sanctioned plugin API surface (v2).

Plugins should import from this package only.  The host still accepts the
legacy match/parse and dict-style register_* methods through a compatibility
layer so existing addons keep working without edits.
"""
from __future__ import annotations

from AssetsManager.plugin_api.types import (
    HOST_API_VERSION,
    CategoryContributor,
    CommandOperator,
    ContextMenuItem,
    EventHook,
    FileParser,
    MenuContributor,
    PanelContributor,
    PluginContext,
    PluginHost,
    Preferences,
    ThemeTokenContributor,
)

__all__ = [
    "HOST_API_VERSION",
    "CategoryContributor",
    "CommandOperator",
    "ContextMenuItem",
    "EventHook",
    "FileParser",
    "MenuContributor",
    "PanelContributor",
    "PluginContext",
    "PluginHost",
    "Preferences",
    "ThemeTokenContributor",
]
