"""Unified explicit-owner validation on the legacy register_* surface.

Under an active plugin subject (registration or execution context) a
contribution call may only attribute itself to the calling plugin: an
explicit id naming another plugin is refused with a warning, an empty
(including whitespace-only) id attributes to the subject, and the
plugin's own id is accepted.  With no active subject — host management
code and headless tests — an explicit id passes through unchanged, so
the host keeps managing contributions on behalf of any plugin.

For the permission-gated APIs (file handler / search provider /
category / theme token) the host row now declares the target identity
explicitly via ``_host_identity_scope`` after granting the permission:
an empty subject no longer passes ``_check_permission_warn`` (it is
indistinguishable from a plugin thread that lost its identity).  The
grant itself is host-side and requires the explicit host identity
marker (``_host_identity()``), mirroring the manager's load path.
"""
from __future__ import annotations

import logging

from AssetsManager.core.plugins.host_context import PluginHostContext
from AssetsManager.domain.events import FileSystemChanged
from AssetsManager.plugin_api import CommandOperator


def test_register_command_owner_matrix(caplog):
    host = PluginHostContext()

    # Cross-plugin attribution is refused and registers nothing.
    with caplog.at_level(logging.WARNING):
        with host.plugin_registration("alpha"):
            assert host.register_command(
                {"id": "cross.cmd", "title": "Cross"}, lambda: None, "beta"
            ) is False
    assert "attempted to attribute register_command to 'beta'" in caplog.text
    assert host.commands() == []

    # Empty plugin_id attributes to the subject.
    with host.plugin_registration("alpha"):
        assert host.register_command({"id": "auto.cmd", "title": "Auto"}, lambda: None) is True
    assert {cmd.id: cmd.plugin_id for cmd in host.commands()} == {"auto.cmd": "alpha"}

    # Whitespace-only plugin_id also attributes to the subject.
    with host.plugin_registration("alpha"):
        assert host.register_command({"id": "blank.cmd", "title": "Blank"}, lambda: None, "   ") is True
    assert host.commands()[-1].plugin_id == "alpha"

    # The plugin's own id is accepted.
    with host.plugin_registration("alpha"):
        assert host.register_command({"id": "own.cmd", "title": "Own"}, lambda: None, "alpha") is True

    # An execution context is a subject too: cross-attribution refused.
    with caplog.at_level(logging.WARNING):
        with host.plugin_execution("alpha"):
            assert host.register_command(
                {"id": "exec.cmd", "title": "Exec"}, lambda: None, "beta"
            ) is False
    assert "attempted to attribute register_command to 'beta'" in caplog.text

    # The host (no active subject) may attribute to any plugin.
    assert host.register_command({"id": "host.cmd", "title": "Host"}, lambda: None, "beta") is True
    assert {cmd.id for cmd in host.commands() if cmd.plugin_id == "beta"} == {"host.cmd"}


def test_register_tool_window_owner_matrix(caplog):
    host = PluginHostContext()

    def factory():
        return "widget"

    with caplog.at_level(logging.WARNING):
        with host.plugin_registration("alpha"):
            assert host.register_tool_window({"id": "cross.tw", "title": "TW"}, factory, "beta") is False
    assert "attempted to attribute register_tool_window to 'beta'" in caplog.text
    assert host.tool_windows() == []

    with host.plugin_registration("alpha"):
        assert host.register_tool_window({"id": "auto.tw", "title": "TW"}, factory) is True
    assert host.tool_windows()[0].plugin_id == "alpha"

    with host.plugin_registration("alpha"):
        assert host.register_tool_window({"id": "own.tw", "title": "TW"}, factory, "alpha") is True

    with caplog.at_level(logging.WARNING):
        with host.plugin_execution("alpha"):
            assert host.register_tool_window({"id": "exec.tw", "title": "TW"}, factory, "beta") is False

    assert host.register_tool_window({"id": "host.tw", "title": "TW"}, factory, "beta") is True
    assert host.tool_windows()[-1].plugin_id == "beta"


def test_register_file_handler_owner_matrix(caplog):
    host = PluginHostContext()
    with host._host_identity():
        host.grant_permissions("alpha", {"filesystem.read"})

    match = lambda path: False  # noqa: E731
    parse = lambda path: {}  # noqa: E731

    with caplog.at_level(logging.WARNING):
        with host.plugin_registration("alpha"):
            host.register_file_handler("beta", match, parse)
    assert "attempted to attribute register_file_handler to 'beta'" in caplog.text
    assert host.file_handlers() == []

    with host.plugin_registration("alpha"):
        host.register_file_handler("", match, parse)
    assert host.file_handlers()[0].plugin_id == "alpha"

    with host.plugin_registration("alpha"):
        host.register_file_handler("alpha", match, parse)

    with caplog.at_level(logging.WARNING):
        with host.plugin_execution("alpha"):
            host.register_file_handler("beta", match, parse)
    assert "attempted to attribute register_file_handler to 'beta'" in caplog.text
    assert {h.plugin_id for h in host.file_handlers()} == {"alpha"}

    # The host may attribute to any plugin, but the permission-gated
    # registration requires an explicit identity plus the grant.
    with host._host_identity():
        host.grant_permissions("beta", {"filesystem.read"})
    with host._host_identity_scope(host._registering_plugin_var, "beta"):
        host.register_file_handler("beta", match, parse)
    assert host.file_handlers()[-1].plugin_id == "beta"


def test_register_search_provider_owner_matrix(caplog):
    host = PluginHostContext()
    with host._host_identity():
        host.grant_permissions("alpha", {"filesystem.read"})

    search = lambda query, root: []  # noqa: E731

    with caplog.at_level(logging.WARNING):
        with host.plugin_registration("alpha"):
            host.register_search_provider("beta", "sp.cross", "SP", search)
    assert "attempted to attribute register_search_provider to 'beta'" in caplog.text
    assert host.search_providers() == []

    with host.plugin_registration("alpha"):
        host.register_search_provider("", "sp.auto", "SP", search)
    assert host.search_providers()[0].plugin_id == "alpha"

    with host.plugin_registration("alpha"):
        host.register_search_provider("alpha", "sp.own", "SP", search)

    with caplog.at_level(logging.WARNING):
        with host.plugin_execution("alpha"):
            host.register_search_provider("beta", "sp.exec", "SP", search)
    assert {p.plugin_id for p in host.search_providers()} == {"alpha"}

    with host._host_identity():
        host.grant_permissions("beta", {"filesystem.read"})
    with host._host_identity_scope(host._registering_plugin_var, "beta"):
        host.register_search_provider("beta", "sp.host", "SP", search)
    assert host.search_providers()[-1].plugin_id == "beta"


def test_register_context_menu_item_owner_matrix(caplog):
    host = PluginHostContext()

    with caplog.at_level(logging.WARNING):
        with host.plugin_registration("alpha"):
            host.register_context_menu_item("beta", "item.cross", "Label", "cmd")
    assert "attempted to attribute register_context_menu_item to 'beta'" in caplog.text
    assert host.context_menu_items() == []

    with host.plugin_registration("alpha"):
        host.register_context_menu_item("", "item.auto", "Label", "cmd")
    assert host.context_menu_items()[0].plugin_id == "alpha"

    with host.plugin_registration("alpha"):
        host.register_context_menu_item("alpha", "item.own", "Label", "cmd")

    with caplog.at_level(logging.WARNING):
        with host.plugin_execution("alpha"):
            host.register_context_menu_item("beta", "item.exec", "Label", "cmd")
    assert {item.plugin_id for item in host.context_menu_items()} == {"alpha"}

    host.register_context_menu_item("beta", "item.host", "Label", "cmd")
    assert host.context_menu_items()[-1].plugin_id == "beta"


def test_register_category_owner_matrix(caplog):
    host = PluginHostContext()
    with host._host_identity():
        host.grant_permissions("alpha", {"settings.write"})

    with caplog.at_level(logging.WARNING):
        with host.plugin_registration("alpha"):
            host.register_category("beta", "cat.cross", "Cat", {".x"})
    assert "attempted to attribute register_category to 'beta'" in caplog.text
    assert host.categories() == []

    with host.plugin_registration("alpha"):
        host.register_category("", "cat.auto", "Cat", {".x"})
    assert host.categories()[0].plugin_id == "alpha"

    with host.plugin_registration("alpha"):
        host.register_category("alpha", "cat.own", "Cat", {".x"})

    with caplog.at_level(logging.WARNING):
        with host.plugin_execution("alpha"):
            host.register_category("beta", "cat.exec", "Cat", {".x"})
    assert {cat.plugin_id for cat in host.categories()} == {"alpha"}

    with host._host_identity():
        host.grant_permissions("beta", {"settings.write"})
    with host._host_identity_scope(host._registering_plugin_var, "beta"):
        host.register_category("beta", "cat.host", "Cat", {".x"})
    assert host.categories()[-1].plugin_id == "beta"


def test_register_column_owner_matrix(caplog):
    host = PluginHostContext()

    with caplog.at_level(logging.WARNING):
        with host.plugin_registration("alpha"):
            host.register_column("beta", "col.cross", "Col")
    assert "attempted to attribute register_column to 'beta'" in caplog.text
    assert host.columns() == []

    with host.plugin_registration("alpha"):
        host.register_column("", "col.auto", "Col")
    assert host.columns()[0].plugin_id == "alpha"

    with host.plugin_registration("alpha"):
        host.register_column("alpha", "col.own", "Col")

    with caplog.at_level(logging.WARNING):
        with host.plugin_execution("alpha"):
            host.register_column("beta", "col.exec", "Col")
    assert {col.plugin_id for col in host.columns()} == {"alpha"}

    host.register_column("beta", "col.host", "Col")
    assert host.columns()[-1].plugin_id == "beta"


def test_register_theme_token_owner_matrix(caplog):
    host = PluginHostContext()
    with host._host_identity():
        host.grant_permissions("alpha", {"settings.write"})

    with caplog.at_level(logging.WARNING):
        with host.plugin_registration("alpha"):
            host.register_theme_token("beta", "tok.cross", "#fff")
    assert "attempted to attribute register_theme_token to 'beta'" in caplog.text
    assert host.theme_tokens() == []

    with host.plugin_registration("alpha"):
        host.register_theme_token("", "tok.auto", "#fff")
    assert host.theme_tokens()[0].plugin_id == "alpha"

    with host.plugin_registration("alpha"):
        host.register_theme_token("alpha", "tok.own", "#fff")

    with caplog.at_level(logging.WARNING):
        with host.plugin_execution("alpha"):
            host.register_theme_token("beta", "tok.exec", "#fff")
    assert {token.plugin_id for token in host.theme_tokens()} == {"alpha"}

    with host._host_identity():
        host.grant_permissions("beta", {"settings.write"})
    with host._host_identity_scope(host._registering_plugin_var, "beta"):
        host.register_theme_token("beta", "tok.host", "#fff")
    assert host.theme_tokens()[-1].plugin_id == "beta"


def test_hook_owner_matrix(caplog):
    host = PluginHostContext()

    def handler(event):
        pass

    with caplog.at_level(logging.WARNING):
        with host.plugin_registration("alpha"):
            host.hook(FileSystemChanged, handler, "beta")
    assert "attempted to attribute hook to 'beta'" in caplog.text
    assert host.event_hooks() == {}

    with host.plugin_registration("alpha"):
        host.hook(FileSystemChanged, handler)
    hooks = host.event_hooks()
    assert hooks[FileSystemChanged] == [(handler, "alpha")]

    with caplog.at_level(logging.WARNING):
        with host.plugin_execution("alpha"):
            host.hook(FileSystemChanged, handler, "beta")
    assert "attempted to attribute hook to 'beta'" in caplog.text
    assert len(host.event_hooks()[FileSystemChanged]) == 1

    host.hook(FileSystemChanged, handler, "beta")
    _, pid = host.event_hooks()[FileSystemChanged][-1]
    assert pid == "beta"
    with host._host_identity():
        host.unregister_plugin("beta")
        host.unregister_plugin("alpha")


def test_register_class_during_execution_attributed_to_subject():
    """A class registered from a command callback is owned by the caller."""

    class SideEffect(CommandOperator):
        id = "alpha.side"
        title = "SideEffect"

        def execute(self, ctx, params=None):
            return None

    host = PluginHostContext()
    with host.plugin_execution("alpha"):
        assert host.register_class(SideEffect) is True
    assert host._class_owners["alpha.side"] == "alpha"
    commands = {cmd.id: cmd for cmd in host.commands()}
    assert commands["alpha.side"].plugin_id == "alpha"
    # The command resolves to alpha, so only alpha (or the host) may run it.
    with host.plugin_execution("alpha"):
        assert host.execute_command("alpha.side") is True
    with host.plugin_execution("beta"):
        assert host.execute_command("alpha.side") is False
