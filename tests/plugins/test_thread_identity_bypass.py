"""Thread-laundering closure: gated APIs refuse calls with no plugin identity.

Plugin code runs under a registration/execution ContextVar that does not
propagate into threads the plugin spawns (``threading.Thread`` /
``ThreadPoolExecutor``).  Those threads used to look like the host — an
empty ``_permission_subject()`` — and ``_check_permission_warn`` let the
empty subject pass, so a plugin could shift any gated call into a fresh
thread and bypass every permission.  The gate now refuses empty subjects;
these tests prove the refusal for the gated APIs, keep the in-scope
success path covered, and show the sanctioned way to carry identity into
a worker thread (re-entering ``plugin_execution`` inside it).

The mutation gates got the same closure one round later: an empty subject
alone no longer makes a caller the host.  ``grant_permissions`` and
host-side ``unregister_plugin`` additionally require the explicit host
identity marker (``_host_identity()``), which lives in its own ContextVar
and does not propagate into spawned threads either — so a plugin cannot
launder a self-grant or strip another plugin's contributions through a
thread it spawned.

Honesty note (as everywhere in this suite): this is an in-process honesty
boundary, not a sandbox.  A plugin can still reach ``_host_identity``,
``_host_identity_scope`` or the identity ContextVars directly.
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from AssetsManager.core.plugins.descriptor import PERMISSION_HOST_SERVICES
from AssetsManager.core.plugins.host_context import PluginHostContext


def _register_all(host: PluginHostContext, plugin_id: str) -> None:
    host.register_file_handler(plugin_id, lambda p: False, lambda p: {})
    host.register_category(plugin_id, "cat", "Cat", {".x"})
    host.register_search_provider(plugin_id, "sp", "SP", lambda q, r: [])
    host.register_theme_token(plugin_id, "tok", "#fff")


def _anything_registered(host: PluginHostContext) -> bool:
    return bool(
        host.file_handlers()
        or host.categories()
        or host.search_providers()
        or host.theme_tokens()
    )


def _patch_default_opener(monkeypatch) -> list[str]:
    """Record paths handed to the platform default-application opener.

    The seam is the module-level ``_open_with_default_handler`` helper —
    not ``os.startfile``, which only exists on Windows, so patching it
    made these tests crash on POSIX with an AttributeError before the
    assertion body ran.
    """
    opened: list[str] = []
    monkeypatch.setattr(
        "AssetsManager.core.plugins.host_context._open_with_default_handler",
        opened.append,
    )
    return opened


def test_plugin_thread_cannot_ride_host_exemption(tmp_path, caplog, monkeypatch):
    """A thread spawned by plugin code loses its identity ContextVar and is
    refused by every permission-gated API — the old empty-subject pass is gone."""
    target = tmp_path / "note.txt"
    target.write_text("x", encoding="utf-8")
    opened = _patch_default_opener(monkeypatch)

    host = PluginHostContext()
    with host._host_identity():
        host.grant_permissions("threader", {"filesystem.read", "settings.write"})
    outcomes: list[bool] = []

    def attempt() -> None:
        _register_all(host, "threader")
        outcomes.append(host.open_path(str(target)))

    with host.plugin_registration("threader"):
        with caplog.at_level(logging.WARNING):
            worker = threading.Thread(target=attempt)
            worker.start()
            worker.join()

    assert outcomes == [False]
    assert not _anything_registered(host)
    assert opened == []
    assert "no plugin identity" in caplog.text


def test_thread_pool_worker_cannot_ride_host_exemption(tmp_path, caplog, monkeypatch):
    """ThreadPoolExecutor workers get the same refusal: pool dispatch does not
    carry the plugin identity ContextVar either."""
    target = tmp_path / "note.txt"
    target.write_text("x", encoding="utf-8")
    opened = _patch_default_opener(monkeypatch)

    host = PluginHostContext()
    with host._host_identity():
        host.grant_permissions("pooler", {"filesystem.read", "settings.write"})

    def attempt(index: int) -> bool:
        _register_all(host, "pooler")
        return host.open_path(str(target))

    with host.plugin_execution("pooler"):
        with caplog.at_level(logging.WARNING):
            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(attempt, range(4)))

    assert outcomes == [False, False, False, False]
    assert not _anything_registered(host)
    assert opened == []
    assert "no plugin identity" in caplog.text


def test_in_scope_calls_with_grants_succeed(tmp_path, monkeypatch):
    """Positive control: the same calls on the identity-bearing thread still
    work when the manifest grants are present."""
    target = tmp_path / "note.txt"
    target.write_text("x", encoding="utf-8")
    opened = _patch_default_opener(monkeypatch)

    host = PluginHostContext()
    with host._host_identity():
        host.grant_permissions("granted", {"filesystem.read", "settings.write"})

    with host.plugin_registration("granted"):
        _register_all(host, "granted")
    with host.plugin_execution("granted"):
        assert host.open_path(str(target)) is True

    assert len(host.file_handlers()) == 1
    assert len(host.categories()) == 1
    assert len(host.search_providers()) == 1
    assert len(host.theme_tokens()) == 1
    assert opened == [str(target)]


def test_worker_thread_with_explicit_plugin_execution_keeps_grants(tmp_path, monkeypatch):
    """Controlled propagation: host-dispatched code may re-enter
    ``plugin_execution`` inside the worker thread to carry the identity and
    its grants across the thread boundary explicitly."""
    target = tmp_path / "note.txt"
    target.write_text("x", encoding="utf-8")
    opened = _patch_default_opener(monkeypatch)

    host = PluginHostContext()
    with host._host_identity():
        host.grant_permissions("carrier", {"filesystem.read", "settings.write"})
    outcomes: list[bool] = []

    def attempt() -> None:
        with host.plugin_execution("carrier"):
            _register_all(host, "carrier")
            outcomes.append(host.open_path(str(target)))

    worker = threading.Thread(target=attempt)
    worker.start()
    worker.join()

    assert outcomes == [True]
    assert len(host.file_handlers()) == 1
    assert len(host.categories()) == 1
    assert len(host.search_providers()) == 1
    assert len(host.theme_tokens()) == 1
    assert opened == [str(target)]


# ── grant_permissions / unregister_plugin: no host identity, no mutation ──


def test_plugin_thread_cannot_grant_permissions_to_itself(caplog):
    """The thread-laundering variant of self-granting is dead.

    A thread spawned inside a plugin frame has neither a plugin subject
    nor the host identity marker, so the grant is refused and the
    permission store stays untouched.
    """
    host = PluginHostContext()
    observed: list[str] = []

    def attempt() -> None:
        observed.append(host._permission_subject())
        host.grant_permissions("evil", {PERMISSION_HOST_SERVICES})

    with host.plugin_execution("evil"):
        with caplog.at_level(logging.WARNING):
            worker = threading.Thread(target=attempt)
            worker.start()
            worker.join()

    assert observed == [""]
    assert "no host identity" in caplog.text
    # The refusal left the permission store untouched (not just the return).
    assert host.granted_permissions("evil") == frozenset()
    with host.plugin_execution("evil"):
        assert host.check_permission(PERMISSION_HOST_SERVICES) is False


def test_thread_pool_worker_cannot_grant_permissions_to_itself(caplog):
    """ThreadPoolExecutor workers get the same refusal: pool dispatch does
    not carry the host identity marker either."""
    host = PluginHostContext()

    def attempt(index: int) -> frozenset[str]:
        host.grant_permissions("evil", {PERMISSION_HOST_SERVICES})
        return host.granted_permissions("evil")

    with host.plugin_execution("evil"):
        with caplog.at_level(logging.WARNING):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(attempt, range(4)))

    assert "no host identity" in caplog.text
    assert results == [frozenset(), frozenset(), frozenset(), frozenset()]
    assert host.granted_permissions("evil") == frozenset()


def test_plugin_thread_cannot_unregister_another_plugin(caplog):
    """unregister_plugin got the same closure: an unmarked thread is not
    the host, so a plugin cannot strip another plugin's contributions (or
    grants) from a thread it spawned."""
    host = PluginHostContext()
    with host.plugin_registration("victim"):
        host.register_command({"id": "victim.cmd", "title": "V"}, lambda: None, "victim")
    with host.plugin_registration("attacker"):
        host.register_command({"id": "attacker.cmd", "title": "A"}, lambda: None, "attacker")
    assert len(host.commands()) == 2

    with caplog.at_level(logging.WARNING):
        with host.plugin_execution("attacker"):
            worker = threading.Thread(target=lambda: host.unregister_plugin("victim"))
            worker.start()
            worker.join()

    assert "no host identity" in caplog.text
    assert {cmd.id for cmd in host.commands()} == {"victim.cmd", "attacker.cmd"}

    with caplog.at_level(logging.WARNING):
        with host.plugin_execution("attacker"):
            with ThreadPoolExecutor(max_workers=1) as pool:
                list(pool.map(lambda _index: host.unregister_plugin("victim"), range(1)))

    assert {cmd.id for cmd in host.commands()} == {"victim.cmd", "attacker.cmd"}
