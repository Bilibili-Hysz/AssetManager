"""Permission and identity gates added in the enforcement round.

Covers the new gates on ``preferences()`` (``settings.read`` /
``settings.write``), ``open_path()`` (``filesystem.read``) and the
identity gates on ``execute_command()`` / ``undo_last_command()`` (a
plugin may only run or undo its own commands; the host may run any).

These gates are honesty/intent boundaries, not a security sandbox: a
plugin runs in the same interpreter and can bypass them with direct
stdlib imports.  The tests therefore assert the host API behaviour —
refusal with a logged warning, and the host path still working.
"""
from __future__ import annotations

import logging

from AssetsManager.core.plugins.host_context import PluginHostContext
from AssetsManager.core.plugins.manager import PluginManagerService
from AssetsManager.core.plugins.preferences import set_prefs_root
from AssetsManager.plugin_api import CommandOperator, Preferences


class _Ping(CommandOperator):
    id = "alpha.ping"
    title = "Ping"

    def execute(self, ctx, params=None):
        return None


class _Sink(CommandOperator):
    id = "beta.sink"
    title = "Sink"

    def execute(self, ctx, params=None):
        return None


# ── preferences(): settings.read / settings.write ──────────────────


class _KeepDays(Preferences):
    settings = {"keep_days": {"type": "int", "default": 7}}


def test_preferences_refused_without_settings_permission(tmp_path, caplog):
    set_prefs_root(tmp_path / "prefs")
    try:
        host = PluginHostContext()
        with host.plugin_registration("bare"):
            assert host.register_class(_KeepDays) is True
        with caplog.at_level(logging.WARNING):
            with host.plugin_execution("bare"):
                bag = host.plugin_context().preferences()
        assert bag is None
        assert "attempted to access preferences without" in caplog.text
        assert "settings.read" in caplog.text
        # Refusal constructed no bag and created no file on disk.
        assert not (tmp_path / "prefs").exists()
    finally:
        set_prefs_root(None)


def test_preferences_allowed_with_settings_read(tmp_path):
    set_prefs_root(tmp_path / "prefs")
    try:
        host = PluginHostContext()
        with host._host_identity():
            host.grant_permissions("reader", {"settings.read"})
        with host.plugin_registration("reader"):
            assert host.register_class(_KeepDays) is True
            bag = host.preferences()
        assert bag is not None
        assert bag.get("keep_days") == 7
    finally:
        set_prefs_root(None)


def test_preferences_allowed_with_settings_write(tmp_path):
    """Either settings token suffices: own-bag access is one gate."""
    set_prefs_root(tmp_path / "prefs")
    try:
        host = PluginHostContext()
        with host._host_identity():
            host.grant_permissions("writer", {"settings.write"})
        with host.plugin_registration("writer"):
            assert host.register_class(_KeepDays) is True
            bag = host.preferences()
        assert bag is not None
        assert bag.get("keep_days") == 7
    finally:
        set_prefs_root(None)


def test_manifest_plugin_without_settings_permission_gets_no_bag(tmp_path):
    """End to end: a manifest without settings.* sees preferences() == None."""
    from AssetsManager.core.plugins.preferences import set_prefs_root as set_root

    set_root(tmp_path / "prefs")
    try:
        plugin_dir = tmp_path / "nosettings"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.json").write_text(
            '{"id":"nosettings","name":"NoSettings","version":"1.0",'
            '"entry":"main:Plugin","permissions":["filesystem.read"]}',
            encoding="utf-8",
        )
        (plugin_dir / "main.py").write_text(
            "class Plugin:\n"
            "    def register(self, host):\n"
            "        assert host.plugin_context().preferences() is None\n",
            encoding="utf-8",
        )
        PluginManagerService._instance = None
        manager = PluginManagerService(search_paths=[tmp_path])
        manager.discover_plugins()
        host = PluginHostContext()
        assert manager.load_plugin("nosettings", host).ok
        manager.unload_plugin("nosettings")
        PluginManagerService._instance = None
    finally:
        set_root(None)


# ── open_path(): filesystem.read ────────────────────────────────────


def _patch_startfile(monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr(
        "AssetsManager.core.plugins.host_context.os.startfile", opened.append
    )
    return opened


def test_open_path_refused_without_filesystem_read(tmp_path, caplog, monkeypatch):
    target = tmp_path / "note.txt"
    target.write_text("x", encoding="utf-8")
    opened = _patch_startfile(monkeypatch)
    host = PluginHostContext()
    with caplog.at_level(logging.WARNING):
        with host.plugin_execution("bare"):
            assert host.open_path(str(target)) is False
    assert opened == []
    assert "attempted open_path without permission" in caplog.text


def test_open_path_allowed_with_filesystem_read(tmp_path, monkeypatch):
    target = tmp_path / "note.txt"
    target.write_text("x", encoding="utf-8")
    opened = _patch_startfile(monkeypatch)
    host = PluginHostContext()
    with host._host_identity():
        host.grant_permissions("reader", {"filesystem.read"})
    with host.plugin_execution("reader"):
        assert host.open_path(str(target)) is True
    assert opened == [str(target)]


def test_open_path_host_dispatch_with_explicit_identity(tmp_path, monkeypatch):
    """The host may still open paths, but must declare an identity explicitly.

    The old empty-subject exemption was the thread-laundering hole this
    round closed: a plugin could move the call into a thread it spawned
    (empty ContextVar) and pass as "the host".  Host dispatch now enters
    ``_host_identity_scope`` with a granted identity, like the manager
    does before invoking ``register()``.
    """
    target = tmp_path / "note.txt"
    target.write_text("x", encoding="utf-8")
    opened = _patch_startfile(monkeypatch)
    host = PluginHostContext()
    with host._host_identity():
        host.grant_permissions("host.dispatch", {"filesystem.read"})
    with host._host_identity_scope(host._executing_plugin_var, "host.dispatch"):
        assert host.open_path(str(target)) is True
    assert opened == [str(target)]


def test_open_path_without_plugin_identity_is_refused(tmp_path, caplog, monkeypatch):
    """A bare call — host code, headless caller, or a plugin thread that
    lost its identity ContextVar — is refused with a warning."""
    target = tmp_path / "note.txt"
    target.write_text("x", encoding="utf-8")
    opened = _patch_startfile(monkeypatch)
    host = PluginHostContext()
    with caplog.at_level(logging.WARNING):
        assert host.open_path(str(target)) is False
    assert opened == []
    assert "no plugin identity" in caplog.text


# ── execute_command(): plugin may only run its own commands ─────────


def test_execute_command_cross_plugin_refused(caplog):
    host = PluginHostContext()
    with host.plugin_registration("alpha"):
        assert host.register_class(_Ping) is True
    with host.plugin_registration("beta"):
        assert host.register_class(_Sink) is True

    with caplog.at_level(logging.WARNING):
        with host.plugin_execution("alpha"):
            assert host.execute_command("beta.sink") is False
    assert "attempted to execute command 'beta.sink'" in caplog.text

    # The host (no active plugin subject) may still run it.
    assert host.execute_command("beta.sink") is True


def test_execute_command_own_command_allowed():
    host = PluginHostContext()
    with host.plugin_registration("alpha"):
        assert host.register_class(_Ping) is True
    with host.plugin_execution("alpha"):
        assert host.execute_command("alpha.ping") is True


def test_execute_command_legacy_cross_plugin_refused(caplog):
    host = PluginHostContext()
    host.register_command({"id": "legacy.b", "title": "B"}, lambda: None, "beta")
    with caplog.at_level(logging.WARNING):
        with host.plugin_execution("alpha"):
            assert host.execute_command("legacy.b") is False
    assert "attempted to execute command 'legacy.b'" in caplog.text
    assert host.execute_command("legacy.b") is True


# ── undo_last_command(): plugin may only undo its own operators ─────


def test_undo_last_command_cross_plugin_refused(caplog):
    undone: list[str] = []

    class AlphaOp(CommandOperator):
        id = "alpha.op"
        title = "AlphaOp"
        undoable = True

        def execute(self, ctx, params=None):
            return {"who": "alpha"}

        def undo(self, ctx, record):
            undone.append("alpha")

    class BetaOp(CommandOperator):
        id = "beta.op"
        title = "BetaOp"
        undoable = True

        def execute(self, ctx, params=None):
            return {"who": "beta"}

        def undo(self, ctx, record):
            undone.append("beta")

    host = PluginHostContext()
    with host.plugin_registration("alpha"):
        assert host.register_class(AlphaOp) is True
    with host.plugin_registration("beta"):
        assert host.register_class(BetaOp) is True
    assert host.execute_command("alpha.op") is True
    assert host.execute_command("beta.op") is True

    # Top of the stack is beta's record: alpha cannot pop it, and the
    # refusal leaves the stack untouched.
    with caplog.at_level(logging.WARNING):
        with host.plugin_execution("alpha"):
            assert host.undo_last_command() is False
    assert "attempted to undo a command owned by 'beta'" in caplog.text
    assert undone == []

    # The host undoes the top record regardless of owner.
    assert host.undo_last_command() is True
    assert undone == ["beta"]

    # A plugin can undo its own record once it is on top.
    with host.plugin_execution("alpha"):
        assert host.undo_last_command() is True
    assert undone == ["beta", "alpha"]
    assert host.undo_last_command() is False
