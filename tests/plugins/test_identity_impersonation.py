"""Identity impersonation gate on the public plugin_* context managers.

A plugin receives the raw ``PluginHostContext`` from ``register(host)``, so
before this gate it could claim any identity: another plugin's id to borrow
its grants, or the empty string to launder itself into the host's
unrestricted path.  The gate refuses the *identity change* while still
running the wrapped block.

This is an in-process honesty boundary, not a sandbox: the same plugin can
reach ``_host_identity_scope`` or set ``_executing_plugin_var`` directly.
Host-side dispatch (hooks, ``when`` predicates, operator handlers) uses the
private scope precisely because it legitimately switches identity from
inside another plugin's frame.
"""

import logging
import threading

from AssetsManager.core.plugins.descriptor import PERMISSION_SETTINGS_READ
from AssetsManager.core.plugins.host_context import PluginHostContext


def test_execution_refuses_foreign_identity(caplog):
    host = PluginHostContext()
    with caplog.at_level(logging.WARNING):
        with host.plugin_execution("alpha"):
            with host.plugin_execution("beta"):
                # The block still runs, but under alpha's identity.
                assert host._permission_subject() == "alpha"
            assert host._permission_subject() == "alpha"
    assert "attempted to assume identity 'beta'" in caplog.text


def test_execution_refuses_host_laundering(caplog):
    host = PluginHostContext()
    with caplog.at_level(logging.WARNING):
        with host.plugin_execution("alpha"):
            with host.plugin_execution(""):
                assert host._permission_subject() == "alpha"
    assert "attempted to assume identity '<host>'" in caplog.text


def test_registration_refuses_foreign_identity(caplog):
    host = PluginHostContext()
    with caplog.at_level(logging.WARNING):
        with host.plugin_registration("alpha"):
            with host.plugin_registration("beta"):
                assert host._permission_subject() == "alpha"
    assert "attempted to assume identity 'beta'" in caplog.text


def test_reasserting_same_identity_is_allowed():
    host = PluginHostContext()
    with host.plugin_execution("alpha"):
        with host.plugin_execution("alpha"):
            assert host._permission_subject() == "alpha"
        assert host._permission_subject() == "alpha"


def test_host_entry_is_unrestricted():
    """No active plugin subject: the host may assume any identity."""
    host = PluginHostContext()
    with host.plugin_execution("alpha"):
        assert host._permission_subject() == "alpha"
    with host.plugin_execution("beta"):
        assert host._permission_subject() == "beta"
    assert host._permission_subject() == ""


def test_host_dispatch_switches_identity_from_plugin_frame():
    """The private scope keeps legitimate nested host dispatch working.

    A plugin callback publishing an event makes the host dispatch another
    plugin's hook from inside the first plugin's frame; the public gate
    would refuse that transition, so host dispatch must not use it.
    """
    host = PluginHostContext()
    seen: list[str] = []
    with host.plugin_execution("alpha"):
        with host._host_identity_scope(host._executing_plugin_var, "beta"):
            seen.append(host._permission_subject())
        seen.append(host._permission_subject())
    assert seen == ["beta", "alpha"]


def test_gate_does_not_leak_grants_across_plugins():
    host = PluginHostContext()
    with host._host_identity():
        host.grant_permissions("victim", {PERMISSION_SETTINGS_READ})
    with host.plugin_execution("attacker"):
        # Refused identity change means the attacker keeps its own (empty)
        # grants rather than borrowing the victim's.
        with host.plugin_execution("victim"):
            assert host.check_permission(PERMISSION_SETTINGS_READ) is False


def test_unmarked_thread_does_not_inherit_plugin_subject():
    """Python 3.14 threads do not copy the caller's context by default.

    Recorded as behaviour: an unmarked worker thread resolves to the empty
    subject.  That empty subject is no longer enough to act as the host —
    the mutation gates (``grant_permissions``, host-side
    ``unregister_plugin``) additionally require the explicit host identity
    marker entered via ``_host_identity()``, which likewise does not
    propagate into spawned threads (see test_thread_identity_bypass).
    """
    host = PluginHostContext()
    observed: list[str] = []

    def worker() -> None:
        observed.append(host._permission_subject())

    with host.plugin_execution("alpha"):
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(timeout=5.0)
    assert observed == [""]
