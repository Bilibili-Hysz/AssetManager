"""Tests for plugin descriptor, loader, and host context."""
import json

import pytest

from AssetsManager.core.plugins.descriptor import (
    PLUGIN_STATE_DISABLED,
    PLUGIN_STATE_INVALID,
    PLUGIN_STATE_LOADABLE,
    build_plugin_record,
    load_manifest,
    parse_plugin_descriptor,
)
from AssetsManager.core.plugins.host_context import (
    PluginHostContext,
)
from AssetsManager.core.plugins.loader import PluginLoader


# ── load_manifest ────────────────────────────────────────────

def test_load_manifest_returns_payload(tmp_path):
    manifest = {"id": "test", "name": "Test", "version": "1.0", "entry": "main:Plugin"}
    path = tmp_path / "plugin.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    payload, diags = load_manifest(path)
    assert payload == manifest
    assert diags == []


def test_load_manifest_missing_file(tmp_path):
    payload, diags = load_manifest(tmp_path / "missing.json")
    assert payload is None
    assert len(diags) == 1
    assert diags[0].code == "manifest.missing"


def test_load_manifest_invalid_json(tmp_path):
    path = tmp_path / "plugin.json"
    path.write_text("{invalid", encoding="utf-8")

    payload, diags = load_manifest(path)
    assert payload is None
    assert diags[0].code == "manifest.invalid_json"


def test_load_manifest_not_object(tmp_path):
    path = tmp_path / "plugin.json"
    path.write_text('"hello"', encoding="utf-8")

    payload, diags = load_manifest(path)
    assert payload is None
    assert diags[0].code == "manifest.not_object"


# ── parse_plugin_descriptor ──────────────────────────────────

def test_parse_descriptor_valid():
    manifest = {"id": "test", "name": "Test", "version": "1.0", "entry": "main:Plugin"}
    desc, diags = parse_plugin_descriptor(manifest, manifest_path="/tmp/plugin.json")

    assert desc is not None
    assert desc.id == "test"
    assert desc.name == "Test"
    assert desc.version == "1.0"
    assert desc.entry == "main:Plugin"
    assert desc.kind == "command"
    assert desc.enabled_by_default is True
    assert diags == []


def test_parse_descriptor_optional_fields():
    manifest = {
        "id": "test", "name": "Test", "version": "1.0", "entry": "main:Plugin",
        "description": "A test plugin", "kind": "tool_window",
        "enabled_by_default": False,
    }
    desc, diags = parse_plugin_descriptor(manifest, manifest_path="/tmp/plugin.json")

    assert desc is not None
    assert desc.description == "A test plugin"
    assert desc.kind == "tool_window"
    assert desc.enabled_by_default is False


def test_parse_descriptor_missing_required_field():
    manifest = {"id": "test", "name": "Test"}
    desc, diags = parse_plugin_descriptor(manifest, manifest_path="/tmp/plugin.json")

    assert desc is None
    assert any(d.code == "manifest.required_field_missing" for d in diags)


def test_parse_descriptor_empty_id():
    manifest = {"id": "", "name": "Test", "version": "1.0", "entry": "main:Plugin"}
    desc, diags = parse_plugin_descriptor(manifest, manifest_path="/tmp/plugin.json")

    assert desc is None


# ── build_plugin_record ──────────────────────────────────────

def test_build_record_valid(tmp_path):
    manifest = {"id": "my.plugin", "name": "My Plugin", "version": "1.0", "entry": "main:Plugin"}
    path = tmp_path / "plugin.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    record = build_plugin_record(path)
    assert record.plugin_id == "my.plugin"
    assert record.state == PLUGIN_STATE_LOADABLE
    assert record.enabled is True
    assert record.descriptor is not None


def test_build_record_disabled(tmp_path):
    manifest = {
        "id": "my.plugin", "name": "My Plugin", "version": "1.0",
        "entry": "main:Plugin", "enabled_by_default": False,
    }
    path = tmp_path / "plugin.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    record = build_plugin_record(path)
    assert record.state == PLUGIN_STATE_DISABLED
    assert record.enabled is False


def test_build_record_missing_manifest(tmp_path):
    record = build_plugin_record(tmp_path / "missing.json")
    assert record.state == PLUGIN_STATE_INVALID
    assert record.enabled is False
    assert len(record.diagnostics) > 0


# ── PluginHostContext ────────────────────────────────────────

def test_host_context_register_command():
    ctx = PluginHostContext()
    ok = ctx.register_command({"id": "cmd1", "title": "Command 1"})
    assert ok is True
    assert len(ctx.commands()) == 1
    assert ctx.commands()[0].id == "cmd1"


def test_host_context_register_command_invalid():
    ctx = PluginHostContext()
    assert ctx.register_command({"id": "", "title": "Test"}) is False
    assert len(ctx.commands()) == 0


def test_host_context_register_menu_contribution():
    ctx = PluginHostContext()
    ok = ctx.register_menu_contribution({
        "id": "menu1", "menu_path": "tools", "command_id": "cmd1",
    })
    assert ok is True
    assert len(ctx.menu_contributions()) == 1
    assert ctx.menu_contributions("tools") == ctx.menu_contributions()
    assert ctx.menu_contributions("context") == []


def test_host_context_register_menu_invalid_path():
    ctx = PluginHostContext()
    ok = ctx.register_menu_contribution({
        "id": "menu1", "menu_path": "invalid", "command_id": "cmd1",
    })
    assert ok is False


def test_host_context_register_tool_window():
    ctx = PluginHostContext()

    def factory():
        return "widget"

    ok = ctx.register_tool_window({"id": "tw1", "title": "Tool Window", "singleton": True}, factory)
    assert ok is True
    assert len(ctx.tool_windows()) == 1


def test_host_context_register_tool_window_no_factory():
    ctx = PluginHostContext()
    ok = ctx.register_tool_window({"id": "tw1", "title": "TW", "singleton": True}, "not_callable")
    assert ok is False


def test_host_context_notification():
    ctx = PluginHostContext()
    ctx.show_notification("hello", "info")
    assert len(ctx.notifications()) == 1
    assert ctx.notifications()[0]["message"] == "hello"


def test_host_context_selected_paths():
    ctx = PluginHostContext(selected_paths=["/a", "/b"])
    assert ctx.get_selected_paths() == ["/a", "/b"]


# ── PluginLoader ─────────────────────────────────────────────

def test_loader_parse_entry():
    loader = PluginLoader()
    module, obj = loader.parse_entry("main:Plugin")
    assert module == "main"
    assert obj == "Plugin"


def test_loader_parse_entry_invalid():
    loader = PluginLoader()
    # Empty string is invalid
    with pytest.raises(ValueError):
        loader.parse_entry("")
    # Single word is allowed (function-based plugin)
    module_name, object_name = loader.parse_entry("parser")
    assert module_name == "parser"
    assert object_name == "__module__"


def test_loader_load_class(tmp_path):
    (tmp_path / "main.py").write_text(
        "class Plugin:\n"
        "    def register(self, ctx): pass\n",
        encoding="utf-8",
    )
    loader = PluginLoader()
    result = loader.load("test", tmp_path, "main:Plugin")
    assert result.plugin_instance is not None


def test_loader_load_missing_module(tmp_path):
    loader = PluginLoader()
    with pytest.raises(FileNotFoundError):
        loader.load("test", tmp_path, "missing:Plugin")


def test_loader_load_missing_class(tmp_path):
    (tmp_path / "main.py").write_text("# empty\n", encoding="utf-8")
    loader = PluginLoader()
    with pytest.raises(AttributeError):
        loader.load("test", tmp_path, "main:Missing")
