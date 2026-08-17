"""Identity gating on PluginHostContext: preference bags, unregister, grants.

Preference bags may hold credentials, so ``preferences()`` must resolve the
bag from the calling plugin's contextvar identity and never from a
caller-supplied id.  Own-bag access is additionally gated on the manifest's
``settings.read`` / ``settings.write`` tokens.  ``unregister_plugin()`` is
likewise gated so one plugin cannot strip another plugin's contributions.
``grant_permissions()`` is gated the hardest of all: no active plugin
subject may grant anything, not even to itself, because self-granting
``host.services`` would let a plugin pass every capability check and reach
the full session and authentication services.  Host-side grants require
entering the explicit host identity marker (``_host_identity()``); an
unmarked thread is refused, closing the thread-laundering variant.
"""
from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

from AssetsManager.core.plugins.descriptor import (
    PERMISSION_HOST_SERVICES,
    PLUGIN_STATE_LOADABLE,
)
from AssetsManager.core.plugins.host_context import PluginHostContext
from AssetsManager.core.plugins.manager import PluginManagerService
from AssetsManager.core.plugins.preferences import set_prefs_root
from AssetsManager.plugin_api import Preferences


class _ServicesWindow:
    """Minimal window exposing a services bundle.

    The bundle is bound exactly like the real window does it, so the only
    thing standing between a plugin and services is the ``host.services``
    permission gate on the host context.
    """

    def __init__(self) -> None:
        self._library_session = object()
        self._services = SimpleNamespace(
            metadata_service=object(),
            token_secret="SECRET",
        )

    def _scoped_services_for_session(self, session):
        assert session is self._library_session
        return self._services


class _AlphaPrefs(Preferences):
    settings = {"keep_days": {"type": "int", "default": 7}}


class _BetaPrefs(Preferences):
    settings = {"retention": {"type": "str", "default": "30d"}}


def _host_with_two_pref_plugins() -> PluginHostContext:
    host = PluginHostContext()
    # Own-bag access is gated on settings.read/settings.write; both
    # plugins declare the settings tokens so their bags are reachable.
    # Granting is host-side: enter explicit host identity.
    with host._host_identity():
        host.grant_permissions("alpha", {"settings.read", "settings.write"})
        host.grant_permissions("beta", {"settings.read", "settings.write"})
    with host.plugin_registration("alpha"):
        assert host.register_class(_AlphaPrefs) is True
    with host.plugin_registration("beta"):
        assert host.register_class(_BetaPrefs) is True
    return host


def test_plugin_cannot_read_another_plugins_bag(tmp_path, caplog):
    set_prefs_root(tmp_path / "prefs")
    try:
        host = _host_with_two_pref_plugins()
        # Seed beta's real bag through the host-internal path.
        host._preferences_for("beta").set("api_key", "beta-secret")

        with caplog.at_level(logging.WARNING):
            with host.plugin_execution("alpha"):
                bag = host.plugin_context().preferences("beta")

        # Alpha got its own bag, not beta's: no secret, alpha's defaults only.
        assert bag is not None
        assert bag.plugin_id == "alpha"
        assert "api_key" not in bag.as_dict()
        assert bag.get("keep_days") == 7
        assert "cross-plugin preference access" in caplog.text
        # Beta's real bag is untouched.
        assert host._preferences_for("beta").get("api_key") == "beta-secret"
    finally:
        set_prefs_root(None)


def test_plugin_cannot_write_another_plugins_bag(tmp_path):
    set_prefs_root(tmp_path / "prefs")
    try:
        host = _host_with_two_pref_plugins()
        host._preferences_for("beta").set("api_key", "beta-secret")

        with host.plugin_execution("alpha"):
            bag = host.plugin_context().preferences("beta")
            bag.set("api_key", "alpha-forged")

        # Beta's file is unchanged; the write landed in alpha's own bag.
        assert host._preferences_for("beta").get("api_key") == "beta-secret"
        assert host._preferences_for("alpha").get("api_key") == "alpha-forged"

        # Only the two legitimate bag files exist on disk.
        names = sorted(p.name for p in (tmp_path / "prefs").iterdir())
        assert names == ["alpha.json", "beta.json"]
    finally:
        set_prefs_root(None)


def test_preferences_host_path_and_unset_context(tmp_path):
    set_prefs_root(tmp_path / "prefs")
    try:
        host = _host_with_two_pref_plugins()

        # No plugin context (host at startup): well-defined None, and no
        # bag file is ever created for an empty/"None" id.
        assert host.preferences() is None
        assert host.preferences("alpha") is None
        assert host.plugin_context().preferences("alpha") is None
        assert not (tmp_path / "prefs").exists()

        # The host reaches a specific plugin's bag through the internal
        # accessor (used by host-side plugin management).
        bag = host._preferences_for("beta")
        assert bag.plugin_id == "beta"
        assert bag.get("retention") == "30d"
        bag.set("retention", "60d")
        assert host._preferences_for("beta").get("retention") == "60d"
    finally:
        set_prefs_root(None)


def test_plugin_cannot_unregister_another_plugin(caplog):
    host = PluginHostContext()
    with host.plugin_registration("victim"):
        host.register_command({"id": "victim.cmd", "title": "Victim"}, lambda: None, "victim")
    with host.plugin_registration("attacker"):
        host.register_command({"id": "attacker.cmd", "title": "Attacker"}, lambda: None, "attacker")
    assert len(host.commands()) == 2

    # A plugin running on its own behalf cannot strip another plugin.
    with caplog.at_level(logging.WARNING):
        with host.plugin_execution("attacker"):
            host.unregister_plugin("victim")
    assert "attempted to unregister contributions owned by 'victim'" in caplog.text
    assert {cmd.id for cmd in host.commands()} == {"victim.cmd", "attacker.cmd"}

    # It may unregister itself.
    with host.plugin_execution("attacker"):
        host.unregister_plugin("attacker")
    assert {cmd.id for cmd in host.commands()} == {"victim.cmd"}

    # The host unregisters any plugin, but must declare host identity.
    with host._host_identity():
        host.unregister_plugin("victim")
    assert host.commands() == []


def test_download_tracker_preferences_round_trip(tmp_path):
    """The shipped example's own preferences still round-trip under the gate."""

    addon = Path(__file__).resolve().parents[2] / "Plugins" / "Addons" / "download_tracker"
    set_prefs_root(tmp_path / "plugin_prefs")

    def _load(host: PluginHostContext) -> PluginManagerService:
        manager = PluginManagerService(search_paths=[addon.parent])
        manager.discover_plugins()
        record = manager.plugin_record("download_tracker")
        assert record is not None
        record.enabled = True
        record.state = PLUGIN_STATE_LOADABLE
        assert manager.load_plugin("download_tracker", host).ok
        return manager

    host1 = PluginHostContext()
    manager1 = _load(host1)
    try:
        # Executing as the tracker, its own id resolves to its own bag.
        with host1.plugin_execution("download_tracker"):
            bag = host1.plugin_context().preferences("download_tracker")
            assert bag is not None
            assert bag.plugin_id == "download_tracker"
            assert bag.get("keep_days") == 30  # TrackerPrefs schema default
            bag.set("keep_days", 7)
        with host1.plugin_execution("download_tracker"):
            assert host1.plugin_context().preferences().get("keep_days") == 7
    finally:
        manager1.unload_plugin("download_tracker")
        PluginManagerService._instance = None

    # A fresh host instance re-reads the persisted value from disk.
    host2 = PluginHostContext()
    manager2 = _load(host2)
    try:
        with host2.plugin_execution("download_tracker"):
            assert host2.plugin_context().preferences().get("keep_days") == 7
    finally:
        manager2.unload_plugin("download_tracker")
        PluginManagerService._instance = None
        set_prefs_root(None)


def test_preferences_mismatch_returns_calling_plugins_own_bag(tmp_path):
    """A mismatched id never escalates: the caller's own bag comes back."""
    set_prefs_root(tmp_path / "prefs")
    try:
        host = _host_with_two_pref_plugins()
        host._preferences_for("beta").set("api_key", "beta-secret")
        with host.plugin_execution("alpha"):
            bag = host.plugin_context().preferences("beta")
        # Degrades to alpha's bag with its defaults, never beta's data.
        assert bag.plugin_id == "alpha"
        assert bag.as_dict() == {"keep_days": 7}
    finally:
        set_prefs_root(None)


def test_plugin_cannot_grant_permissions_to_itself(caplog):
    """Self-granting is the privilege-escalation exploit: it must be refused."""
    host = PluginHostContext()
    with caplog.at_level(logging.WARNING):
        with host.plugin_registration("rogue"):
            host.grant_permissions("rogue", {PERMISSION_HOST_SERVICES})
    assert "attempted to grant permissions" in caplog.text
    # The refusal left the permission store untouched.
    assert host.granted_permissions("rogue") == frozenset()
    with host.plugin_registration("rogue"):
        assert host.check_permission(PERMISSION_HOST_SERVICES) is False


def test_plugin_cannot_grant_permissions_to_another_plugin(caplog):
    """A plugin cannot bestow capabilities on any plugin, itself or another."""
    host = PluginHostContext()
    with caplog.at_level(logging.WARNING):
        with host.plugin_registration("attacker"):
            host.grant_permissions("victim", {PERMISSION_HOST_SERVICES})
    assert "attempted to grant permissions" in caplog.text
    assert host.granted_permissions("victim") == frozenset()
    with host.plugin_registration("victim"):
        assert host.check_permission(PERMISSION_HOST_SERVICES) is False


def test_plugin_cannot_grant_permissions_during_execution(caplog):
    """The executing contextvar (command/hook callbacks) is gated too.

    This closes the later variant of the hole where a plugin reaches back
    through its stored PluginContext host reference after registration.
    """
    host = PluginHostContext()
    with caplog.at_level(logging.WARNING):
        with host.plugin_execution("rogue"):
            host.grant_permissions("rogue", {PERMISSION_HOST_SERVICES})
    assert "attempted to grant permissions" in caplog.text
    assert host.granted_permissions("rogue") == frozenset()


def test_host_can_still_grant_permissions():
    """The manager grants manifest permissions under explicit host identity."""
    host = PluginHostContext()
    with host._host_identity():
        host.grant_permissions("alpha", {PERMISSION_HOST_SERVICES})
    with host.plugin_registration("alpha"):
        assert host.check_permission(PERMISSION_HOST_SERVICES) is True


def test_self_grant_escalation_is_closed_end_to_end(caplog):
    """The full exploit chain is dead: self-grant, then reach for services.

    Proves the fix rather than just the mechanism: even inside the very
    context that attempts the self-grant, and again in a later execution
    context, the service capability is still refused and the store is
    empty.
    """
    host = PluginHostContext()
    host.bind_window(_ServicesWindow())
    ctx = host.plugin_context()

    with caplog.at_level(logging.WARNING):
        with host.plugin_registration("rogue"):
            host.grant_permissions("rogue", {PERMISSION_HOST_SERVICES})
            assert host.current_services() is None
            assert ctx.services() is None
            assert ctx.session is None
            assert ctx.window is None
    # The attempted self-grant never landed: a later execution context is
    # refused exactly like the registration context was.
    assert host.granted_permissions("rogue") == frozenset()
    with host.plugin_execution("rogue"):
        assert host.current_services() is None
        assert ctx.services() is None


def test_host_grant_without_host_identity_is_refused(caplog):
    """An empty plugin subject alone no longer grants.

    Host code must enter the explicit host identity marker, or the call
    is refused exactly like a plugin thread that lost its identity
    ContextVar.
    """
    host = PluginHostContext()
    with caplog.at_level(logging.WARNING):
        host.grant_permissions("alpha", {PERMISSION_HOST_SERVICES})
    assert "no host identity" in caplog.text
    assert host.granted_permissions("alpha") == frozenset()


def test_plugin_cannot_read_another_plugins_permissions(caplog):
    """Cross-plugin permission enumeration degrades to the caller's own set."""
    host = PluginHostContext()
    with host._host_identity():
        host.grant_permissions("alpha", {"settings.read"})
        host.grant_permissions("beta", {PERMISSION_HOST_SERVICES})

    with caplog.at_level(logging.WARNING):
        with host.plugin_execution("alpha"):
            seen = host.granted_permissions("beta")
            own = host.granted_permissions()
    assert "attempted to read permissions of 'beta'" in caplog.text
    assert seen == frozenset({"settings.read"})
    assert own == frozenset({"settings.read"})


def test_host_can_read_any_plugins_permissions():
    """Host code (plugin manager dialog) still reads any plugin's grants."""
    host = PluginHostContext()
    with host._host_identity():
        host.grant_permissions("alpha", {"settings.read"})
        host.grant_permissions("beta", {PERMISSION_HOST_SERVICES})
    assert host.granted_permissions("alpha") == frozenset({"settings.read"})
    assert host.granted_permissions("beta") == frozenset({PERMISSION_HOST_SERVICES})

