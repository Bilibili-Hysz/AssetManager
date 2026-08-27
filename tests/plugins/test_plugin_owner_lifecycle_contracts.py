"""Focused ownership and lifecycle contracts for plugin contributions."""
from __future__ import annotations

import json

import pytest

from AssetsManager.application import asset_filters
from AssetsManager.core import themes
from AssetsManager.core.format_utils import CATEGORY_MAP
from AssetsManager.core.plugins.host_context import PluginHostContext
from AssetsManager.core.plugins.manager import PluginManagerService
from AssetsManager.panels.file_list._common import EXT_TO_CATEGORY


@pytest.fixture(autouse=True)
def restore_global_registries():
    category_exts = {key: set(value) for key, value in asset_filters.FILTER_CATEGORY_EXTS.items()}
    category_labels = list(asset_filters.FILTER_CATEGORY_LABELS)
    filter_categories = dict(asset_filters.FILTER_CATEGORIES)
    category_map = dict(CATEGORY_MAP)
    theme_fallbacks = dict(themes._EXTENDED_FALLBACKS)
    theme_plugin_names = set(themes._PLUGIN_TOKEN_NAMES)
    theme_values = {name: dict(value) for name, value in themes._THEMES.items()}
    yield
    asset_filters.FILTER_CATEGORY_EXTS.clear()
    asset_filters.FILTER_CATEGORY_EXTS.update(category_exts)
    asset_filters.FILTER_CATEGORY_LABELS[:] = category_labels
    asset_filters.FILTER_CATEGORIES.clear()
    asset_filters.FILTER_CATEGORIES.update(filter_categories)
    CATEGORY_MAP.clear()
    CATEGORY_MAP.update(category_map)
    themes._EXTENDED_FALLBACKS.clear()
    themes._EXTENDED_FALLBACKS.update(theme_fallbacks)
    themes._PLUGIN_TOKEN_NAMES.clear()
    themes._PLUGIN_TOKEN_NAMES.update(theme_plugin_names)
    for name, value in theme_values.items():
        if name in themes._THEMES:
            themes._THEMES[name].clear()
            themes._THEMES[name].update(value)
    themes.invalidate_cache()


def _write_plugin(root, plugin_id, source, *, enabled=True):
    folder = root / plugin_id
    folder.mkdir()
    (folder / "plugin.json").write_text(
        json.dumps({
            "id": plugin_id,
            "name": plugin_id,
            "version": "1.0.0",
            "entry": "main:Plugin",
            "enabled_by_default": enabled,
            "permissions": ["settings.write"],
        }),
        encoding="utf-8",
    )
    (folder / "main.py").write_text(source, encoding="utf-8")
    return folder


def _manager_with_host(tmp_path, host):
    manager = PluginManagerService(search_paths=[tmp_path])
    manager.discover_plugins()
    manager._host_context = host
    host.set_apply_hooks(
        apply_categories=manager.apply_registered_categories,
        apply_theme_tokens=manager.apply_registered_theme_tokens,
    )
    return manager


def _grant(host, plugin_id):
    with host._host_identity():
        host.grant_permissions(plugin_id, {"settings.write"})


def test_category_contributions_are_live_and_revert_by_owner():
    from AssetsManager.application import plugin_service  # noqa: F401

    host = PluginHostContext()
    _grant(host, "first")
    _grant(host, "second")
    with host._host_identity_scope(host._registering_plugin_var, "first"):
        host.register_category("first", "shared.category", "First", {".shared"})
    with host._host_identity_scope(host._registering_plugin_var, "second"):
        host.register_category("second", "shared.category", "Second", {".shared", ".second"})

    manager = PluginManagerService()
    manager._host_context = host
    manager.apply_registered_categories()
    assert asset_filters.extension_matches_category(".second", "shared.category")
    assert CATEGORY_MAP[".shared"] == "shared.category"
    assert EXT_TO_CATEGORY.get(".second") == "shared.category"
    assert any(key == "shared.category" and label == "Second" for key, label in asset_filters.FILTER_CATEGORY_LABELS)

    with host._host_identity():
        host.unregister_plugin("second")
    manager.remove_registered_categories("second")
    assert asset_filters.FILTER_CATEGORY_EXTS["shared.category"] == {".shared"}
    assert CATEGORY_MAP[".shared"] == "shared.category"
    assert EXT_TO_CATEGORY.get(".second") is None
    assert asset_filters.FILTER_CATEGORY_EXTS["shared.category"] == {".shared"}


def test_theme_tokens_update_loaded_themes_and_restore_other_owner():
    host = PluginHostContext()
    _grant(host, "first")
    _grant(host, "second")
    with host._host_identity_scope(host._registering_plugin_var, "first"):
        host.register_theme_token("first", "owner.token", "#111111")
    with host._host_identity_scope(host._registering_plugin_var, "second"):
        host.register_theme_token("second", "owner.token", "#222222")

    manager = PluginManagerService()
    manager._host_context = host
    manager.apply_registered_theme_tokens()
    assert themes.color("owner.token") == "#222222"
    assert themes.get().get("owner.token") == "#222222"

    with host._host_identity():
        host.unregister_plugin("second")
    manager.remove_registered_theme_tokens("second")
    assert themes.color("owner.token") == "#111111"
    assert themes.get().get("owner.token") == "#111111"

    with host._host_identity():
        host.unregister_plugin("first")
    manager.remove_registered_theme_tokens("first")
    assert "owner.token" not in themes._EXTENDED_FALLBACKS
    assert "owner.token" not in themes.get()


def test_menu_contribution_has_owner_and_unload_only_removes_owner():
    host = PluginHostContext()
    with host.plugin_registration("first"):
        assert host.register_menu_contribution({
            "id": "first.menu", "menu_path": "tools", "command_id": "first.cmd",
        })
    with host.plugin_registration("second"):
        assert host.register_menu_contribution({
            "id": "second.menu", "menu_path": "tools", "command_id": "second.cmd",
        })
    assert {item.plugin_id for item in host.menu_contributions()} == {"first", "second"}
    with host._host_identity():
        host.unregister_plugin("first")
    assert [item.id for item in host.menu_contributions()] == ["second.menu"]


def test_enable_loads_through_current_host_and_rolls_back_on_failure(tmp_path):
    _write_plugin(tmp_path, "failing.enable", "class Plugin:\n    def register(self, host):\n        raise RuntimeError('boom')\n", enabled=False)
    host = PluginHostContext()
    manager = _manager_with_host(tmp_path, host)
    assert manager.plugin_record("failing.enable").state == "disabled"
    assert manager.enable_plugin("failing.enable") is False
    record = manager.plugin_record("failing.enable")
    assert record.enabled is False
    assert record.state == "disabled"
    assert manager._host_context is None


def test_load_is_idempotent_and_failed_load_can_rebind(tmp_path):
    _write_plugin(
        tmp_path,
        "repeatable",
        "class Plugin:\n    def register(self, host):\n        host.show_notification('loaded')\n",
    )
    manager = PluginManagerService(search_paths=[tmp_path])
    manager.discover_plugins()
    host = PluginHostContext()
    first = manager.load_plugin("repeatable", host)
    second = manager.load_plugin("repeatable", host)
    assert first.ok and second.ok
    assert manager.plugin_record("repeatable").plugin_instance is not None
    assert [n for n in host.notifications() if n["message"] == "loaded"] == [
        {"level": "info", "message": "loaded", "plugin_id": "repeatable"}
    ]

    failing = _write_plugin(
        tmp_path,
        "retryable",
        "class Plugin:\n    def register(self, host):\n        raise RuntimeError('retry')\n",
    )
    retry_manager = PluginManagerService(search_paths=[tmp_path])
    retry_manager.discover_plugins()
    first_host = PluginHostContext()
    assert not retry_manager.load_plugin("retryable", first_host).ok
    assert retry_manager._host_context is None
    (failing / "main.py").write_text("class Plugin:\n    def register(self, host):\n        pass\n", encoding="utf-8")
    second_host = PluginHostContext()
    assert retry_manager.load_plugin("retryable", second_host).ok
    assert retry_manager.plugin_record("retryable").host_context is second_host


def test_unload_all_attempts_every_loaded_plugin(monkeypatch):
    manager = PluginManagerService()
    manager._records = {
        "first": type("Record", (), {"plugin_id": "first", "plugin_instance": object()})(),
        "second": type("Record", (), {"plugin_id": "second", "plugin_instance": object()})(),
    }
    calls = []

    def unload(plugin_id):
        calls.append(plugin_id)
        return plugin_id != "first"

    monkeypatch.setattr(manager, "unload_plugin", unload)
    assert manager.unload_all() is False
    assert calls == ["first", "second"]
