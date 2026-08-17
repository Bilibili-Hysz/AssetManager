"""Plugin API types: runtime context and contribution base classes.

This module is a leaf: it must not import ``core`` or ``application`` so
plugins and the layer DAG stay one-way.  Host objects are duck-typed.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, ClassVar, Protocol, Sequence

_log = logging.getLogger(__name__)

HOST_API_VERSION = 2


def _as_path(value: object) -> Path | None:
    text = str(value or "").strip()
    return Path(text) if text else None


class PluginContext:
    """Live view of the host at the moment a plugin callback runs.

    Attributes are queried on access (Blender ``bpy.context`` style).  They
    are not the snapshot captured when the plugin registered.
    """

    def __init__(
        self,
        host: Any,
        *,
        extra_paths: tuple[str, ...] = (),
    ) -> None:
        self._host = host
        self._extra_paths = tuple(str(p) for p in extra_paths if str(p).strip())

    @property
    def library_root(self) -> Path | None:
        getter = getattr(self._host, "get_current_root_path", None)
        if not callable(getter):
            return None
        return _as_path(getter())

    @property
    def session(self) -> Any | None:
        """Live library session for plugins holding ``host.services``.

        The session reaches the database connection provider, so the host
        returns None (with a warning logged) when the manifest lacks the
        ``host.services`` permission.
        """
        getter = getattr(self._host, "current_session", None)
        if callable(getter):
            return getter()
        return getattr(self._host, "_runtime_session", lambda: None)()

    @property
    def current_directory(self) -> Path | None:
        getter = getattr(self._host, "get_current_directory", None)
        if not callable(getter):
            return None
        return _as_path(getter())

    @property
    def selected_paths(self) -> tuple[Path, ...]:
        getter = getattr(self._host, "get_selected_paths", None)
        paths: list[Path] = []
        seen: set[str] = set()
        if callable(getter):
            # ``callable()`` narrows the duck-typed getter to a return of
            # ``object``, which is not iterable; the host contract is a sequence.
            raw_paths: Any = getter() or []
            for raw in raw_paths:
                path = _as_path(raw)
                if path is None:
                    continue
                key = str(path)
                if key not in seen:
                    seen.add(key)
                    paths.append(path)
        for raw in self._extra_paths:
            path = _as_path(raw)
            if path is None:
                continue
            key = str(path)
            if key not in seen:
                seen.add(key)
                paths.append(path)
        return tuple(paths)

    @property
    def focused_path(self) -> Path | None:
        getter = getattr(self._host, "get_focused_path", None)
        if not callable(getter):
            return None
        return _as_path(getter())

    @property
    def window(self) -> Any | None:
        """Live main window for plugins holding ``host.services``.

        The window exposes the bootstrap and the session service bundle, so
        it shares the ``host.services`` gate: None (with a warning logged)
        when the permission is missing.
        """
        getter = getattr(self._host, "current_window", None)
        if callable(getter):
            return getter()
        return None

    def services(self) -> Any | None:
        """Restricted host service view for plugins holding ``host.services``.

        Returns None when the manifest lacks the ``host.services``
        permission or no window session is bound.  The returned view never
        exposes authentication material (``sharing_services``), the plugin
        lifecycle service (``plugin_service``) or the raw session.
        """
        getter = getattr(self._host, "current_services", None)
        if callable(getter):
            return getter()
        return None

    def show_notification(self, message: str, level: str = "info") -> None:
        show = getattr(self._host, "show_notification", None)
        if callable(show):
            show(message, level)

    def refresh(self, domains: list[str] | None = None) -> None:
        refresh = getattr(self._host, "request_refresh", None)
        if callable(refresh):
            refresh(domains)

    def log(self, message: str, level: str = "info") -> None:
        numeric = getattr(logging, str(level or "info").upper(), logging.INFO)
        _log.log(numeric, "%s", message)

    def preferences(self, plugin_id: str | None = None) -> Any:
        """Persisted preference bag owned by the calling plugin.

        Requires the ``settings.read`` or ``settings.write`` manifest
        permission; without either the host returns None (with a warning
        logged).  The host resolves the owner from the plugin-identity
        contextvar, so the returned bag always belongs to the plugin whose
        code is running; a mismatched ``plugin_id`` is ignored (with a
        host-side warning) rather than used to reach another plugin's bag.
        Returns None when no plugin context is active or the host has no
        bag accessor.
        """
        getter = getattr(self._host, "preferences", None)
        if not callable(getter):
            return None
        return getter(plugin_id)


class PluginHost(Protocol):
    """Minimal host surface plugins may rely on during ``register()``."""

    def register_class(self, cls: type) -> bool: ...
    def plugin_context(self) -> PluginContext: ...


class CommandOperator:
    """Official command contribution.  ``execute`` always receives a live context."""

    id: ClassVar[str] = ""
    title: ClassVar[str] = ""
    icon: ClassVar[str | None] = None
    menu_paths: ClassVar[tuple[str, ...]] = ()
    shortcut: ClassVar[str | None] = None
    undoable: ClassVar[bool] = False
    params: ClassVar[dict[str, dict[str, Any]]] = {}

    @classmethod
    def poll(cls, ctx: PluginContext) -> bool:
        return True

    @classmethod
    def default_params(cls) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for key, spec in (cls.params or {}).items():
            if isinstance(spec, dict) and "default" in spec:
                values[str(key)] = spec["default"]
        return values

    def execute(self, ctx: PluginContext, params: dict[str, Any] | None = None) -> Any:
        """Run the command.

        Return a dict to use as the undo record, ``False`` to skip undo, or
        ``None`` to record the resolved params when ``undoable`` is true.
        """
        raise NotImplementedError

    def undo(self, ctx: PluginContext, record: dict[str, Any]) -> None:
        """Reverse one previously recorded plugin action."""
        return None


class FileParser:
    """Official file-metadata parser.  Replaces the module-level match/parse pair."""

    id: ClassVar[str] = ""
    output_fields: ClassVar[tuple[tuple[str, str, str], ...]] = ()

    @classmethod
    def match(cls, ctx: PluginContext, file_path: str) -> bool:
        return False

    def parse(self, ctx: PluginContext, file_path: str) -> dict[str, Any]:
        return {}


class ContextMenuItem:
    id: ClassVar[str] = ""
    label: ClassVar[str] = ""
    order: ClassVar[int] = 100
    command_id: ClassVar[str] = ""

    @classmethod
    def poll(cls, ctx: PluginContext, file_path: str) -> bool:
        return True


class MenuContributor:
    id: ClassVar[str] = ""
    menu_path: ClassVar[str] = "plugins"
    command_id: ClassVar[str] = ""
    title: ClassVar[str | None] = None
    order: ClassVar[int] = 100


class PanelContributor:
    id: ClassVar[str] = ""
    title: ClassVar[str] = ""
    area: ClassVar[str] = "right"
    singleton: ClassVar[bool] = True

    def build(self, ctx: PluginContext) -> Any:
        raise NotImplementedError


class EventHook:
    event: ClassVar[Any] = None

    def handle(self, ctx: PluginContext, event: Any) -> None:
        raise NotImplementedError


class CategoryContributor:
    """File-type category that is applied as soon as the class is registered."""

    id: ClassVar[str] = ""
    label: ClassVar[str] = ""
    extensions: ClassVar[Sequence[str]] = ()


class ThemeTokenContributor:
    """Theme token that is applied as soon as the class is registered."""

    token: ClassVar[str] = ""
    fallback: ClassVar[str] = ""


class Preferences:
    """Plugin settings schema.  Values persist under RuntimeData/Shared/plugin_prefs."""

    settings: ClassVar[dict[str, dict[str, Any]]] = {}
