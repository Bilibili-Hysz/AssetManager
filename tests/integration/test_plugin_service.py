"""Tests for PluginService."""
import json
from unittest.mock import Mock

import pytest

from AssetsManager.application.plugin_service import PluginService
from AssetsManager.core.plugins import PluginManagerService


def _make_plugin(tmp_path, plugin_id="test.plugin", enabled=True):
    plugin_dir = tmp_path / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": plugin_id,
        "name": f"Test Plugin {plugin_id}",
        "version": "1.0.0",
        "entry": "main:Plugin",
        "enabled_by_default": enabled,
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    (plugin_dir / "main.py").write_text(
        "class Plugin:\n"
        "    def register(self, ctx): pass\n"
        "    def unregister(self, ctx): pass\n",
        encoding="utf-8",
    )
    return plugin_dir


def test_discover_finds_plugins(tmp_path):
    _make_plugin(tmp_path, "alpha")
    _make_plugin(tmp_path, "beta")

    PluginManagerService._instance = None
    svc = PluginService(PluginManagerService(search_paths=[tmp_path]))
    descriptors = svc.discover()

    ids = {d.id for d in descriptors}
    assert "alpha" in ids
    assert "beta" in ids


def test_list_plugins_returns_discovered(tmp_path):
    _make_plugin(tmp_path, "my.plugin")

    PluginManagerService._instance = None
    svc = PluginService(PluginManagerService(search_paths=[tmp_path]))
    svc.discover()

    plugins = svc.list_plugins()
    assert len(plugins) == 1
    assert plugins[0].id == "my.plugin"


def test_enable_disable_plugin(tmp_path):
    _make_plugin(tmp_path, "toggle.plugin", enabled=False)

    PluginManagerService._instance = None
    svc = PluginService(PluginManagerService(search_paths=[tmp_path]))
    svc.discover()

    assert svc.enable("toggle.plugin") is True
    record = svc._manager.plugin_record("toggle.plugin")
    assert record.enabled is True

    assert svc.disable("toggle.plugin") is True
    record = svc._manager.plugin_record("toggle.plugin")
    assert record.enabled is False


def test_load_plugin(tmp_path):
    _make_plugin(tmp_path, "loadable.plugin")

    PluginManagerService._instance = None
    svc = PluginService(PluginManagerService(search_paths=[tmp_path]))
    svc.discover()

    from AssetsManager.core.plugins import PluginHostContext
    ctx = PluginHostContext()
    result = svc.load("loadable.plugin", ctx)

    assert result.ok
    assert result.state == "active"


def test_unload_plugin(tmp_path):
    _make_plugin(tmp_path, "unloadable.plugin")

    PluginManagerService._instance = None
    svc = PluginService(PluginManagerService(search_paths=[tmp_path]))
    svc.discover()

    from AssetsManager.core.plugins import PluginHostContext
    ctx = PluginHostContext()
    svc.load("unloadable.plugin", ctx)

    assert svc.unload("unloadable.plugin") is True
    record = svc._manager.plugin_record("unloadable.plugin")
    assert record.state == "loadable"


def test_failed_plugin_register_cleans_event_hook(tmp_path):
    from AssetsManager.core.plugins import PluginHostContext
    plugin_dir = _make_plugin(tmp_path, "failing.register")
    (plugin_dir / "main.py").write_text(
        "from AssetsManager.domain.events import FileCreated\n"
        "class Plugin:\n"
        "    def register(self, ctx):\n"
        "        ctx.hook(FileCreated, lambda event: None)\n"
        "        raise RuntimeError('register failed')\n",
        encoding="utf-8",
    )
    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import FileCreated

    manager = PluginManagerService(search_paths=[tmp_path])
    manager.discover_plugins()
    result = manager.load_plugin("failing.register", PluginHostContext())

    assert result.ok is False
    assert get_event_bus().handler_count(FileCreated) == 0


def test_failed_plugin_unregister_still_cleans_event_hook(tmp_path):
    from AssetsManager.core.plugins import PluginHostContext
    plugin_dir = _make_plugin(tmp_path, "failing.unregister")
    (plugin_dir / "main.py").write_text(
        "from AssetsManager.domain.events import FileCreated\n"
        "class Plugin:\n"
        "    def register(self, ctx):\n"
        "        ctx.hook(FileCreated, lambda event: None)\n"
        "    def unregister(self, ctx):\n"
        "        raise RuntimeError('unregister failed')\n",
        encoding="utf-8",
    )
    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import FileCreated

    manager = PluginManagerService(search_paths=[tmp_path])
    manager.discover_plugins()
    context = PluginHostContext()
    assert manager.load_plugin("failing.unregister", context).ok
    assert get_event_bus().handler_count(FileCreated) == 1

    assert manager.unload_plugin("failing.unregister") is False
    assert get_event_bus().handler_count(FileCreated) == 0


def test_failed_host_cleanup_still_completes_plugin_unload(tmp_path, monkeypatch):
    from AssetsManager.core.plugins import PluginHostContext
    from AssetsManager.core.plugins import PLUGIN_STATE_LOADABLE

    _make_plugin(tmp_path, "failing.host_cleanup")
    manager = PluginManagerService(search_paths=[tmp_path])
    manager.discover_plugins()
    context = PluginHostContext()
    assert manager.load_plugin("failing.host_cleanup", context).ok

    def fail_unregister(_plugin_id):
        raise RuntimeError("subscription close failed")

    remove_categories = Mock(wraps=manager.remove_registered_categories)
    remove_theme_tokens = Mock(wraps=manager.remove_registered_theme_tokens)
    monkeypatch.setattr(manager, "remove_registered_categories", remove_categories)
    monkeypatch.setattr(manager, "remove_registered_theme_tokens", remove_theme_tokens)
    monkeypatch.setattr(context, "unregister_plugin", fail_unregister)

    assert manager.unload_plugin("failing.host_cleanup") is True
    remove_categories.assert_called_once_with("failing.host_cleanup")
    remove_theme_tokens.assert_called_once_with("failing.host_cleanup")
    record = manager.plugin_record("failing.host_cleanup")
    assert record is not None
    assert record.state == PLUGIN_STATE_LOADABLE
    assert record.module is None
    assert record.plugin_instance is None
    assert record.host_context is None


def test_load_nonexistent_plugin_returns_error(tmp_path):
    PluginManagerService._instance = None
    svc = PluginService(PluginManagerService(search_paths=[tmp_path]))

    result = svc.load("does.not.exist")
    assert not result.ok


def test_discover_empty_directory(tmp_path):
    PluginManagerService._instance = None
    svc = PluginService(PluginManagerService(search_paths=[tmp_path]))
    descriptors = svc.discover()
    assert descriptors == []


def test_register_file_handler_and_parse(tmp_path):
    from AssetsManager.core.plugins.host_context import PluginHostContext

    PluginManagerService._instance = None
    manager = PluginManagerService(search_paths=[tmp_path])
    ctx = PluginHostContext()

    # Register a file handler via host context
    def match(path: str) -> bool:
        return path.endswith(".fbx")

    def parse(path: str) -> dict:
        return {"format": "fbx", "vertices": "1000"}

    ctx.register_file_handler("model_analyzer", match, parse)

    # Load plugins (empty directory) with host context
    manager.load_all_enabled(ctx)

    # parse_file should use the registered handler
    result = manager.parse_file("scene.fbx")
    assert "model_analyzer" in result
    assert result["model_analyzer"]["format"] == "fbx"

    # Non-matching file should not trigger handler
    result = manager.parse_file("image.png")
    assert "model_analyzer" not in result


def test_register_file_handler_with_invalid_callables():
    from AssetsManager.core.plugins.host_context import PluginHostContext

    ctx = PluginHostContext()
    # Should not raise, just log warning
    ctx.register_file_handler("bad", "not_callable", "also_not_callable")  # type: ignore[arg-type]
    assert len(ctx.file_handlers()) == 0


def test_hook_registers_event_handler():
    from AssetsManager.core.plugins.host_context import PluginHostContext
    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import FileCreated

    ctx = PluginHostContext()
    calls = []

    def on_created(event):
        calls.append(event)

    ctx.hook(FileCreated, on_created)
    hooks = ctx.event_hooks()
    assert FileCreated in hooks
    assert len(hooks[FileCreated]) == 1

    get_event_bus().publish(FileCreated(path="/asset.txt"))
    assert len(calls) == 1


def test_unregister_plugin_keeps_shared_handler_owned_by_another_plugin():
    from AssetsManager.core.plugins.host_context import PluginHostContext
    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import FileCreated

    ctx = PluginHostContext()
    calls = []

    def on_created(event):
        calls.append(event)

    ctx.hook(FileCreated, on_created, plugin_id="plugin_a")
    ctx.hook(FileCreated, on_created, plugin_id="plugin_b")
    ctx.unregister_plugin("plugin_a")

    get_event_bus().publish(FileCreated(path="/asset.txt"))
    assert len(calls) == 1
    assert calls[0].path == "/asset.txt"
    assert get_event_bus().handler_count(FileCreated) == 1


def test_plugin_registration_assigns_default_hook_ownership(tmp_path):
    from AssetsManager.core.plugins import PluginHostContext
    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import FileCreated

    plugin_dir = _make_plugin(tmp_path, "implicit.owner")
    (plugin_dir / "main.py").write_text(
        "from AssetsManager.domain.events import FileCreated\n"
        "class Plugin:\n"
        "    def register(self, ctx):\n"
        "        ctx.hook(FileCreated, lambda event: None)\n",
        encoding="utf-8",
    )
    manager = PluginManagerService(search_paths=[tmp_path])
    manager.discover_plugins()
    context = PluginHostContext()

    assert manager.load_plugin("implicit.owner", context).ok
    assert get_event_bus().handler_count(FileCreated) == 1
    assert manager.unload_plugin(" implicit.owner ")
    assert get_event_bus().handler_count(FileCreated) == 0


def test_hook_rejects_non_domain_event_type():
    from AssetsManager.core.plugins.host_context import PluginHostContext

    with pytest.raises(TypeError, match="DomainEvent subclass"):
        PluginHostContext().hook("ThemeChanged", lambda _event: None)  # type: ignore[arg-type]


def test_register_category():
    from AssetsManager.core.plugins.host_context import PluginHostContext

    ctx = PluginHostContext()
    ctx.register_category("cad_plugin", "cad", "CAD Files", {".dwg", ".dxf"})

    cats = ctx.categories()
    assert len(cats) == 1
    assert cats[0].key == "cad"
    assert cats[0].label == "CAD Files"
    assert ".dwg" in cats[0].extensions


def test_apply_registered_categories(tmp_path):
    from AssetsManager.core.plugins.host_context import PluginHostContext
    from AssetsManager.application.asset_filters import FILTER_CATEGORY_EXTS
    from AssetsManager.core.format_utils import CATEGORY_MAP

    PluginManagerService._instance = None
    manager = PluginManagerService(search_paths=[tmp_path])
    ctx = PluginHostContext()

    ctx.register_category("cad_plugin", "test_cad_cat", "Test CAD", {".testext"})
    manager.load_all_enabled(ctx)
    manager.apply_registered_categories()

    assert "test_cad_cat" in FILTER_CATEGORY_EXTS
    assert ".testext" in FILTER_CATEGORY_EXTS["test_cad_cat"]
    assert CATEGORY_MAP.get(".testext") == "test_cad_cat"


def test_register_column():
    from AssetsManager.core.plugins.host_context import PluginHostContext

    ctx = PluginHostContext()
    ctx.register_column("meta_plugin", "file_format", "Format", width=80, order=10)
    ctx.register_column("meta_plugin", "color_space", "Color Space", width=100, order=20)

    cols = ctx.columns()
    assert len(cols) == 2
    assert cols[0].key == "file_format"
    assert cols[0].label == "Format"
    assert cols[0].width == 80
    assert cols[0].order == 10
    assert cols[1].key == "color_space"


def test_register_column_invalid():
    from AssetsManager.core.plugins.host_context import PluginHostContext

    ctx = PluginHostContext()
    ctx.register_column("p", "", "Label")
    assert len(ctx.columns()) == 0


def test_register_search_provider():
    from AssetsManager.core.plugins.host_context import PluginHostContext

    def search(query: str, library_root: str) -> list[dict]:
        return [{"name": f"result_{query}", "path": "/fake"}]

    ctx = PluginHostContext()
    ctx.register_search_provider("search_plugin", "fulltext", "Full Text", search)

    providers = ctx.search_providers()
    assert len(providers) == 1
    assert providers[0].id == "fulltext"
    assert providers[0].label == "Full Text"
    result = providers[0].search("test", "/lib")
    assert result[0]["name"] == "result_test"


def test_register_search_provider_invalid():
    from AssetsManager.core.plugins.host_context import PluginHostContext

    ctx = PluginHostContext()
    ctx.register_search_provider("p", "", "Label", lambda q, r: [])
    assert len(ctx.search_providers()) == 0


def test_register_theme_token():
    from AssetsManager.core.plugins.host_context import PluginHostContext

    ctx = PluginHostContext()
    ctx.register_theme_token("theme_plugin", "plugin.accent", "#ff00ff")

    tokens = ctx.theme_tokens()
    assert len(tokens) == 1
    assert tokens[0].token == "plugin.accent"
    assert tokens[0].fallback == "#ff00ff"


def test_apply_registered_theme_tokens(tmp_path):
    from AssetsManager.core.plugins.host_context import PluginHostContext
    from AssetsManager.core.themes import _EXTENDED_FALLBACKS

    PluginManagerService._instance = None
    manager = PluginManagerService(search_paths=[tmp_path])
    ctx = PluginHostContext()

    ctx.register_theme_token("theme_plugin", "test_custom_token", "#abc123")
    manager.load_all_enabled(ctx)
    manager.apply_registered_theme_tokens()

    fallback_fn = _EXTENDED_FALLBACKS.get("test_custom_token")
    assert callable(fallback_fn)
    assert fallback_fn({}) == "#abc123"


def test_permissions_in_manifest(tmp_path):
    manifest = {
        "id": "secure_plugin",
        "name": "Secure Plugin",
        "version": "1.0.0",
        "permissions": ["filesystem.read", "network.request", "unknown.perm"],
    }
    manifest_path = tmp_path / "plugin.json"
    manifest_path.write_text(
        __import__("json").dumps(manifest), encoding="utf-8"
    )
    from AssetsManager.core.plugins.descriptor import parse_plugin_descriptor
    descriptor, _ = parse_plugin_descriptor(manifest, manifest_path=manifest_path)
    assert descriptor is not None
    assert "filesystem.read" in descriptor.permissions
    assert "network.request" in descriptor.permissions
    assert "unknown.perm" in descriptor.permissions
    assert len(descriptor.permissions) == 3


def test_check_permission():
    from AssetsManager.core.plugins.host_context import PluginHostContext
    from AssetsManager.core.plugins.descriptor import PERMISSION_FILESYSTEM_READ, PERMISSION_NETWORK_REQUEST

    ctx = PluginHostContext(granted_permissions=frozenset({PERMISSION_FILESYSTEM_READ}))
    assert ctx.check_permission(PERMISSION_FILESYSTEM_READ) is True
    assert ctx.check_permission(PERMISSION_NETWORK_REQUEST) is False
    assert ctx.check_permission("unknown.perm") is False


def test_check_permission_default_none():
    from AssetsManager.core.plugins.host_context import PluginHostContext
    from AssetsManager.core.plugins.descriptor import PERMISSION_FILESYSTEM_READ

    ctx = PluginHostContext()
    assert ctx.check_permission(PERMISSION_FILESYSTEM_READ) is False


def test_check_permission_warns_but_never_blocks(caplog):
    """Permissions are advisory: registration succeeds even without them."""
    import logging
    from AssetsManager.core.plugins.host_context import PluginHostContext
    from AssetsManager.core.plugins.descriptor import PERMISSION_FILESYSTEM_READ

    ctx = PluginHostContext()
    assert ctx.check_permission(PERMISSION_FILESYSTEM_READ) is False

    with caplog.at_level(logging.WARNING):
        assert len(ctx.categories()) == 0
        ctx.register_category("test_pid", "test_cat", "Test", {".test"})
        assert len(ctx.categories()) == 1  # registered despite no permission
        assert "without permission" in caplog.text


def test_unload_cleans_host_contributions(tmp_path):
    """Verify that unload_plugin removes all host context contributions."""
    from AssetsManager.core.plugins.host_context import PluginHostContext

    PluginManagerService._instance = None
    PluginManagerService(search_paths=[tmp_path])
    ctx = PluginHostContext()

    # Register contributions for a plugin
    ctx.register_command({"id": "cmd1", "title": "Test"}, plugin_id="test_plugin")
    ctx.register_context_menu_item("test_plugin", "item1", "Label", "cmd1")
    ctx.register_category("test_plugin", "test_cat", "Test", {".test"})
    ctx.register_column("test_plugin", "col1", "Col")
    ctx.register_search_provider("test_plugin", "sp1", "SP", lambda q, r: [])
    ctx.register_theme_token("test_plugin", "tok", "#fff")

    assert len(ctx.commands()) == 1
    assert len(ctx.context_menu_items()) == 1
    assert len(ctx.categories()) == 1
    assert len(ctx.columns()) == 1
    assert len(ctx.search_providers()) == 1
    assert len(ctx.theme_tokens()) == 1

    # Unregister should remove all
    ctx.unregister_plugin("test_plugin")

    assert len(ctx.commands()) == 0
    assert len(ctx.context_menu_items()) == 0
    assert len(ctx.categories()) == 0
    assert len(ctx.columns()) == 0
    assert len(ctx.search_providers()) == 0
    assert len(ctx.theme_tokens()) == 0


def test_unload_preserves_other_plugins(tmp_path):
    """Verify that unregister_plugin only removes contributions from the target plugin."""
    from AssetsManager.core.plugins.host_context import PluginHostContext

    ctx = PluginHostContext()

    ctx.register_command({"id": "cmd_a", "title": "A"}, plugin_id="plugin_a")
    ctx.register_command({"id": "cmd_b", "title": "B"}, plugin_id="plugin_b")
    ctx.register_context_menu_item("plugin_a", "item_a", "A Item", "cmd_a")
    ctx.register_context_menu_item("plugin_b", "item_b", "B Item", "cmd_b")

    ctx.unregister_plugin("plugin_a")

    assert len(ctx.commands()) == 1
    assert ctx.commands()[0].id == "cmd_b"
    assert len(ctx.context_menu_items()) == 1
    assert ctx.context_menu_items()[0].id == "item_b"


def test_unload_cleans_event_hooks():
    """Verify that unregister_plugin removes event hooks by plugin_id."""
    from AssetsManager.core.plugins.host_context import PluginHostContext
    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import FileCreated

    ctx = PluginHostContext()

    def handler_a(event):
        pass

    def handler_b(event):
        pass

    ctx.hook(FileCreated, handler_a, plugin_id="plugin_a")
    ctx.hook(FileCreated, handler_b, plugin_id="plugin_b")

    hooks = ctx.event_hooks()
    assert len(hooks[FileCreated]) == 2

    ctx.unregister_plugin("plugin_a")

    hooks = ctx.event_hooks()
    assert len(hooks[FileCreated]) == 1
    _, pid = hooks[FileCreated][0]
    assert pid == "plugin_b"
    assert get_event_bus().handler_count(FileCreated) == 1


def test_unload_keeps_shared_handler_owned_by_other_plugin():
    """Each hook must have its own EventBus subscription token."""
    from AssetsManager.core.plugins.host_context import PluginHostContext
    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import FileCreated

    ctx = PluginHostContext()
    calls = []

    def handler(event):
        calls.append(event)

    ctx.hook(FileCreated, handler, plugin_id="plugin_a")
    ctx.hook(FileCreated, handler, plugin_id="plugin_b")
    ctx.unregister_plugin("plugin_a")

    get_event_bus().publish(FileCreated(path="/asset.txt"))

    assert len(calls) == 1
    assert get_event_bus().handler_count(FileCreated) == 1


def test_unload_normalizes_plugin_id_for_hook_cleanup(tmp_path):
    from AssetsManager.core.plugins.host_context import PluginHostContext
    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import FileCreated

    plugin_dir = _make_plugin(tmp_path, "normalized.plugin")
    (plugin_dir / "main.py").write_text(
        "from AssetsManager.domain.events import FileCreated\n"
        "class Plugin:\n"
        "    def register(self, ctx): ctx.hook(FileCreated, lambda event: None)\n",
        encoding="utf-8",
    )
    manager = PluginManagerService(search_paths=[tmp_path])
    manager.discover_plugins()
    assert manager.load_plugin("normalized.plugin", PluginHostContext()).ok

    assert manager.unload_plugin(" normalized.plugin ") is True
    assert get_event_bus().handler_count(FileCreated) == 0


def test_unload_cleans_tool_windows():
    """Verify that unregister_plugin removes tool windows by plugin_id."""
    from AssetsManager.core.plugins.host_context import PluginHostContext

    ctx = PluginHostContext()

    ctx.register_tool_window({"id": "tw_a", "title": "A"}, lambda: None, plugin_id="plugin_a")
    ctx.register_tool_window({"id": "tw_b", "title": "B"}, lambda: None, plugin_id="plugin_b")

    assert len(ctx.tool_windows()) == 2

    ctx.unregister_plugin("plugin_a")

    assert len(ctx.tool_windows()) == 1
    assert ctx.tool_windows()[0].id == "tw_b"


def test_unload_cleans_global_category_mutations(tmp_path):
    """Verify that disabling a plugin removes its global category registrations."""
    from AssetsManager.core.plugins.host_context import PluginHostContext
    from AssetsManager.application.asset_filters import FILTER_CATEGORY_EXTS
    from AssetsManager.core.format_utils import CATEGORY_MAP

    PluginManagerService._instance = None
    pm = PluginManagerService(search_paths=[tmp_path])
    ctx = PluginHostContext()
    pm._host_context = ctx

    # Register a category
    ctx.register_category("test_plugin", "test_cat", "Test", {".test_ext"})
    pm.apply_registered_categories()

    assert "test_cat" in FILTER_CATEGORY_EXTS
    assert ".test_ext" in CATEGORY_MAP
    assert CATEGORY_MAP[".test_ext"] == "test_cat"

    # Unregister should clean global mutations
    ctx.unregister_plugin("test_plugin")
    pm.remove_registered_categories("test_plugin")

    assert "test_cat" not in FILTER_CATEGORY_EXTS
    assert ".test_ext" not in CATEGORY_MAP


def test_unload_cleans_global_theme_token_mutations():
    """Verify that disabling a plugin removes its global theme token registrations."""
    from AssetsManager.core.plugins.host_context import PluginHostContext
    from AssetsManager.core.themes import _EXTENDED_FALLBACKS

    PluginManagerService._instance = None
    pm = PluginManagerService()
    ctx = PluginHostContext()
    pm._host_context = ctx

    # Register a theme token
    ctx.register_theme_token("test_plugin", "test_token", "#abc")
    pm.apply_registered_theme_tokens()

    assert "test_token" in _EXTENDED_FALLBACKS

    # Unregister should clean global mutations
    ctx.unregister_plugin("test_plugin")
    pm.remove_registered_theme_tokens("test_plugin")

    assert "test_token" not in _EXTENDED_FALLBACKS
