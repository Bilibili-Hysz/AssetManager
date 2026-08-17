"""Plugin host context — runtime environment provided to plugins."""
from __future__ import annotations

import contextvars
import inspect
import logging
import os
import subprocess
import sys
import threading
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from AssetsManager.core.event_contracts import (
    DomainEventBase,
    EventSubscriptionPort,
)
from AssetsManager.core.plugins.descriptor import (
    ALL_PERMISSIONS,
    PERMISSION_FILESYSTEM_READ,
    PERMISSION_HOST_SERVICES,
    PERMISSION_SETTINGS_READ,
    PERMISSION_SETTINGS_WRITE,
)
from AssetsManager.plugin_api.types import (
    CategoryContributor,
    CommandOperator,
    ContextMenuItem,
    EventHook,
    FileParser,
    MenuContributor,
    PanelContributor,
    PluginContext,
    Preferences,
    ThemeTokenContributor,
)

_log = logging.getLogger(__name__)

# The core plugin host must not import the domain event bus directly.  The
# application composition root installs the canonical bus through this seam;
# tests install an equivalent provider in the shared conftest.
_EventBusProvider = Callable[[], Any]
_event_bus_provider: _EventBusProvider | None = None


def install_event_bus_provider(provider: _EventBusProvider) -> None:
    """Install the event bus used by plugin event hooks."""
    global _event_bus_provider
    if not callable(provider):
        raise TypeError("event bus provider must be callable")
    _event_bus_provider = provider


def _event_bus() -> Any:
    if _event_bus_provider is None:
        raise RuntimeError(
            "Plugin event bus provider is not installed; "
            "ApplicationBootstrap installs the domain event bus."
        )
    return _event_bus_provider()


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
    area: str = "right"


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


class _PluginServicesView:
    """Restricted projection of the session service bundle for plugins.

    Only metadata-oriented services are exposed.  Authentication material
    (``sharing_services``: token_secret / auth_service / share_service), the
    plugin lifecycle service (``plugin_service``), the raw ``session`` and
    the lazy LAN projection stay hidden behind AttributeError so even
    hasattr() cannot see them.  Write-capable services are likewise excluded:
    plugins should ask for capabilities through dedicated permissions rather
    than the whole service graph.
    """

    _EXPOSED = frozenset({
        "metadata_service",
        "tag_service",
        "thumbnail_service",
    })

    def __init__(self, services: Any) -> None:
        object.__setattr__(self, "_services", services)

    def __getattr__(self, name: str) -> Any:
        if name not in self._EXPOSED:
            raise AttributeError(f"{type(self).__name__} does not expose '{name}'")
        return getattr(self._services, name)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("plugin services view is read-only")


class PluginHostContext:
    """Runtime context given to plugins for registering commands, menus, tool windows.

    Constructor ``current_root_path`` / ``selected_paths`` remain as fallbacks
    for headless tests.  When a live window is bound, getters read UI state
    at call time instead of the registration-time snapshot.
    """

    def __init__(
        self,
        *,
        current_root_path: str | None = None,
        selected_paths: list[str] | None = None,
        granted_permissions: frozenset[str] | None = None,
    ):
        self._fallback_root_path = str(current_root_path) if current_root_path else None
        self._fallback_selected_paths = [str(p) for p in (selected_paths or []) if str(p).strip()]
        self._current_root_path = self._fallback_root_path
        self._selected_paths = list(self._fallback_selected_paths)
        # Permissions are bookkept per plugin id.  The empty key holds the
        # host-internal grant (constructor argument): calls made with no
        # active plugin context come from the application itself.  Only
        # ``check_permission`` consults that key — the permission-gated
        # registration APIs refuse an empty subject outright (see
        # ``_check_permission_warn``) because a plugin thread that lost its
        # identity ContextVar is indistinguishable from the host here.
        self._permissions_by_plugin: dict[str, frozenset[str]] = {
            "": granted_permissions or frozenset(),
        }
        # Plugin identity is thread-isolated so a hook dispatched on the
        # event bus thread can never observe another thread's subject.
        self._registering_plugin_var: contextvars.ContextVar[str] = contextvars.ContextVar(
            "plugin_registering_id", default=""
        )
        self._executing_plugin_var: contextvars.ContextVar[str] = contextvars.ContextVar(
            "plugin_executing_id", default=""
        )
        # Explicit host identity marker, required by the mutation gates
        # (``grant_permissions``, host-side ``unregister_plugin``).  The
        # marker lives in its own ContextVar, so — exactly like the plugin
        # identity vars — it does not propagate into threads a plugin
        # spawns: an unmarked thread can no longer launder itself into the
        # "host" path that an empty plugin subject used to imply.
        self._host_identity_var: contextvars.ContextVar[bool] = contextvars.ContextVar(
            "plugin_host_identity", default=False
        )
        self._window: Any | None = None
        self._v2_commands: dict[str, type[CommandOperator]] = {}
        self._v2_parsers: dict[str, type[FileParser]] = {}
        self._class_owners: dict[str, str] = {}
        self._apply_categories: Callable[[], None] | None = None
        self._apply_theme_tokens: Callable[[], None] | None = None
        self._preference_classes: dict[str, type[Preferences]] = {}
        self._prompt_params: Callable[[type[CommandOperator], dict[str, Any]], dict[str, Any] | None] | None = None
        # Each undo record carries the owner it was executed under so that
        # undo gating and unload cleanup never depend on the (mutable)
        # ``_class_owners`` registry — which unregister_plugin() rewrites.
        self._undo_stack: list[tuple[type[CommandOperator], dict[str, Any], str]] = []
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
        self._event_subscriptions: list[tuple[str, EventSubscriptionPort, dict[str, bool]]] = []
        self._event_hooks_lock = threading.Lock()
        self._notifications: list[dict[str, str]] = []

    def bind_window(self, window: Any | None) -> None:
        """Attach the live main window so context queries are not snapshots."""
        self._window = window

    def set_apply_hooks(
        self,
        *,
        apply_categories: Callable[[], None] | None = None,
        apply_theme_tokens: Callable[[], None] | None = None,
    ) -> None:
        """Let the manager apply category/theme mutations immediately on register."""
        self._apply_categories = apply_categories
        self._apply_theme_tokens = apply_theme_tokens

    def set_param_prompt(
        self,
        prompt: Callable[[type[CommandOperator], dict[str, Any]], dict[str, Any] | None] | None,
    ) -> None:
        """Optional UI hook: collect operator params.  Return None to cancel."""
        self._prompt_params = prompt

    def grant_permissions(
        self,
        plugin_id: str,
        permissions: frozenset[str] | set[str] | tuple[str, ...],
    ) -> None:
        """Record manifest-declared permissions for *plugin_id* (manager → load).

        Grants are stored per plugin and replace previous grants for that
        plugin; one plugin's manifest never widens another plugin's set.

        Double gate:

        - any call with an active plugin subject is refused, even when the
          subject grants to itself.  Self-granting is exactly the
          escalation this closes — a plugin granting itself
          ``host.services`` would pass every capability check and reach the
          full session and authentication services;
        - a call with no active plugin subject is refused unless the
          caller explicitly entered host identity via ``_host_identity()``.
          An empty subject alone used to mean "the host", but Python
          threads do not inherit the caller's context: a plugin can move
          the call into a thread it spawned (``threading.Thread`` /
          ``ThreadPoolExecutor``), where the identity ContextVar is empty,
          and launder itself into that exemption.  The host marker lives
          in its own ContextVar and does not propagate into spawned
          threads either, so a grant only lands when host management code
          declared itself host on this very thread.

        The manager grants manifest permissions under ``_host_identity()``
        before entering ``plugin_registration`` and before invoking
        ``register()`` — the grant identity is the host's, the
        ``register()`` identity is the plugin's, and the two scopes must
        not be conflated.  Refusal is a warning rather than a raise so a
        customer plugin that trips the gate degrades into a logged message
        instead of a crashed callback.

        This is an in-process honesty boundary, not a sandbox: a plugin
        runs in the same interpreter and can call ``_host_identity`` (or
        set ``_host_identity_var``) directly.
        """
        subject = self._permission_subject()
        target = str(plugin_id or "").strip()
        if subject:
            # Any active subject is refused regardless of target: granting
            # to itself is the exploit, and granting to another plugin
            # would let any plugin bestow capabilities on anything.
            _log.warning(
                "Plugin '%s' attempted to grant permissions to '%s'; refused",
                subject,
                target,
            )
            return
        if not self._host_identity_var.get():
            _log.warning(
                "Refused to grant permissions to '%s': no host identity on this "
                "thread (host management code must enter _host_identity(); an "
                "unmarked thread is not the host, so plugin code cannot launder "
                "grants through threads it spawns)",
                target,
            )
            return
        extra = {str(item).strip() for item in permissions if str(item).strip()}
        self._permissions_by_plugin[target] = frozenset(extra)

    def preferences(self, plugin_id: str | None = None) -> Any:
        """Return the persisted preference bag owned by the *calling* plugin.

        The owner is resolved from the plugin-identity contextvar (via
        ``_permission_subject``), never from the caller-supplied argument:
        preference bags can hold API keys and other credentials, so no
        plugin may reach another plugin's bag by guessing its id.

        Requires the ``settings.read`` or ``settings.write`` manifest
        permission; without either the call is refused with a warning and
        returns None.  This gate is advisory, not a security boundary: a
        plugin runs in the same interpreter and can import
        ``AssetsManager.core.plugins.preferences`` (or maintain its own
        JSON file) directly.  The gate exists so the declared settings
        tokens mean something and honest mistakes are caught.  Note the
        returned bag is mutable — a plugin holding only ``settings.read``
        can still call ``set()`` on it; writes to the plugin's own
        preference file are not separately gated.

        ``plugin_id`` is kept for backwards compatibility (the shipped
        ``download_tracker`` passes its own id).  When it mismatches the
        calling plugin it is ignored with a warning instead of raising: the
        returned bag is always the caller's own, which keeps the
        confidentiality/integrity boundary absolute and degrades a plugin
        bug into a logged warning rather than a crashed plugin callback.
        The mismatch is deliberately not fatal because the failure mode of
        a raise (a customer-site plugin crashing on a typo'd id) is worse
        than the failure mode of a warning (the plugin reads its own bag).

        When no plugin context is active (host code at startup), this
        returns None and never constructs a bag for an empty id; the host
        reaches a specific plugin's bag through :meth:`_preferences_for`.
        """
        subject = self._permission_subject()
        requested = str(plugin_id or "").strip()
        if not subject:
            if requested:
                _log.warning(
                    "preferences('%s') called outside any plugin context; "
                    "host code managing a specific plugin's bag must use _preferences_for()",
                    requested,
                )
            return None
        if requested and requested != subject:
            _log.warning(
                "Plugin '%s' requested preferences for '%s'; "
                "cross-plugin preference access is not allowed, returning its own bag",
                subject,
                requested,
            )
        if not (
            self.check_permission(PERMISSION_SETTINGS_READ)
            or self.check_permission(PERMISSION_SETTINGS_WRITE)
        ):
            _log.warning(
                "Plugin '%s' attempted to access preferences without '%s' or '%s' permission",
                subject,
                PERMISSION_SETTINGS_READ,
                PERMISSION_SETTINGS_WRITE,
            )
            return None
        return self._preferences_for(subject)

    def _preferences_for(self, plugin_id: str) -> Any:
        """Ungated bag lookup for host-internal management code.

        Mirrors ``_current_session_raw``: private by convention, used by
        the host (plugin manager dialogs/services) to reach a specific
        plugin's bag by id.  Safe because host callers pass ids they
        control; a plugin that reaches through ``ctx._host`` to call this
        bypasses the PluginContext facade, which is outside the plugin
        contract in exactly the same way as every other private host
        attribute.
        """
        owner = str(plugin_id or "").strip()
        if not owner:
            return None
        from AssetsManager.core.plugins.preferences import PluginPreferenceBag

        schema = self._preference_classes.get(owner)
        defaults: dict[str, Any] = {}
        if schema is not None:
            for key, spec in (schema.settings or {}).items():
                if isinstance(spec, dict) and "default" in spec:
                    defaults[str(key)] = spec["default"]
        return PluginPreferenceBag(owner, defaults)

    def plugin_context(self, extra_paths: tuple[str, ...] = ()) -> PluginContext:
        return PluginContext(self, extra_paths=extra_paths)

    def current_window(self) -> Any | None:
        """Return the live window when the calling plugin holds ``host.services``.

        The window exposes the bootstrap and the session service bundle, so
        it is the same capability class as ``current_session`` /
        ``current_services`` and shares their gate.
        """
        if not self.check_permission(PERMISSION_HOST_SERVICES):
            _log.warning(
                "Plugin '%s' attempted to access the host window without '%s' permission",
                self._permission_subject() or "<host>", PERMISSION_HOST_SERVICES,
            )
            return None
        return self._window

    def current_session(self) -> Any | None:
        """Return the live library session when the calling plugin holds ``host.services``.

        The session reaches the database connection provider, so it is a
        strict superset of the ``services()`` capability; both share one
        gate so the permission table stays auditable.
        """
        if not self.check_permission(PERMISSION_HOST_SERVICES):
            _log.warning(
                "Plugin '%s' attempted to access the library session without '%s' permission",
                self._permission_subject() or "<host>", PERMISSION_HOST_SERVICES,
            )
            return None
        return self._current_session_raw()

    def _current_session_raw(self) -> Any | None:
        """Ungated session lookup for the host's own navigation queries."""
        window = self._window
        if window is None:
            return None
        return getattr(window, "_library_session", None)

    def current_services(self) -> Any | None:
        """Return the restricted service view when the calling plugin holds ``host.services``.

        The full bundle contains authentication material and the plugin
        lifecycle service, so plugins never receive it raw: without the
        permission this returns None, and with it a
        :class:`_PluginServicesView` hiding the sensitive attributes.
        """
        if not self.check_permission(PERMISSION_HOST_SERVICES):
            _log.warning(
                "Plugin '%s' attempted to access host services without '%s' permission",
                self._permission_subject() or "<host>", PERMISSION_HOST_SERVICES,
            )
            return None
        window = self._window
        session = self._current_session_raw()
        if window is None or session is None:
            return None
        getter = getattr(window, "_scoped_services_for_session", None)
        if callable(getter):
            try:
                services = getter(session)
            except Exception:
                _log.debug("Failed to resolve scoped services for plugin context", exc_info=True)
                return None
            return _PluginServicesView(services) if services is not None else None
        return None

    def get_current_directory(self) -> str | None:
        window = self._window
        if window is None:
            return None
        file_list = getattr(window, "file_list", None)
        current = getattr(file_list, "_current", None)
        return str(current) if current else None

    def get_focused_path(self) -> str | None:
        window = self._window
        if window is None:
            return None
        info = getattr(window, "info", None)
        path = getattr(info, "_current_path", None)
        text = str(path or "").strip()
        return text or None

    def request_refresh(self, domains: list[str] | None = None) -> None:
        window = self._window
        if window is None:
            return
        refresh = getattr(window, "_refresh_all", None)
        if callable(refresh):
            refresh()

    def register_class(self, cls: type) -> bool:
        """Unique v2 registration entry.  Dispatches on contribution base class."""
        if not isinstance(cls, type):
            _log.warning("register_class: expected a class, got %r", cls)
            return False
        # Fall back from the registration context to the active plugin
        # subject so a class registered outside ``plugin_registration``
        # (e.g. from a command callback) is attributed to the caller, not
        # to the host or to a stale id.
        owner = self._registering_plugin_var.get() or self._permission_subject()
        if issubclass(cls, CommandOperator):
            return self._register_operator_class(cls, owner)
        if issubclass(cls, FileParser):
            return self._register_parser_class(cls, owner)
        if issubclass(cls, ContextMenuItem):
            return self._register_context_menu_class(cls, owner)
        if issubclass(cls, MenuContributor):
            return self.register_menu_contribution(
                {
                    "id": cls.id,
                    "menu_path": cls.menu_path,
                    "command_id": cls.command_id,
                    "title": cls.title,
                    "order": cls.order,
                }
            )
        if issubclass(cls, PanelContributor):
            instance = cls()

            def factory(ctx=self, panel=instance, owner=owner):
                with self._host_identity_scope(self._executing_plugin_var, owner):
                    return panel.build(ctx.plugin_context())

            return self.register_tool_window(
                {
                    "id": cls.id,
                    "title": cls.title,
                    "singleton": cls.singleton,
                    "area": cls.area,
                },
                factory,
                plugin_id=owner,
            )
        if issubclass(cls, EventHook):
            instance = cls()
            if cls.event is None:
                return False
            self.hook(cls.event, lambda event, hook=instance: hook.handle(self.plugin_context(), event), owner)
            return True
        if issubclass(cls, CategoryContributor):
            self.register_category(owner, cls.id, cls.label, set(cls.extensions))
            return any(cat.key == cls.id and cat.plugin_id == owner for cat in self._categories)
        if issubclass(cls, ThemeTokenContributor):
            self.register_theme_token(owner, cls.token, cls.fallback)
            return any(token.token == cls.token and token.plugin_id == owner for token in self._theme_tokens)
        if issubclass(cls, Preferences):
            if not owner:
                return False
            self._preference_classes[owner] = cls
            self._class_owners[f"prefs:{owner}"] = owner
            return True
        _log.warning("register_class: unsupported contribution type %s", getattr(cls, "__name__", cls))
        return False

    def _register_operator_class(self, cls: type[CommandOperator], owner: str) -> bool:
        command_id = str(cls.id or "").strip()
        title = str(cls.title or command_id).strip()
        if not command_id or not title:
            return False
        if self._resolve_contribution_owner(owner, "register_command") is None:
            return False
        self._v2_commands[command_id] = cls
        self._class_owners[command_id] = owner
        handler = self._operator_handler(cls)
        registered = self.register_command(
            {
                "id": command_id,
                "title": title,
                "shortcut": cls.shortcut,
                "icon": cls.icon,
            },
            handler,
            plugin_id=owner,
        )
        for menu_path in cls.menu_paths:
            self.register_menu_contribution(
                {
                    "id": f"{command_id}:{menu_path}",
                    "menu_path": menu_path,
                    "command_id": command_id,
                    "title": title,
                }
            )
        return registered

    def _register_parser_class(self, cls: type[FileParser], owner: str) -> bool:
        parser_id = str(cls.id or owner or "").strip()
        if not parser_id:
            return False
        if self._resolve_contribution_owner(owner or parser_id, "register_file_handler") is None:
            return False
        self._v2_parsers[parser_id] = cls
        self._class_owners[parser_id] = owner

        def match(file_path: str, parser=cls, owner=owner) -> bool:
            with self._host_identity_scope(self._executing_plugin_var, owner):
                return bool(parser.match(self.plugin_context(), file_path))

        def parse(file_path: str, parser=cls, owner=owner) -> dict:
            with self._host_identity_scope(self._executing_plugin_var, owner):
                parsed = parser().parse(self.plugin_context(), file_path)
                return parsed if isinstance(parsed, dict) else {}

        self.register_file_handler(owner or parser_id, match, parse)
        return True

    def _register_context_menu_class(self, cls: type[ContextMenuItem], owner: str) -> bool:
        item_id = str(cls.id or "").strip()
        label = str(cls.label or "").strip()
        command_id = str(cls.command_id or "").strip()
        if not item_id or not label or not command_id:
            return False

        def when(file_path: str, item=cls, owner=owner) -> bool:
            with self._host_identity_scope(self._executing_plugin_var, owner):
                return bool(item.poll(self.plugin_context(extra_paths=(file_path,)), file_path))

        self.register_context_menu_item(
            owner,
            item_id,
            label,
            command_id,
            when=when,
            order=int(cls.order),
        )
        return True

    def _operator_handler(self, cls: type[CommandOperator]) -> Callable[..., object]:
        def handler(*_args: object, **_kwargs: object) -> None:
            extra = tuple(str(arg) for arg in _args if str(arg).strip())
            self.execute_command(cls.id, extra_paths=extra)

        return handler

    def execute_command(
        self,
        command_id: str,
        *,
        extra_paths: tuple[str, ...] = (),
        params: dict[str, object] | None = None,
    ) -> bool:
        """Run a registered command through the single v2 execute path.

        Identity-gated: a plugin subject may only execute its own
        commands.  Running another plugin's command would execute it under
        that plugin's identity and permission grants, so it is refused
        with a warning (refusal rather than a raise keeps a misbehaving
        plugin from crashing the callback that called it).  The host, with
        no active plugin subject, may execute any command; the UI and
        ``_operator_handler`` dispatch all run as the host.
        """
        cid = str(command_id or "").strip()
        if not cid:
            return False
        subject = self._permission_subject()
        ctx = self.plugin_context(extra_paths=extra_paths)
        operator_cls = self._v2_commands.get(cid)
        if operator_cls is not None:
            owner = self._class_owners.get(cid, "")
            if subject and subject != owner:
                _log.warning(
                    "Plugin '%s' attempted to execute command '%s' owned by '%s'; refused",
                    subject,
                    cid,
                    owner or "<host>",
                )
                return False
            with self._host_identity_scope(self._executing_plugin_var, owner):
                return self._execute_operator(operator_cls, ctx, params, owner)
        for cmd in self.commands():
            if cmd.id != cid:
                continue
            if subject and subject != cmd.plugin_id:
                _log.warning(
                    "Plugin '%s' attempted to execute command '%s' owned by '%s'; refused",
                    subject,
                    cid,
                    cmd.plugin_id or "<host>",
                )
                return False
            handler = cmd.handler
            if not callable(handler):
                return False
            with self._host_identity_scope(self._executing_plugin_var, cmd.plugin_id):
                self._invoke_legacy_handler(handler, extra_paths)
            return True
        return False

    def _execute_operator(
        self,
        operator_cls: type[CommandOperator],
        ctx: PluginContext,
        params: dict[str, object] | None,
        owner: str,
    ) -> bool:
        if not operator_cls.poll(ctx):
            return False
        resolved = dict(operator_cls.default_params())
        if params:
            resolved.update(params)
        elif operator_cls.params and self._prompt_params is not None:
            prompted = self._prompt_params(operator_cls, resolved)
            if prompted is None:
                return False
            resolved.update(prompted)
        operator = operator_cls()
        result = operator.execute(ctx, resolved)
        if operator_cls.undoable and result is not False:
            record = result if isinstance(result, dict) else dict(resolved)
            self._undo_stack.append((operator_cls, record, owner))
        return True

    def _invoke_legacy_handler(
        self,
        handler: Callable[..., object],
        extra_paths: tuple[str, ...],
    ) -> None:
        """Invoke a legacy handler exactly once, matching its declared arity.

        Legacy handlers keep their original arity: context-menu calls pass
        the clicked path, menu/toolbar calls pass nothing.
        ``inspect.signature`` decides between the forms before the call, so
        a TypeError raised inside the handler propagates instead of being
        mistaken for an arity mismatch and re-invoking the handler (which
        double-executed its side effects).
        """
        accepts_args = True
        try:
            accepts_args = any(
                param.kind in (
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.VAR_POSITIONAL,
                )
                for param in inspect.signature(handler).parameters.values()
            )
        except (TypeError, ValueError):
            pass  # Uninspectable callable: never retry, let a TypeError escape.
        if accepts_args and extra_paths:
            handler(*extra_paths)
        else:
            handler()

    def undo_last_command(self) -> bool:
        """Undo the most recent undoable v2 operator, if any.

        Identity-gated like ``execute_command``: a plugin subject may only
        undo its own operators.  Popping another plugin's undo record and
        running its ``undo`` under that plugin's identity is refused with
        a warning and the stack is left untouched.  The host may undo any
        record.  The owner is read from the record itself (captured when
        the command executed), not from the ``_class_owners`` registry,
        which unloads rewrite.
        """
        if not self._undo_stack:
            return False
        operator_cls, record, owner = self._undo_stack[-1]
        subject = self._permission_subject()
        if subject and subject != owner:
            _log.warning(
                "Plugin '%s' attempted to undo a command owned by '%s'; refused",
                subject,
                owner or "<host>",
            )
            return False
        self._undo_stack.pop()
        with self._host_identity_scope(self._executing_plugin_var, owner):
            operator_cls().undo(self.plugin_context(), record)
        return True

    def _resolve_contribution_owner(self, plugin_id: str, action: str) -> str | None:
        """Resolve an explicit ``plugin_id`` argument against the active subject.

        Returns the normalized owner id to attribute the contribution to,
        or ``None`` when the call must be refused.  Under an active plugin
        subject (registration or execution context):

        - an empty plugin_id attributes the contribution to the subject;
        - an equal plugin_id is accepted;
        - a different plugin_id is refused with a warning, so a plugin can
          never quietly file its contribution under another plugin's id
          (which would later be stripped or executed under that identity).

        With no active subject (host management code and headless tests)
        the explicit id passes through unchanged, preserving the host's
        ability to manage contributions on behalf of any plugin.  For the
        permission-gated APIs (category / theme token / file handler /
        search provider) the downstream ``_check_permission_warn`` still
        refuses an empty subject, so host management code must declare
        the target identity via ``_host_identity_scope`` (and grant the
        permission) before the contribution is actually recorded.
        """
        requested = str(plugin_id or "").strip()
        subject = self._permission_subject()
        if not subject:
            return requested
        if requested and requested != subject:
            _log.warning(
                "Plugin '%s' attempted to attribute %s to '%s'; refused",
                subject,
                action,
                requested,
            )
            return None
        return subject

    def register_command(self, descriptor: dict[str, object], handler: Callable[..., object] | None = None, plugin_id: str = "") -> bool:
        owner = self._resolve_contribution_owner(plugin_id, "register_command")
        if owner is None:
            return False
        cid = str(descriptor.get("id") or "").strip()
        title = str(descriptor.get("title") or cid).strip()
        if not cid or not title:
            return False
        shortcut = _opt_str(descriptor.get("shortcut"))
        if shortcut:
            existing = next(
                (cmd for cmd in self._commands.values() if cmd.shortcut == shortcut),
                None,
            )
            if existing:
                _log.warning(
                    "Shortcut conflict: command '%s' (plugin '%s') declares shortcut '%s', "
                    "already registered by command '%s' (plugin '%s'). The new registration "
                    "will overwrite the shortcut binding.",
                    cid,
                    owner,
                    shortcut,
                    existing.id,
                    existing.plugin_id,
                )
        self._commands[cid] = CommandContribution(
            id=cid, title=title,
            plugin_id=owner,
            description=_opt_str(descriptor.get("description")),
            shortcut=shortcut,
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
        owner = self._resolve_contribution_owner(plugin_id, "register_tool_window")
        if owner is None:
            return False
        cid = str(descriptor.get("id") or "").strip()
        title = str(descriptor.get("title") or cid).strip()
        if not cid or not callable(factory):
            return False
        area = str(descriptor.get("area") or "right").strip().lower() or "right"
        self._tool_windows[cid] = ToolWindowContribution(
            id=cid, title=title,
            singleton=bool(descriptor.get("singleton", True)),
            factory=factory,
            plugin_id=owner,
            area=area,
        )
        return True

    def show_notification(self, message: str, level: str = "info") -> None:
        text = str(message or "").strip()
        if text:
            owner = self._permission_subject()
            self._notifications.append({"level": level, "message": text, "plugin_id": owner})

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
        owner = self._resolve_contribution_owner(plugin_id, "register_file_handler")
        if owner is None:
            return
        if not callable(match) or not callable(parse):
            _log.warning("register_file_handler: match and parse must be callables")
            return
        if not self._check_permission_warn("filesystem.read", "register_file_handler", owner):
            return
        self._file_handlers.append(
            FileHandlerContribution(plugin_id=owner, match=match, parse=parse)
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
        owner = self._resolve_contribution_owner(plugin_id, "register_context_menu_item")
        if owner is None:
            return
        if not item_id or not label or not command_id:
            _log.warning("register_context_menu_item: item_id, label, command_id required")
            return
        self._context_menu_items.append(
            ContextMenuContribution(
                id=item_id,
                plugin_id=owner,
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
        owner = self._resolve_contribution_owner(plugin_id, "register_category")
        if owner is None:
            return
        if not key or not label or not extensions:
            _log.warning("register_category: key, label, extensions required")
            return
        if not self._check_permission_warn("settings.write", "register_category", owner):
            return
        self._categories.append(
            CategoryContribution(
                plugin_id=owner,
                key=key,
                label=label,
                extensions=frozenset(extensions),
            )
        )
        apply = self._apply_categories
        if callable(apply):
            apply()

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
        owner = self._resolve_contribution_owner(plugin_id, "register_column")
        if owner is None:
            return
        if not key or not label:
            _log.warning("register_column: key and label required")
            return
        self._columns.append(
            ColumnContribution(
                plugin_id=owner,
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
        owner = self._resolve_contribution_owner(plugin_id, "register_search_provider")
        if owner is None:
            return
        if not provider_id or not label or not callable(search):
            _log.warning("register_search_provider: provider_id, label, search required")
            return
        if not self._check_permission_warn("filesystem.read", "register_search_provider", owner):
            return
        self._search_providers.append(
            SearchProviderContribution(
                plugin_id=owner,
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
        owner = self._resolve_contribution_owner(plugin_id, "register_theme_token")
        if owner is None:
            return
        if not token or not fallback:
            _log.warning("register_theme_token: token and fallback required")
            return
        if not self._check_permission_warn("settings.write", "register_theme_token", owner):
            return
        self._theme_tokens.append(
            ThemeTokenContribution(plugin_id=owner, token=token, fallback=fallback)
        )
        apply = self._apply_theme_tokens
        if callable(apply):
            apply()

    def theme_tokens(self) -> list[ThemeTokenContribution]:
        return list(self._theme_tokens)

    def _permission_subject(self) -> str:
        """Plugin id the current thread's code is running on behalf of, or "".

        Resolution order: innermost execution context (command / hook /
        callback dispatch), then the registration context.  Falls back to
        "" for the host and for any thread that never entered a plugin
        identity — including threads a plugin spawned itself, since
        ContextVars do not propagate into new threads.  An empty subject
        therefore no longer means "host" by itself: the permission-gated
        APIs treat it as untrusted and refuse it, and the mutation gates
        (``grant_permissions``, host-side ``unregister_plugin``) require
        the separate explicit host marker entered via ``_host_identity()``.
        Host management code that must act on a plugin's behalf declares
        an identity explicitly via ``_host_identity_scope``.
        """
        executing = str(self._executing_plugin_var.get() or "").strip()
        if executing:
            return executing
        return str(self._registering_plugin_var.get() or "").strip()

    def check_permission(self, permission: str) -> bool:
        """Whether the current plugin subject holds *permission*."""
        if permission not in ALL_PERMISSIONS:
            _log.warning("Unknown permission: %s", permission)
            return False
        subject = self._permission_subject()
        return permission in self._permissions_by_plugin.get(subject, frozenset())

    def _check_permission_warn(self, permission: str, action: str, plugin_id: str = "") -> bool:
        """Enforce *permission* for the active plugin context; no identity, no pass.

        An empty subject is refused: it used to be read as "the host" and
        exempted, but a plugin can move a call into a thread it spawned
        (``threading.Thread`` / ``ThreadPoolExecutor``) where the
        registration/execution ContextVar is empty, laundering itself into
        that exemption.  A call with no plugin identity is now always
        refused with a warning, whether it really comes from host code, a
        headless caller, or a plugin thread that lost its identity.  Host
        management code that must register on a plugin's behalf declares
        that identity explicitly — grant the permission and enter
        ``_host_identity_scope`` — exactly as the manager does before
        invoking ``register()``.  There is no production host caller left
        that relies on the empty-subject pass.

        This remains an honesty boundary, not a security sandbox: a
        plugin runs in the same interpreter and can still reach
        ``_host_identity_scope`` or ``_executing_plugin_var`` directly.
        """
        subject = self._permission_subject()
        if not subject:
            _log.warning(
                "Refused %s requiring %s: no plugin identity on this thread "
                "(host management code must enter an explicit identity scope, "
                "and plugin code must not shift gated calls into unmarked threads)",
                action,
                permission,
            )
            return False
        if self.check_permission(permission):
            return True
        _log.warning(
            "Plugin %s attempted %s without permission %s",
            plugin_id or subject, action, permission,
        )
        return False

    def granted_permissions(self, plugin_id: str | None = None) -> frozenset[str]:
        """The permission set of *plugin_id*, gated by caller identity.

        A plugin subject may only read its own set: passing another
        plugin's id logs a warning and returns the caller's own set
        instead, and an empty id always means "my own".  Cross-plugin
        enumeration is an information leak with no capability gain, so it
        degrades to a warning rather than raising.  With no active plugin
        subject the id is honored as-is, which is what host code (the
        plugin manager dialog reads any plugin's grants) relies on; reads
        grant no capabilities, so — unlike the write paths — they are not
        gated on the ``_host_identity`` marker, and an unmarked thread
        reading another plugin's set only ever learns its permission
        tokens, never capabilities.
        """
        subject = self._permission_subject()
        requested = str(plugin_id or "").strip()
        if subject:
            if requested and requested != subject:
                _log.warning(
                    "Plugin '%s' attempted to read permissions of '%s'; "
                    "cross-plugin permission enumeration is not allowed, "
                    "returning its own set",
                    subject,
                    requested,
                )
            return self._permissions_by_plugin.get(subject, frozenset())
        return self._permissions_by_plugin.get(requested, frozenset())

    @contextmanager
    def _host_identity_scope(self, var: contextvars.ContextVar[str], plugin_id: str):
        """Set an identity ContextVar unconditionally (host dispatch only).

        The host legitimately enters another plugin's identity while a
        plugin subject is already active: a plugin callback can publish an
        event or open a menu, and the host then dispatches plugin B's hook
        or ``when`` predicate from inside plugin A's frame.  The public
        wrappers refuse that transition to stop impersonation, so host-side
        dispatch goes through this private path instead.  Reaching it
        requires touching a private attribute, which a hostile in-process
        plugin can do anyway (see the class docstring): this separates host
        dispatch from plugin calls, it does not contain a plugin.
        """
        token = var.set(str(plugin_id or "").strip())
        try:
            yield
        finally:
            var.reset(token)

    @contextmanager
    def _host_identity(self):
        """Enter explicit host identity (host management paths only).

        The host marker is a dedicated ContextVar, so — like the plugin
        identity vars — it does not propagate into threads a plugin
        spawns.  ``grant_permissions`` and host-side ``unregister_plugin``
        require it: an empty plugin subject alone no longer counts as the
        host, because a plugin thread that lost its identity ContextVar
        resolves to an empty subject too, which is exactly the laundering
        path the marker closes.

        Honesty boundary, not a sandbox: a plugin running in the same
        interpreter can reach this private scope (or set
        ``_host_identity_var``) directly.
        """
        token = self._host_identity_var.set(True)
        try:
            yield
        finally:
            self._host_identity_var.reset(token)

    def _guarded_identity_scope(
        self, var: contextvars.ContextVar[str], plugin_id: str, api: str
    ):
        """Public-entry identity scope that refuses impersonation.

        A plugin holding the raw host context could otherwise claim any
        identity: ``plugin_execution("victim")`` to borrow another plugin's
        grants, or ``plugin_execution("")`` to launder itself into the
        host's unrestricted path.  When a plugin subject is already active,
        only re-asserting that same id is allowed; anything else logs a
        warning and leaves the identity untouched while still running the
        wrapped block (refusing the identity change, not the call).  The
        host, with no active plugin subject, is unrestricted.
        """
        requested = str(plugin_id or "").strip()
        active = self._permission_subject()
        if active and requested != active:
            _log.warning(
                "Plugin '%s' attempted to assume identity '%s' via %s; "
                "refused, identity unchanged",
                active,
                requested or "<host>",
                api,
            )
            return nullcontext()
        return self._host_identity_scope(var, requested)

    def plugin_registration(self, plugin_id: str):
        """Assign ownership to contributions registered during plugin startup.

        Refuses to switch identity when another plugin subject is already
        active; see :meth:`_guarded_identity_scope`.
        """
        return self._guarded_identity_scope(
            self._registering_plugin_var, plugin_id, "plugin_registration"
        )

    def plugin_execution(self, plugin_id: str):
        """Mark the calling thread as executing code owned by *plugin_id*.

        Permission checks inside the wrapped callback resolve against this
        plugin's grants instead of the host's.  The identity lives in a
        ContextVar, so callbacks dispatched on other threads (e.g. the event
        bus thread) can never observe or clobber another thread's subject.

        Refuses to switch identity when another plugin subject is already
        active; see :meth:`_guarded_identity_scope`.
        """
        return self._guarded_identity_scope(
            self._executing_plugin_var, plugin_id, "plugin_execution"
        )

    def hook(self, event_type: type[DomainEventBase], handler: Callable, plugin_id: str = "") -> None:
        """Register a handler for a lifecycle event.

        The handler runs synchronously in the EventBus publishing thread. It
        must not mutate Qt UI directly; unload closes the host-owned subscription.
        """
        if not isinstance(event_type, type) or not issubclass(event_type, DomainEventBase):
            raise TypeError("hook event_type must be a DomainEvent subclass")
        if not callable(handler):
            _log.warning("hook: handler must be callable")
            return
        owner = self._resolve_contribution_owner(plugin_id, "hook")
        if owner is None:
            return
        active = {"value": True}

        def dispatch(event: DomainEventBase) -> None:
            if active["value"]:
                with self._host_identity_scope(self._executing_plugin_var, owner):
                    handler(event)

        with self._event_hooks_lock:
            self._event_hooks.setdefault(event_type, []).append((handler, owner))
            subscription = _event_bus().subscribe(event_type, dispatch)
            self._event_subscriptions.append((owner, subscription, active))

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
        with self._event_hooks_lock:
            return {event_type: list(hooks) for event_type, hooks in self._event_hooks.items()}

    def open_path(self, path: str) -> bool:
        """Open *path* in its OS-default application.

        Advisory gate on ``filesystem.read``: a plugin can call
        ``os.startfile`` / ``subprocess`` itself in the same interpreter,
        so the gate documents intent and catches honest mistakes rather
        than containing filesystem access.  Calls with no plugin subject
        (the host or an unmarked thread) are refused; the host must enter
        an explicit identity via ``_host_identity_scope``.
        """
        p = str(path or "").strip()
        if not p:
            return False
        p_obj = Path(p)
        if not p_obj.exists():
            return False
        if not self._check_permission_warn(PERMISSION_FILESYSTEM_READ, "open_path"):
            return False
        if sys.platform == 'win32':
            os.startfile(str(p_obj))
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', str(p_obj)])
        else:
            subprocess.Popen(['xdg-open', str(p_obj)])
        return True

    def get_current_root_path(self) -> str | None:
        # Ungated: library_root is basic navigation context every plugin
        # gets, not a capability escalation.
        session = self._current_session_raw()
        if session is not None:
            context = getattr(session, "context", None)
            root = getattr(context, "root", None)
            if root:
                return str(root)
        return self._fallback_root_path

    def get_selected_paths(self) -> list[str]:
        window = self._window
        file_list = getattr(window, "file_list", None) if window is not None else None
        getter = getattr(file_list, "_selected_paths", None)
        if callable(getter):
            try:
                # ``callable()`` narrows the duck-typed getter to a return of
                # ``object``, which is not iterable; the panel returns a sequence.
                raw_paths: Any = getter() or []
                live = [str(path) for path in raw_paths if str(path).strip()]
            except Exception:
                _log.debug("Failed to read live file-list selection", exc_info=True)
            else:
                return live
        return list(self._fallback_selected_paths)

    def command_available(self, command_id: str, extra_paths: tuple[str, ...] = ()) -> bool:
        """Whether a v2 operator currently polls true.  Legacy commands stay enabled."""
        cid = str(command_id or "").strip()
        operator_cls = self._v2_commands.get(cid)
        if operator_cls is None:
            return any(cmd.id == cid and cmd.enabled for cmd in self._commands.values())
        with self._host_identity_scope(self._executing_plugin_var, self._class_owners.get(cid, "")):
            return bool(operator_cls.poll(self.plugin_context(extra_paths=extra_paths)))

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
        """Notifications shown so far, each with ``level``, ``message`` and
        the ``plugin_id`` of the subject that raised it ("" for the host)."""
        return list(self._notifications)

    def unregister_plugin(self, plugin_id: str) -> None:
        """Remove all contributions registered by the given plugin.

        Called during plugin unload to prevent stale menu items, commands,
        and other contributions from persisting after the plugin is disabled.

        Gated by plugin identity: a plugin running on its own behalf may
        only unregister itself, so one plugin cannot strip another plugin's
        contributions.  A call with no active plugin subject requires the
        explicit host identity marker (``_host_identity()``): the empty
        subject used to pass as "the host", but a plugin thread spawned
        with ``threading.Thread`` / ``ThreadPoolExecutor`` loses its
        identity ContextVar and would launder into that exemption, letting
        any plugin strip any other plugin's contributions and grants.  The
        manager (unload, load-failure cleanup) enters ``_host_identity()``
        before unregistering; the plugin manager dialog goes through the
        manager.  As everywhere, this is an in-process honesty boundary:
        a plugin can reach ``_host_identity`` directly.

        The argument is whitespace-normalized once and the normalized id
        is used for every registry comparison, so a padded id (e.g. from
        the plugin manager dialog) cannot leave residues behind.  Undo
        records and notifications owned by the unloaded plugin are removed
        with the rest of its contributions: keeping them would let a
        record's ``undo()`` run after its owner was unloaded, or leave
        orphan notifications attributed to a plugin that no longer exists.
        """
        target = str(plugin_id or "").strip()
        subject = self._permission_subject()
        if subject:
            if subject != target:
                _log.warning(
                    "Plugin '%s' attempted to unregister contributions owned by '%s'; refused",
                    subject,
                    target,
                )
                return
        elif not self._host_identity_var.get():
            _log.warning(
                "Refused to unregister '%s': no host identity on this thread "
                "(host management code must enter _host_identity(); an unmarked "
                "thread is not the host)",
                target,
            )
            return
        self._permissions_by_plugin.pop(target, None)
        self._undo_stack = [
            (cls, record, owner)
            for cls, record, owner in self._undo_stack
            if owner != target
        ]
        self._notifications = [
            notification
            for notification in self._notifications
            if notification.get("plugin_id") != target
        ]
        self._commands = {
            cid: cmd for cid, cmd in self._commands.items()
            if cmd.plugin_id != target
        }
        self._menu_contributions = {
            cid: mc for cid, mc in self._menu_contributions.items()
            if mc.command_id in self._commands
        }
        self._tool_windows = {
            cid: tw for cid, tw in self._tool_windows.items()
            if tw.plugin_id != target
        }
        self._file_handlers = [h for h in self._file_handlers if h.plugin_id != target]
        self._context_menu_items = [i for i in self._context_menu_items if i.plugin_id != target]
        self._categories = [c for c in self._categories if c.plugin_id != target]
        self._columns = [c for c in self._columns if c.plugin_id != target]
        self._search_providers = [p for p in self._search_providers if p.plugin_id != target]
        self._theme_tokens = [t for t in self._theme_tokens if t.plugin_id != target]
        owned_ids = {cid for cid, owner in self._class_owners.items() if owner == target}
        self._v2_commands = {cid: cls for cid, cls in self._v2_commands.items() if cid not in owned_ids}
        self._v2_parsers = {cid: cls for cid, cls in self._v2_parsers.items() if cid not in owned_ids}
        self._preference_classes = {
            pid: cls for pid, cls in self._preference_classes.items() if pid != target
        }
        self._class_owners = {cid: owner for cid, owner in self._class_owners.items() if owner != target}
        with self._event_hooks_lock:
            subscriptions = [
                (subscription, active)
                for pid, subscription, active in self._event_subscriptions
                if pid == target
            ]
            self._event_subscriptions = [
                (pid, subscription, active)
                for pid, subscription, active in self._event_subscriptions
                if pid != target
            ]
            self._event_hooks = {
                etype: [(h, pid) for h, pid in handlers if pid != target]
                for etype, handlers in self._event_hooks.items()
            }
            for _subscription, active in subscriptions:
                active["value"] = False
        for subscription, _active in subscriptions:
            subscription.close()
        _log.info("Unregistered contributions for plugin '%s'", target)


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
