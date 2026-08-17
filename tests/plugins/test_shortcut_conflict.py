"""Test shortcut conflict detection in register_command."""
import logging
import pytest
from AssetsManager.core.plugins.host_context import PluginHostContext


@pytest.fixture
def host():
    ctx = PluginHostContext()
    with ctx._host_identity():
        ctx.grant_permissions("plugin_a", frozenset())
        ctx.grant_permissions("plugin_b", frozenset())
        yield ctx


def test_shortcut_conflict_warns(host, caplog):
    """Registering two commands with the same shortcut logs a warning."""
    with host._host_identity_scope(host._registering_plugin_var, "plugin_a"):
        registered_a = host.register_command(
            {"id": "cmd_a", "title": "Command A", "shortcut": "Ctrl+K"},
            lambda: None,
            plugin_id="plugin_a",
        )
    assert registered_a
    assert host._commands["cmd_a"].shortcut == "Ctrl+K"

    with caplog.at_level(logging.WARNING):
        with host._host_identity_scope(host._registering_plugin_var, "plugin_b"):
            registered_b = host.register_command(
                {"id": "cmd_b", "title": "Command B", "shortcut": "Ctrl+K"},
                lambda: None,
                plugin_id="plugin_b",
            )
    assert registered_b
    assert host._commands["cmd_b"].shortcut == "Ctrl+K"
    assert any("Shortcut conflict" in rec.message for rec in caplog.records)
    assert any("cmd_a" in rec.message and "plugin_a" in rec.message for rec in caplog.records)


def test_no_shortcut_no_warning(host, caplog):
    """Commands without shortcuts do not trigger conflict warnings."""
    with host._host_identity_scope(host._registering_plugin_var, "plugin_a"):
        host.register_command(
            {"id": "cmd_a", "title": "Command A"},
            lambda: None,
            plugin_id="plugin_a",
        )
    with caplog.at_level(logging.WARNING):
        with host._host_identity_scope(host._registering_plugin_var, "plugin_b"):
            host.register_command(
                {"id": "cmd_b", "title": "Command B"},
                lambda: None,
                plugin_id="plugin_b",
            )
    assert not any("Shortcut conflict" in rec.message for rec in caplog.records)


def test_different_shortcuts_no_warning(host, caplog):
    """Different shortcuts do not trigger warnings."""
    with host._host_identity_scope(host._registering_plugin_var, "plugin_a"):
        host.register_command(
            {"id": "cmd_a", "title": "Command A", "shortcut": "Ctrl+K"},
            lambda: None,
            plugin_id="plugin_a",
        )
    with caplog.at_level(logging.WARNING):
        with host._host_identity_scope(host._registering_plugin_var, "plugin_b"):
            host.register_command(
                {"id": "cmd_b", "title": "Command B", "shortcut": "Ctrl+L"},
                lambda: None,
                plugin_id="plugin_b",
            )
    assert not any("Shortcut conflict" in rec.message for rec in caplog.records)


def test_same_plugin_shortcut_conflict_still_warns(host, caplog):
    """Even commands from the same plugin warn on shortcut collision."""
    with host._host_identity_scope(host._registering_plugin_var, "plugin_a"):
        host.register_command(
            {"id": "cmd_a1", "title": "Command A1", "shortcut": "Ctrl+K"},
            lambda: None,
            plugin_id="plugin_a",
        )
    with caplog.at_level(logging.WARNING):
        with host._host_identity_scope(host._registering_plugin_var, "plugin_a"):
            host.register_command(
                {"id": "cmd_a2", "title": "Command A2", "shortcut": "Ctrl+K"},
                lambda: None,
                plugin_id="plugin_a",
            )
    assert any("Shortcut conflict" in rec.message for rec in caplog.records)
