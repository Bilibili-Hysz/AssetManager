"""Concurrency contracts for plugin manager lifecycle transitions."""
from __future__ import annotations

import json
import shutil
import threading

from AssetsManager.core.plugins.host_context import PluginHostContext
import AssetsManager.core.plugins.manager as manager_module
from AssetsManager.core.plugins.manager import PluginManagerService


def _write_plugin(root, plugin_id, source):
    folder = root / plugin_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plugin.json").write_text(
        json.dumps({
            "id": plugin_id,
            "name": plugin_id,
            "version": "1.0.0",
            "entry": "main:Plugin",
            "enabled_by_default": True,
            "permissions": [],
        }),
        encoding="utf-8",
    )
    (folder / "main.py").write_text(source, encoding="utf-8")


def test_concurrent_load_serializes_register_callback(tmp_path):
    _write_plugin(
        tmp_path,
        "serial",
        "class Plugin:\n"
        "    def register(self, host):\n"
        "        host.show_notification('registered')\n",
    )
    manager = PluginManagerService(search_paths=[tmp_path])
    manager.discover_plugins()
    host = PluginHostContext()

    entered = threading.Event()
    release = threading.Event()
    calls = 0
    calls_lock = threading.Lock()
    real_load = manager.loader.load

    def blocked_load(*args, **kwargs):
        nonlocal calls
        with calls_lock:
            calls += 1
        entered.set()
        assert release.wait(2)
        return real_load(*args, **kwargs)

    manager.loader.load = blocked_load
    first = threading.Thread(target=lambda: manager.load_plugin("serial", host))
    second_result = []
    second = threading.Thread(
        target=lambda: second_result.append(manager.load_plugin("serial", host))
    )
    first.start()
    assert entered.wait(2)
    second.start()
    release.set()
    first.join(2)
    second.join(2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert calls == 1
    assert second_result[0].ok is True
    assert [n for n in host.notifications() if n["message"] == "registered"] == [
        {"level": "info", "message": "registered", "plugin_id": "serial"}
    ]


def test_unload_waits_for_inflight_load_then_unregisters_once(tmp_path):
    _write_plugin(
        tmp_path,
        "racing",
        "class Plugin:\n"
        "    def register(self, host):\n"
        "        host.show_notification('registered')\n"
        "    def unregister(self, host):\n"
        "        host.show_notification('unregistered')\n",
    )
    manager = PluginManagerService(search_paths=[tmp_path])
    manager.discover_plugins()
    host = PluginHostContext()
    messages = []
    original_notification = host.show_notification

    def record_notification(message, level="info"):
        messages.append(message)
        return original_notification(message, level)

    host.show_notification = record_notification

    entered = threading.Event()
    release = threading.Event()
    real_load = manager.loader.load

    def blocked_load(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return real_load(*args, **kwargs)

    manager.loader.load = blocked_load
    load_result = []
    unload_result = []
    loader = threading.Thread(target=lambda: load_result.append(manager.load_plugin("racing", host)))
    unloader = threading.Thread(target=lambda: unload_result.append(manager.unload_plugin("racing")))
    loader.start()
    assert entered.wait(2)
    unloader.start()
    release.set()
    loader.join(2)
    unloader.join(2)

    assert not loader.is_alive()
    assert not unloader.is_alive()
    assert load_result[0].ok is True
    assert unload_result == [True]
    assert manager.plugin_record("racing").plugin_instance is None
    assert messages == ["registered", "unregistered"]


def test_rediscovery_retains_loaded_record_and_contributions(tmp_path):
    _write_plugin(
        tmp_path,
        "retained",
        "class Plugin:\n"
        "    def register(self, host):\n"
        "        host.register_command({'id': 'retained.command', 'title': 'Retained'})\n"
        "    def unregister(self, host):\n"
        "        pass\n",
    )
    manager = PluginManagerService(search_paths=[tmp_path])
    manager.discover_plugins()
    host = PluginHostContext()
    assert manager.load_plugin("retained", host).ok
    original = manager.plugin_record("retained")

    manager.discover_plugins()

    assert manager.plugin_record("retained") is original
    assert manager.plugin_record("retained").plugin_instance is not None
    assert [command.id for command in host.commands()] == ["retained.command"]
    assert manager.unload_plugin("retained") is True
    assert host.commands() == []


def test_load_all_enabled_uses_snapshot_when_records_change(tmp_path, monkeypatch):
    _write_plugin(tmp_path, "first", "class Plugin:\n    def register(self, host): pass\n")
    _write_plugin(tmp_path, "second", "class Plugin:\n    def register(self, host): pass\n")
    manager = PluginManagerService(search_paths=[tmp_path])
    manager.discover_plugins()
    host = PluginHostContext()
    original_load = manager.load_plugin
    loaded_ids = []

    def load_and_rediscover(plugin_id, context):
        loaded_ids.append(plugin_id)
        if plugin_id == "first":
            manager._records.pop("second")
        return original_load(plugin_id, context)

    monkeypatch.setattr(manager, "load_plugin", load_and_rediscover)

    results = manager.load_all_enabled(host)

    assert loaded_ids == ["first", "second"]
    assert len(results) == 2
    assert results[0].ok is True
    assert results[1].ok is False


def test_cross_plugin_lifecycle_request_from_callback_fails_without_hanging(tmp_path):
    _write_plugin(
        tmp_path,
        "first",
        "class Plugin:\n"
        "    def register(self, host):\n"
        "        pass\n",
    )
    _write_plugin(tmp_path, "second", "class Plugin:\n    def register(self, host): pass\n")
    manager = PluginManagerService(search_paths=[tmp_path])
    manager.discover_plugins()
    host = PluginHostContext()
    nested_results = []
    original_notification = host.show_notification

    def request_second(message, level="info"):
        nested_results.append(manager.load_plugin("second", host))
        return original_notification(message, level)

    host.show_notification = request_second
    folder = tmp_path / "first"
    (folder / "main.py").write_text(
        "class Plugin:\n"
        "    def register(self, host):\n"
        "        host.show_notification('first')\n",
        encoding="utf-8",
    )

    result = []
    worker = threading.Thread(target=lambda: result.append(manager.load_plugin("first", host)))
    worker.start()
    worker.join(2)

    assert not worker.is_alive()
    assert result[0].ok is True
    assert nested_results[0].ok is False
    assert nested_results[0].diagnostics[0].code == "plugin.lifecycle_in_progress"
    assert manager.plugin_record("second").plugin_instance is None


def test_shared_host_callbacks_are_serialized_for_distinct_plugins(tmp_path):
    source = (
        "class Plugin:\n"
        "    def register(self, host):\n"
        "        host.show_notification('register')\n"
        "    def unregister(self, host):\n"
        "        host.show_notification('unregister')\n"
    )
    _write_plugin(tmp_path, "first", source)
    _write_plugin(tmp_path, "second", source)
    manager = PluginManagerService(search_paths=[tmp_path])
    manager.discover_plugins()
    host = PluginHostContext()
    active_callbacks = 0
    maximum_callbacks = 0
    messages = []
    callback_lock = threading.Lock()
    original_notification = host.show_notification

    def tracked_notification(message, level="info"):
        nonlocal active_callbacks, maximum_callbacks
        with callback_lock:
            active_callbacks += 1
            maximum_callbacks = max(maximum_callbacks, active_callbacks)
        try:
            threading.Event().wait(0.05)
            messages.append(message)
            return original_notification(message, level)
        finally:
            with callback_lock:
                active_callbacks -= 1

    host.show_notification = tracked_notification
    loaders = [
        threading.Thread(target=lambda plugin_id=plugin_id: manager.load_plugin(plugin_id, host))
        for plugin_id in ("first", "second")
    ]
    for worker in loaders:
        worker.start()
    for worker in loaders:
        worker.join(2)
    assert all(not worker.is_alive() for worker in loaders)
    assert maximum_callbacks == 1
    assert sorted(messages) == ["register", "register"]

    unloaders = [
        threading.Thread(target=lambda plugin_id=plugin_id: manager.unload_plugin(plugin_id))
        for plugin_id in ("first", "second")
    ]
    for worker in unloaders:
        worker.start()
    for worker in unloaders:
        worker.join(2)
    assert all(not worker.is_alive() for worker in unloaders)
    assert maximum_callbacks == 1
    assert sorted(messages) == ["register", "register", "unregister", "unregister"]


def test_rediscovery_during_failed_load_applies_fresh_record(tmp_path):
    _write_plugin(
        tmp_path,
        "refresh",
        "class Plugin:\n"
        "    def register(self, host):\n"
        "        raise RuntimeError('original failure')\n",
    )
    manager = PluginManagerService(search_paths=[tmp_path])
    manager.discover_plugins()
    host = PluginHostContext()
    entered = threading.Event()
    release = threading.Event()
    original_load = manager.loader.load

    def blocked_load(*args, **kwargs):
        loaded = original_load(*args, **kwargs)
        entered.set()
        assert release.wait(2)
        return loaded

    manager.loader.load = blocked_load
    worker = threading.Thread(target=lambda: manager.load_plugin("refresh", host))
    worker.start()
    assert entered.wait(2)
    _write_plugin(
        tmp_path,
        "refresh",
        "class Plugin:\n"
        "    def register(self, host):\n"
        "        pass\n",
    )
    manager.discover_plugins()
    release.set()
    worker.join(2)

    record = manager.plugin_record("refresh")
    assert not worker.is_alive()
    assert record.state == "loadable"
    assert record.plugin_instance is None
    assert manager.load_plugin("refresh", host).ok is True


def test_rediscovery_during_active_load_defers_fresh_record_until_unload(tmp_path):
    _write_plugin(
        tmp_path,
        "deferred",
        "class Plugin:\n"
        "    def register(self, host):\n"
        "        host.show_notification('old')\n"
        "    def unregister(self, host):\n"
        "        pass\n",
    )
    manager = PluginManagerService(search_paths=[tmp_path])
    manager.discover_plugins()
    host = PluginHostContext()
    entered = threading.Event()
    release = threading.Event()
    original_notification = host.show_notification

    def blocked_notification(message, level="info"):
        entered.set()
        assert release.wait(2)
        return original_notification(message, level)

    host.show_notification = blocked_notification
    worker = threading.Thread(target=lambda: manager.load_plugin("deferred", host))
    worker.start()
    assert entered.wait(2)
    _write_plugin(
        tmp_path,
        "deferred",
        "class Plugin:\n"
        "    def register(self, host):\n"
        "        host.show_notification('fresh')\n",
    )
    manager.discover_plugins()
    release.set()
    worker.join(2)

    active = manager.plugin_record("deferred")
    assert not worker.is_alive()
    assert active.plugin_instance is not None
    assert manager.unload_plugin("deferred") is True
    refreshed = manager.plugin_record("deferred")
    assert refreshed.plugin_instance is None
    assert refreshed.state == "loadable"
    assert manager.load_plugin("deferred", host).ok is True
    assert any(note["message"] == "fresh" for note in host.notifications())


def test_enable_disable_race_leaves_consistent_record(tmp_path):
    _write_plugin(tmp_path, "toggle", "class Plugin:\n    def register(self, host): pass\n")
    manager = PluginManagerService(search_paths=[tmp_path])
    manager.discover_plugins()
    record = manager.plugin_record("toggle")
    record.enabled = False
    record.state = "disabled"
    results = []
    workers = [
        threading.Thread(target=lambda: results.append(manager.enable_plugin("toggle"))),
        threading.Thread(target=lambda: results.append(manager.disable_plugin("toggle"))),
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(2)

    assert all(not worker.is_alive() for worker in workers)
    current = manager.plugin_record("toggle")
    assert current.state in {"disabled", "loadable"}
    assert current.plugin_instance is None
    assert current.enabled is (current.state == "loadable")


def test_disable_holds_transition_until_disabled_state_is_final(tmp_path, monkeypatch):
    _write_plugin(tmp_path, "atomic", "class Plugin:\n    def register(self, host): pass\n")
    manager = PluginManagerService(search_paths=[tmp_path])
    manager.discover_plugins()
    host = PluginHostContext()
    assert manager.load_plugin("atomic", host).ok
    entered = threading.Event()
    release = threading.Event()
    original_unload = manager._unload_claimed_record

    def blocked_unload(record, plugin_id):
        entered.set()
        assert release.wait(2)
        return original_unload(record, plugin_id)

    monkeypatch.setattr(manager, "_unload_claimed_record", blocked_unload)
    disabled = []
    reload_result = []
    disable_thread = threading.Thread(target=lambda: disabled.append(manager.disable_plugin("atomic")))
    reload_thread = threading.Thread(
        target=lambda: reload_result.append(manager.load_plugin("atomic", host))
    )
    disable_thread.start()
    assert entered.wait(2)
    reload_thread.start()
    release.set()
    disable_thread.join(2)
    reload_thread.join(2)

    assert not disable_thread.is_alive()
    assert not reload_thread.is_alive()
    assert disabled == [True]
    assert reload_result[0].ok is False
    record = manager.plugin_record("atomic")
    assert record.enabled is False
    assert record.state == "disabled"
    assert record.plugin_instance is None
    assert host.commands() == []


def test_later_rediscovery_removal_discards_earlier_pending_record(tmp_path):
    _write_plugin(
        tmp_path,
        "vanishing",
        "class Plugin:\n"
        "    def register(self, host):\n"
        "        host.show_notification('old')\n",
    )
    manager = PluginManagerService(search_paths=[tmp_path])
    manager.discover_plugins()
    host = PluginHostContext()
    entered = threading.Event()
    release = threading.Event()
    original_notification = host.show_notification

    def blocked_notification(message, level="info"):
        entered.set()
        assert release.wait(2)
        return original_notification(message, level)

    host.show_notification = blocked_notification
    worker = threading.Thread(target=lambda: manager.load_plugin("vanishing", host))
    worker.start()
    assert entered.wait(2)
    _write_plugin(tmp_path, "vanishing", "class Plugin:\n    def register(self, host): pass\n")
    manager.discover_plugins()
    shutil.rmtree(tmp_path / "vanishing")
    manager.discover_plugins()
    release.set()
    worker.join(2)

    assert not worker.is_alive()
    assert manager.plugin_record("vanishing").plugin_instance is not None
    assert manager.unload_plugin("vanishing") is True
    assert manager.plugin_record("vanishing") is None


def test_shared_host_callback_gate_spans_manager_instances(tmp_path):
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    source = "class Plugin:\n    def register(self, host): host.show_notification('registered')\n"
    _write_plugin(first_root, "first", source)
    _write_plugin(second_root, "second", source)
    first = PluginManagerService(search_paths=[first_root])
    second = PluginManagerService(search_paths=[second_root])
    first.discover_plugins()
    second.discover_plugins()
    host = PluginHostContext()
    active = 0
    maximum = 0
    state_lock = threading.Lock()
    original_notification = host.show_notification

    def tracked_notification(message, level="info"):
        nonlocal active, maximum
        with state_lock:
            active += 1
            maximum = max(maximum, active)
        try:
            threading.Event().wait(0.05)
            return original_notification(message, level)
        finally:
            with state_lock:
                active -= 1

    host.show_notification = tracked_notification
    workers = [
        threading.Thread(target=lambda: first.load_plugin("first", host)),
        threading.Thread(target=lambda: second.load_plugin("second", host)),
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(2)

    assert all(not worker.is_alive() for worker in workers)
    assert maximum == 1
    assert sorted(note["plugin_id"] for note in host.notifications()) == ["first", "second"]


def test_unload_all_snapshots_records_under_manager_lock(monkeypatch):
    manager = PluginManagerService()
    manager._records = {
        "first": type("Record", (), {"plugin_id": "first", "plugin_instance": object()})(),
    }
    calls = []
    monkeypatch.setattr(manager, "unload_plugin", lambda plugin_id: calls.append(plugin_id) or True)
    completed = threading.Event()
    worker = threading.Thread(target=lambda: (manager.unload_all(), completed.set()))

    with manager._records_lock:
        worker.start()
        assert not completed.wait(0.1)
    worker.join(2)

    assert not worker.is_alive()
    assert calls == ["first"]


def test_rediscovery_during_disable_preserves_disabled_intent(tmp_path, monkeypatch):
    _write_plugin(tmp_path, "disable-refresh", "class Plugin:\n    def register(self, host): pass\n")
    manager = PluginManagerService(search_paths=[tmp_path])
    manager.discover_plugins()
    host = PluginHostContext()
    assert manager.load_plugin("disable-refresh", host).ok
    entered = threading.Event()
    release = threading.Event()
    original_unload = manager._unload_claimed_record

    def blocked_unload(record, plugin_id):
        entered.set()
        assert release.wait(2)
        return original_unload(record, plugin_id)

    monkeypatch.setattr(manager, "_unload_claimed_record", blocked_unload)
    worker = threading.Thread(target=lambda: manager.disable_plugin("disable-refresh"))
    worker.start()
    assert entered.wait(2)
    _write_plugin(tmp_path, "disable-refresh", "class Plugin:\n    def register(self, host): pass\n")
    manager.discover_plugins()
    release.set()
    worker.join(2)

    record = manager.plugin_record("disable-refresh")
    assert not worker.is_alive()
    assert record.plugin_instance is None
    assert record.enabled is False
    assert record.state == "disabled"


def test_latest_active_rediscovery_outcome_replaces_older_pending_on_unload(tmp_path):
    _write_plugin(
        tmp_path,
        "latest",
        "class Plugin:\n"
        "    def register(self, host):\n"
        "        host.show_notification('original')\n",
    )
    manager = PluginManagerService(search_paths=[tmp_path])
    manager.discover_plugins()
    host = PluginHostContext()
    assert manager.load_plugin("latest", host).ok

    _write_plugin(
        tmp_path,
        "latest",
        "class Plugin:\n"
        "    def register(self, host):\n"
        "        host.show_notification('pending-a')\n",
    )
    manager.discover_plugins()
    _write_plugin(
        tmp_path,
        "latest",
        "class Plugin:\n"
        "    def register(self, host):\n"
        "        host.show_notification('pending-b')\n",
    )
    manager.discover_plugins()

    assert manager.unload_plugin("latest") is True
    refreshed = manager.plugin_record("latest")
    assert refreshed.plugin_instance is None
    assert manager.load_plugin("latest", host).ok
    assert any(note["message"] == "pending-b" for note in host.notifications())
    assert not any(note["message"] == "pending-a" for note in host.notifications())

    # A later removal while the replacement is active supersedes pending-b.
    shutil.rmtree(tmp_path / "latest")
    manager.discover_plugins()
    assert manager.unload_plugin("latest") is True
    assert manager.plugin_record("latest") is None


def test_disable_persists_intent_before_releasing_transition(
    tmp_path, monkeypatch, isolated_plugin_settings,
):
    _write_plugin(tmp_path, "durable-disable", "class Plugin:\n    def register(self, host): pass\n")
    manager = PluginManagerService(search_paths=[tmp_path])
    manager.discover_plugins()
    host = PluginHostContext()
    assert manager.load_plugin("durable-disable", host).ok
    persisted = threading.Event()
    release_persist = threading.Event()
    original_persist = manager._persist_enabled_state_locked

    def blocked_persist():
        persisted.set()
        assert release_persist.wait(2)
        original_persist()

    monkeypatch.setattr(manager, "_persist_enabled_state_locked", blocked_persist)
    disabled = []
    worker = threading.Thread(target=lambda: disabled.append(manager.disable_plugin("durable-disable")))
    worker.start()
    assert persisted.wait(2)

    # Discovery cannot observe an enabled replacement while persistence and the
    # disable transition are still owned by the disabling thread.
    discovered = []
    discovery = threading.Thread(target=lambda: discovered.append(manager.discover_plugins()))
    discovery.start()
    assert discovery.is_alive()
    release_persist.set()
    worker.join(2)
    discovery.join(2)

    assert not worker.is_alive()
    assert not discovery.is_alive()
    assert disabled == [True]
    record = manager.plugin_record("durable-disable")
    assert record.enabled is False
    assert record.state == "disabled"
    assert "durable-disable" in manager._disabled_plugin_ids
    assert isolated_plugin_settings.data["plugin_disabled_ids"] == ["durable-disable"]


def test_late_older_discovery_scan_cannot_publish_over_newer_request(tmp_path, monkeypatch):
    _write_plugin(tmp_path, "revision", "class Plugin:\n    def register(self, host): pass\n")
    manager = PluginManagerService(search_paths=[tmp_path])
    manager.discover_plugins()
    first_scan_entered = threading.Event()
    release_first_scan = threading.Event()
    original_build = manager_module.build_plugin_record
    calls = 0
    calls_lock = threading.Lock()

    def blocked_build(path):
        nonlocal calls
        record = original_build(path)
        with calls_lock:
            calls += 1
            call_number = calls
        if call_number == 1:
            first_scan_entered.set()
            assert release_first_scan.wait(2)
        return record

    monkeypatch.setattr(manager_module, "build_plugin_record", blocked_build)
    older = threading.Thread(target=manager.discover_plugins)
    older.start()
    assert first_scan_entered.wait(2)

    _write_plugin(
        tmp_path,
        "revision",
        "class Plugin:\n"
        "    def register(self, host):\n"
        "        host.show_notification('newer')\n",
    )
    newer = threading.Thread(target=manager.discover_plugins)
    newer.start()
    newer.join(2)
    assert not newer.is_alive()
    release_first_scan.set()
    older.join(2)

    assert not older.is_alive()
    host = PluginHostContext()
    assert manager.load_plugin("revision", host).ok
    assert any(note["message"] == "newer" for note in host.notifications())
