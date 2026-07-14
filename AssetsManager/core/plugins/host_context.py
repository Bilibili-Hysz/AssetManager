"""Plugin host context — runtime environment provided to plugins."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from AssetsManager.core.plugins.descriptor import ALL_PERMISSIONS

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommandContribution:
    id: str
    title: str
    plugin_id: str = ""
    description: str | None = None
    shortcut: str | None = None
    icon: str | None = None
    enabled: bool = True
    handler: Callable[..., object] | None = None


@dataclass(frozen=True)
class MenuContribution:
    id: str
    menu_path: str
    command_id: str
    title: str | None = None
    order: int = 100
    enabled: bool = True


@dataclass(frozen=True)
class ToolWindowContribution:
    id: str
    title: str
    singleton: bool
    factory: Callable[..., object]
    plugin_id: str = ""


@dataclass(frozen=True)
class FileHandlerContribution:
    """A plugin-provided file handler with match/parse logic."""
    plugin_id: str
    match: Callable[[str], bool]
    parse: Callable[[str], dict]


@dataclass(frozen=True)
class ContextMenuContribution:
    """A plugin-provided context menu item."""
    id: str
    plugin_id: str
    label: str
    command_id: str
    when: Callable[[str], bool] | None = None
    order: int = 100


@dataclass(frozen=True)
class CategoryContribution:
    """A plugin-provided file type category."""
    plugin_id: str
    key: str
    label: str
    extensions: frozenset[str]


@dataclass(frozen=True)
class ColumnContribution:
    """A plugin-provided custom column for the detail view."""
    plugin_id: str
    key: str
    label: str
    width: int = 120
    order: int = 100


@dataclass(frozen=True)
class SearchProviderContribution:
    """A plugin-provided search provider."""
    plugin_id: str
    id: str
    label: str
    search: Callable[[str, str], list[dict]]


@dataclass(frozen=True)
class ThemeTokenContribution:
    """A plugin-provided theme color token."""
    plugin_id: str
    token: str
    fallback: str


class PluginHostContext:
    """Runtime context given to plugins for registering commands, menus, tool windows."""

    def __init__(
        self,
        *,
        current_root_path: str | None = None,
        selected_paths: list[str] | None = None,
        granted_permissions: frozenset[str] | None = None,
    ):
        self._current_root_path = str(current_root_path) if current_root_path else None
        self._selected_paths = [str(p) for p in (selected_paths or []) if str(p).strip()]
        self._granted_permissions = granted_permissions or frozenset()
        self._commands: dict[str, CommandContribution] = {}
        self._menu_contributions: dict[str, MenuContribution] = {}
        self._tool_windows: dict[str, ToolWindowContribution] = {}
        self._file_handlers: list[FileHandlerContribution] = []
        self._context_menu_items: list[ContextMenuContribution] = []
        self._categories: list[CategoryContribution] = []
        self._columns: list[ColumnContribution] = []
        self._search_providers: list[SearchProviderContribution] = []
        self._theme_tokens: list[ThemeTokenContribution] = []
        self._event_hooks: dict[type, list[tuple[Callable, str]]] = {}
        self._notifications: list[dict[str, str]] = []

    def register_command(self, descriptor: dict[str, object], handler: Callable[..., object] | None = None, plugin_id: str = "") -> bool:
        cid = str(descriptor.get("id") or "").strip()
        title = str(descriptor.get("title") or cid).strip()
        if not cid or not title:
            return False
        self._commands[cid] = CommandContribution(
            id=cid, title=title,
            plugin_id=plugin_id,
            description=_opt_str(descriptor.get("description")),
            shortcut=_opt_str(descriptor.get("shortcut")),
            icon=_opt_str(descriptor.get("icon")),
            enabled=bool(descriptor.get("enabled", True)),
            handler=handler,
        )
        return True

    def register_menu_contribution(self, descriptor: dict[str, object]) -> bool:
        cid = str(descriptor.get("id") or "").strip()
        menu_path = str(descriptor.get("menu_path") or "").strip()
        command_id = str(descriptor.get("command_id") or "").strip()
        if not cid or menu_path not in {"tools", "plugins", "context"} or not command_id:
            return False
        self._menu_contributions[cid] = MenuContribution(
            id=cid, menu_path=menu_path, command_id=command_id,
            title=_opt_str(descriptor.get("title")),
            order=_to_int(descriptor.get("order")),
            enabled=bool(descriptor.get("enabled", True)),
        )
        return True

    def register_tool_window(self, descriptor: dict[str, object], factory: Callable[..., object], plugin_id: str = "") -> bool:
        cid = str(descriptor.get("id") or "").strip()
        title = str(descriptor.get("title") or cid).strip()
        if not cid or not callable(factory):
            return False
        self._tool_windows[cid] = ToolWindowContribution(
            id=cid, title=title,
            singleton=bool(descriptor.get("singleton", True)),
            factory=factory,
            plugin_id=plugin_id,
        )
        return True

    def show_notification(self, message: str, level: str = "info") -> None:
        text = str(message or "").strip()
        if text:
            self._notifications.append({"level": level, "message": text})

    def register_file_handler(
        self,
        plugin_id: str,
        match: Callable[[str], bool],
        parse: Callable[[str], dict],
    ) -> None:
        """Register a file handler with match/parse logic.

        This is the Blender-style registration for file metadata parsers.
        The host will call match(file_path) for each selected file,
        and parse(file_path) when match returns True.
        """
        if not callable(match) or not callable(parse):
            _log.warning("register_file_handler: match and parse must be callables")
            return
        self._check_permission_warn("filesystem.read", "register_file_handler", plugin_id)
        self._file_handlers.append(
            FileHandlerContribution(plugin_id=plugin_id, match=match, parse=parse)
        )

    def register_context_menu_item(
        self,
        plugin_id: str,
        item_id: str,
        label: str,
        command_id: str,
        *,
        when: Callable[[str], bool] | None = None,
        order: int = 100,
    ) -> None:
        """Register a custom context menu item for file right-click menus.

        Args:
            plugin_id: The plugin registering this item.
            item_id: Unique identifier for this menu item.
            label: Display text for the menu item.
            command_id: The command to execute when clicked.
            when: Optional predicate receiving file_path; item shown only if True.
            order: Sort order (lower = earlier).
        """
        if not item_id or not label or not command_id:
            _log.warning("register_context_menu_item: item_id, label, command_id required")
            return
        self._context_menu_items.append(
            ContextMenuContribution(
                id=item_id,
                plugin_id=plugin_id,
                label=label,
                command_id=command_id,
                when=when,
                order=order,
            )
        )

    def register_category(
        self,
        plugin_id: str,
        key: str,
        label: str,
        extensions: set[str],
    ) -> None:
        """Register a new file type category.

        The category will be available in filter dropdowns, LAN API,
        and search. Extensions should include the leading dot.

        Args:
            plugin_id: The plugin registering this category.
            key: Canonical key (e.g. "cad", "audio").
            label: Display label (e.g. "CAD Files", "Audio").
            extensions: Set of file extensions (e.g. {".dwg", ".dxf"}).
        """
        if not key or not label or not extensions:
            _log.warning("register_category: key, label, extensions required")
            return
        self._check_permission_warn("settings.write", "register_category", plugin_id)
        self._categories.append(
            CategoryContribution(
                plugin_id=plugin_id,
                key=key,
                label=label,
                extensions=frozenset(extensions),
            )
        )

    def register_column(
        self,
        plugin_id: str,
        key: str,
        label: str,
        *,
        width: int = 120,
        order: int = 100,
    ) -> None:
        """Register a custom column for the detail view.

        Args:
            plugin_id: The plugin registering this column.
            key: Unique column key.
            label: Display header text.
            width: Column width in pixels (default 120).
            order: Sort order (lower = earlier, default 100).
        """
        if not key or not label:
            _log.warning("register_column: key and label required")
            return
        self._columns.append(
            ColumnContribution(
                plugin_id=plugin_id,
                key=key,
                label=label,
                width=width,
                order=order,
            )
        )

    def columns(self) -> list[ColumnContribution]:
        items = list(self._columns)
        items.sort(key=lambda c: c.order)
        return items

    def register_search_provider(
        self,
        plugin_id: str,
        provider_id: str,
        label: str,
        search: Callable[[str, str], list[dict]],
    ) -> None:
        """Register a custom search provider.

        The search callable receives (query, library_root) and returns
        a list of result dicts with at least {name, path} keys.
        """
        if not provider_id or not label or not callable(search):
            _log.warning("register_search_provider: provider_id, label, search required")
            return
        self._check_permission_warn("filesystem.read", "register_search_provider", plugin_id)
        self._search_providers.append(
            SearchProviderContribution(
                plugin_id=plugin_id,
                id=provider_id,
                label=label,
                search=search,
            )
        )

    def search_providers(self) -> list[SearchProviderContribution]:
        return list(self._search_providers)

    def register_theme_token(self, plugin_id: str, token: str, fallback: str) -> None:
        """Register a custom theme color token.

        The token will be available in themes.get() with the given fallback
        color if not defined in the current theme JSON.
        """
        if not token or not fallback:
            _log.warning("register_theme_token: token and fallback required")
            return
        self._check_permission_warn("settings.write", "register_theme_token", plugin_id)
        self._theme_tokens.append(
            ThemeTokenContribution(plugin_id=plugin_id, token=token, fallback=fallback)
        )

    def theme_tokens(self) -> list[ThemeTokenContribution]:
        return list(self._theme_tokens)

    def check_permission(self, permission: str) -> bool:
        """Check if a permission is granted to this plugin context."""
        if permission not in ALL_PERMISSIONS:
            _log.warning("Unknown permission: %s", permission)
            return False
        return permission in self._granted_permissions

    def _check_permission_warn(self, permission: str, action: str, plugin_id: str = "") -> bool:
        """Check permission and log a warning if not granted. Returns True if granted."""
        if self.check_permission(permission):
            return True
        _log.warning(
            "Plugin %s attempted %s without permission %s",
            plugin_id or "unknown", action, permission,
        )
        return False

    def granted_permissions(self) -> frozenset[str]:
        return self._granted_permissions

    def hook(self, event_type: type, handler: Callable, plugin_id: str = "") -> None:
        """Register a handler for a lifecycle event.

        The handler will be called when the event is published via EventBus.
        Supported event types are defined in domain.events:
        - LibraryOpened, FileRenamed, FileDeleted, FileCreated, FileCopied
        - TagsChanged, NotesChanged, UrlsChanged
        """
        if not callable(handler):
            _log.warning("hook: handler must be callable")
            return
        self._event_hooks.setdefault(event_type, []).append((handler, plugin_id))

    def file_handlers(self) -> list[FileHandlerContribution]:
        return list(self._file_handlers)

    def context_menu_items(self, file_path: str | None = None) -> list[ContextMenuContribution]:
        """Return registered context menu items, optionally filtered by file path."""
        items = list(self._context_menu_items)
        if file_path is not None:
            items = [item for item in items if item.when is None or item.when(file_path)]
        items.sort(key=lambda item: item.order)
        return items

    def categories(self) -> list[CategoryContribution]:
        return list(self._categories)

    def event_hooks(self) -> dict[type, list[tuple[Callable, str]]]:
        return dict(self._event_hooks)

    def open_path(self, path: str) -> bool:
        p = str(path or "").strip()
        if not p:
            return False
        p_obj = Path(p)
        if not p_obj.exists():
            return False
        if sys.platform == 'win32':
            os.startfile(str(p_obj))
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', str(p_obj)])
        else:
            subprocess.Popen(['xdg-open', str(p_obj)])
        return True

    def get_current_root_path(self) -> str | None:
        return self._current_root_path

    def get_selected_paths(self) -> list[str]:
        return list(self._selected_paths)

    def commands(self) -> list[CommandContribution]:
        return list(self._commands.values())

    def menu_contributions(self, menu_path: str | None = None) -> list[MenuContribution]:
        items = list(self._menu_contributions.values())
        if menu_path is None:
            return items
        return [i for i in items if i.menu_path == menu_path]

    def tool_windows(self) -> list[ToolWindowContribution]:
        return list(self._tool_windows.values())

    def notifications(self) -> list[dict[str, str]]:
        return list(self._notifications)

    def unregister_plugin(self, plugin_id: str) -> None:
        """Remove all contributions registered by the given plugin.

        Called during plugin unload to prevent stale menu items, commands,
        and other contributions from persisting after the plugin is disabled.
        """
        self._commands = {
            cid: cmd for cid, cmd in self._commands.items()
            if cmd.plugin_id != plugin_id
        }
        self._menu_contributions = {
            cid: mc for cid, mc in self._menu_contributions.items()
            if mc.command_id in self._commands
        }
        self._tool_windows = {
            cid: tw for cid, tw in self._tool_windows.items()
            if tw.plugin_id != plugin_id
        }
        self._file_handlers = [h for h in self._file_handlers if h.plugin_id != plugin_id]
        self._context_menu_items = [i for i in self._context_menu_items if i.plugin_id != plugin_id]
        self._categories = [c for c in self._categories if c.plugin_id != plugin_id]
        self._columns = [c for c in self._columns if c.plugin_id != plugin_id]
        self._search_providers = [p for p in self._search_providers if p.plugin_id != plugin_id]
        self._theme_tokens = [t for t in self._theme_tokens if t.plugin_id != plugin_id]
        self._event_hooks = {
            etype: [(h, pid) for h, pid in handlers if pid != plugin_id]
            for etype, handlers in self._event_hooks.items()
        }
        _log.info("Unregistered contributions for plugin '%s'", plugin_id)


def _opt_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    t = value.strip()
    return t or None


def _to_int(value: object, default: int = 100) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
