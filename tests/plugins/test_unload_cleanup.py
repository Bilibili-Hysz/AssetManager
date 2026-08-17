"""Unload cleanup: undo records, ownership maps, and whitespace-padded ids.

Unloading a plugin must remove everything it owns from the host context:
its undo records (so its ``undo()`` can never run after unload), its
commands/parsers/classes, its notifications, and its permission grants —
all keyed by the whitespace-normalized plugin id, so a padded id from the
plugin manager dialog cannot leave residues behind.
"""
from __future__ import annotations

import logging

from AssetsManager.core.plugins.host_context import PluginHostContext
from AssetsManager.plugin_api import CommandOperator, FileParser, Preferences


class _AlphaOp(CommandOperator):
    id = "alpha.op"
    title = "AlphaOp"
    undoable = True

    def execute(self, ctx, params=None):
        return {"who": "alpha"}

    def undo(self, ctx, record):
        raise AssertionError("alpha's undo must never run after unload")


class _BetaOp(CommandOperator):
    id = "beta.op"
    title = "BetaOp"
    undoable = True

    def execute(self, ctx, params=None):
        return {"who": "beta"}

    def undo(self, ctx, record):
        undone_owners.append(record["who"])


undone_owners: list[str] = []


def test_unload_removes_own_undo_records_and_keeps_others():
    undone_owners.clear()
    host = PluginHostContext()
    with host.plugin_registration("alpha"):
        assert host.register_class(_AlphaOp) is True
    with host.plugin_registration("beta"):
        assert host.register_class(_BetaOp) is True
    assert host.execute_command("alpha.op") is True
    assert host.execute_command("beta.op") is True

    # Host-side unload: enter explicit host identity.
    with host._host_identity():
        host.unregister_plugin("alpha")

    # Only beta's record remains: the top (beta) undoes normally, then the
    # stack is empty because alpha's record was cleaned with the unload.
    assert host.undo_last_command() is True
    assert undone_owners == ["beta"]
    assert host.undo_last_command() is False
    assert undone_owners == ["beta"]


def test_unload_keeps_beta_undo_executable_under_beta_identity():
    undone_owners.clear()
    subjects: list[str] = []

    class BetaOpSpy(_BetaOp):
        def undo(self, ctx, record):
            subjects.append("beta")
            super().undo(ctx, record)

    host = PluginHostContext()
    with host.plugin_registration("alpha"):
        assert host.register_class(_AlphaOp) is True
    with host.plugin_registration("beta"):
        assert host.register_class(BetaOpSpy) is True
    assert host.execute_command("alpha.op") is True
    assert host.execute_command("beta.op") is True

    # Host-side unload: enter explicit host identity.
    with host._host_identity():
        host.unregister_plugin("alpha")

    # A plugin subject can still undo its own record after another plugin
    # unloaded, and the undo runs under beta's identity.
    with host.plugin_execution("beta"):
        assert host.undo_last_command() is True
    assert undone_owners == ["beta"]
    assert subjects == ["beta"]

    # Alpha's record was removed, so the remaining stack is empty.
    assert host.undo_last_command() is False


def test_unload_cleans_command_parser_and_class_mappings():
    class ParserA(FileParser):
        id = "alpha.parser"

        @classmethod
        def match(cls, ctx, file_path):
            return False

        def parse(self, ctx, file_path):
            return {}

    class PrefsA(Preferences):
        settings = {"keep": {"type": "int", "default": 1}}

    class ParserB(FileParser):
        id = "beta.parser"

        @classmethod
        def match(cls, ctx, file_path):
            return False

        def parse(self, ctx, file_path):
            return {}

    host = PluginHostContext()
    with host._host_identity():
        host.grant_permissions("alpha", {"filesystem.read", "settings.read", "settings.write"})
        host.grant_permissions("beta", {"filesystem.read"})
    with host.plugin_registration("alpha"):
        assert host.register_class(_AlphaOp) is True
        assert host.register_class(ParserA) is True
        assert host.register_class(PrefsA) is True
        host.register_command({"id": "alpha.legacy", "title": "LegacyA"}, lambda: None)
    with host.plugin_registration("beta"):
        assert host.register_class(_BetaOp) is True
        assert host.register_class(ParserB) is True
        host.register_command({"id": "beta.legacy", "title": "LegacyB"}, lambda: None)

    # Host-side unload: enter explicit host identity.
    with host._host_identity():
        host.unregister_plugin("alpha")

    # v2 command/parser registries keep beta, drop alpha.
    assert host._v2_commands.keys() == {"beta.op"}
    assert host._v2_parsers.keys() == {"beta.parser"}
    # Ownership and preference maps keep no alpha entry.
    assert "alpha" not in set(host._class_owners.values())
    assert set(host._class_owners.values()) == {"beta"}
    assert host._preference_classes == {}
    # Legacy command contributions follow the same rule.
    assert {cmd.id for cmd in host.commands()} == {"beta.op", "beta.legacy"}
    # File handlers: only beta's parser remains.
    assert {h.plugin_id for h in host.file_handlers()} == {"beta"}


def test_unregister_with_whitespace_padded_id_cleans_everything():
    host = PluginHostContext()
    with host._host_identity():
        host.grant_permissions("pad.pid", {"filesystem.read", "settings.write"})
    with host.plugin_registration("pad.pid"):
        host.register_command({"id": "pad.cmd", "title": "Pad"}, lambda: None)
        # A padded self-id is normalized and accepted as the subject's own.
        host.register_command({"id": "pad.cmd2", "title": "Pad2"}, lambda: None, " pad.pid ")
        host.register_tool_window({"id": "pad.tw", "title": "TW"}, lambda: None)
        host.register_file_handler("pad.pid", lambda p: False, lambda p: {})
        host.register_category("pad.pid", "pad.cat", "Cat", {".x"})
        host.register_column("pad.pid", "pad.col", "Col")
        host.register_search_provider("pad.pid", "pad.sp", "SP", lambda q, r: [])
        host.register_theme_token("pad.pid", "pad.tok", "#fff")
        host.register_context_menu_item("pad.pid", "pad.item", "Item", "pad.cmd")
        host.show_notification("pad note")
    host.show_notification("host note")

    # A plugin may unregister itself with a padded id.
    with host.plugin_execution("pad.pid"):
        host.unregister_plugin(" pad.pid ")

    assert host.commands() == []
    assert host.tool_windows() == []
    assert host.file_handlers() == []
    assert host.categories() == []
    assert host.columns() == []
    assert host.search_providers() == []
    assert host.theme_tokens() == []
    assert host.context_menu_items() == []
    assert host._permissions_by_plugin.get("pad.pid") is None
    # The plugin's notification was cleaned; the host's survives.
    assert host.notifications() == [
        {"level": "info", "message": "host note", "plugin_id": ""},
    ]


def test_unregister_with_padded_id_refused_gate_matches_normalized_subject(caplog):
    host = PluginHostContext()
    with host.plugin_registration("attacker"):
        host.register_command({"id": "atk.cmd", "title": "Atk"}, lambda: None)
    with caplog.at_level(logging.WARNING):
        with host.plugin_execution("attacker"):
            host.unregister_plugin(" pad.pid ")
    assert "attempted to unregister contributions owned by 'pad.pid'" in caplog.text
    # Attacker's own contribution is untouched by the refused call.
    assert {cmd.id for cmd in host.commands()} == {"atk.cmd"}
