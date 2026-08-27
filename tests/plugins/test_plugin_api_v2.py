"""Stage-1 plugin API: live context, register_class, unified execute, legacy compat."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from AssetsManager.core.plugins.descriptor import (
    PERMISSION_HOST_SERVICES,
    PLUGIN_STATE_LOADABLE,
)
from AssetsManager.core.plugins.host_context import PluginHostContext
from AssetsManager.core.plugins.loader import PluginLoader
from AssetsManager.core.plugins.manager import PluginManagerService
from AssetsManager.plugin_api import (
    CategoryContributor,
    CommandOperator,
    FileParser,
    PluginContext,
    Preferences,
    ThemeTokenContributor,
)


class _FakeSession:
    def __init__(self, root: Path) -> None:
        self.context = type("Ctx", (), {"root": root})()


class _FakeFileList:
    def __init__(self) -> None:
        self._current = Path("C:/lib/browse")
        self._selection = [Path("C:/lib/browse/a.png")]

    def _selected_paths(self):
        return list(self._selection)


class _FakeInfo:
    _current_path = "C:/lib/browse/a.png"


class _FakeWindow:
    def __init__(self, root: Path) -> None:
        self._library_session = _FakeSession(root)
        self.file_list = _FakeFileList()
        self.info = _FakeInfo()
        self.services = object()
        self.refreshed = False

    def _scoped_services_for_session(self, session):
        assert session is self._library_session
        return self.services

    def _refresh_all(self):
        self.refreshed = True


def test_plugin_context_reads_live_window_state(tmp_path):
    host = PluginHostContext(
        current_root_path="/stale",
        selected_paths=["/old"],
        granted_permissions=frozenset({PERMISSION_HOST_SERVICES}),
    )
    window = _FakeWindow(tmp_path)
    host.bind_window(window)

    ctx = host.plugin_context()
    assert ctx.library_root == tmp_path
    assert ctx.current_directory == Path("C:/lib/browse")
    assert ctx.selected_paths == (Path("C:/lib/browse/a.png"),)
    assert ctx.focused_path == Path("C:/lib/browse/a.png")
    assert ctx.session is window._library_session
    assert ctx.services() is not None
    assert ctx.window is window

    window.file_list._selection = [Path("C:/lib/browse/b.png")]
    assert ctx.selected_paths == (Path("C:/lib/browse/b.png"),)


def test_plugin_context_falls_back_to_constructor_snapshot():
    host = PluginHostContext(current_root_path="/lib", selected_paths=["/lib/one"])
    ctx = PluginContext(host)
    assert ctx.library_root == Path("/lib")
    assert ctx.selected_paths == (Path("/lib/one"),)
    assert ctx.current_directory is None
    assert ctx.session is None


def test_register_class_operator_execute_receives_context():
    seen: list[tuple[str, ...]] = []

    class Ping(CommandOperator):
        id = "demo.ping"
        title = "Ping"
        menu_paths = ("tools",)

        def execute(self, ctx, params=None):
            seen.append(ctx.selected_paths)

    host = PluginHostContext(selected_paths=["/lib/kept.png"])
    with host.plugin_registration("demo"):
        assert host.register_class(Ping) is True

    commands = {cmd.id: cmd for cmd in host.commands()}
    assert "demo.ping" in commands
    assert any(item.command_id == "demo.ping" for item in host.menu_contributions("tools"))

    assert host.execute_command("demo.ping", extra_paths=("/lib/clicked.png",)) is True
    assert seen == [(Path("/lib/kept.png"), Path("/lib/clicked.png"))]


def test_legacy_handler_keeps_original_arity():
    calls: list[tuple] = []

    host = PluginHostContext(selected_paths=["/lib/kept.png"])
    host.register_command({"id": "legacy.cmd", "title": "Legacy"}, lambda path: calls.append(("one", path)), "legacy")
    assert host.execute_command("legacy.cmd", extra_paths=("/lib/clicked.png",)) is True
    assert calls == [("one", "/lib/clicked.png")]

    calls.clear()
    host.register_command({"id": "legacy.zero", "title": "Zero"}, lambda: calls.append(("zero",)), "legacy")
    assert host.execute_command("legacy.zero") is True
    assert calls == [("zero",)]


def test_parse_file_does_not_double_invoke_same_plugin(tmp_path):
    plugin_dir = tmp_path / "dual"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(
        '{"id":"dual","name":"Dual","version":"1.0","entry":"parser.py",'
        '"permissions":["filesystem.read"]}',
        encoding="utf-8",
    )
    (plugin_dir / "parser.py").write_text(
        "hits = {'n': 0}\n"
        "def match(path):\n"
        "    return path.endswith('.txt')\n"
        "def parse(path):\n"
        "    hits['n'] += 1\n"
        "    return {'from': 'instance'}\n"
        "def register(host):\n"
        "    host.register_file_handler('dual', match, parse)\n",
        encoding="utf-8",
    )

    PluginManagerService._instance = None
    manager = PluginManagerService(search_paths=[tmp_path])
    manager.discover_plugins()
    host = PluginHostContext()
    assert manager.load_plugin("dual", host).ok

    result = manager.parse_file("note.txt")
    assert result == {"dual": {"from": "instance"}}
    module = manager.plugin_record("dual").module
    assert module.hits["n"] == 1


def test_booth_link_legacy_parser_unchanged(tmp_path):
    addon = Path(__file__).resolve().parents[2] / "Plugins" / "Addons" / "booth_link"
    loader = PluginLoader()
    loaded = loader.load("booth_link", addon, "parser.py")

    sample = tmp_path / "_link"
    sample.mkdir()
    target = sample / "item.txt"
    target.write_text(
        "https://booth.pm/items/1\n\n商品名称: Cube\n作者: Artist\n商品ID: 1\n",
        encoding="utf-8",
    )

    instance = loaded.plugin_instance
    assert instance.match(str(target)) is True
    assert instance.parse(str(target)) == {
        "url": "https://booth.pm/items/1",
        "name": "Cube",
        "author": "Artist",
        "item_id": "1",
    }


def test_register_class_applies_category_and_theme_immediately():
    from AssetsManager.application.asset_filters import FILTER_CATEGORY_EXTS
    from AssetsManager.core.format_utils import CATEGORY_MAP
    from AssetsManager.core.themes import _EXTENDED_FALLBACKS

    class Cad(CategoryContributor):
        id = "stage2_cad"
        label = "Stage2 CAD"
        extensions = (".s2cad",)

    class Accent(ThemeTokenContributor):
        token = "stage2_accent"
        fallback = "#112233"

    PluginManagerService._instance = None
    manager = PluginManagerService(search_paths=[])
    host = PluginHostContext()
    manager.load_all_enabled(host)
    try:
        # Grants are host-side (manager manifest flow); a grant made inside
        # a plugin context is refused by the identity gate, and host-side
        # grants require the explicit host identity marker.
        with host._host_identity():
            host.grant_permissions("stage2", {"settings.write"})
        with host.plugin_registration("stage2"):
            assert host.register_class(Cad) is True
            assert host.register_class(Accent) is True

        assert "stage2_cad" in FILTER_CATEGORY_EXTS
        assert CATEGORY_MAP.get(".s2cad") == "stage2_cad"
        assert callable(_EXTENDED_FALLBACKS.get("stage2_accent"))
    finally:
        manager.remove_registered_categories("stage2")
        manager.remove_registered_theme_tokens("stage2")
        FILTER_CATEGORY_EXTS.pop("stage2_cad", None)
        CATEGORY_MAP.pop(".s2cad", None)
        _EXTENDED_FALLBACKS.pop("stage2_accent", None)


def test_manifest_permissions_are_granted_on_load(tmp_path):
    plugin_dir = tmp_path / "granted"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(
        '{"id":"granted","name":"Granted","version":"1.0",'
        '"entry":"main:Plugin","permissions":["filesystem.read"]}',
        encoding="utf-8",
    )
    (plugin_dir / "main.py").write_text(
        "class Plugin:\n"
        "    def register(self, host):\n"
        "        host.register_file_handler('granted', lambda p: False, lambda p: {})\n",
        encoding="utf-8",
    )
    PluginManagerService._instance = None
    manager = PluginManagerService(search_paths=[tmp_path])
    manager.discover_plugins()
    host = PluginHostContext()
    assert host.check_permission("filesystem.read") is False
    assert manager.load_plugin("granted", host).ok
    with host.plugin_registration("granted"):
        assert host.check_permission("filesystem.read") is True
    # The host itself and other plugins remain unprivileged.
    assert host.check_permission("filesystem.read") is False


def test_command_available_follows_poll():
    class NeedsSelection(CommandOperator):
        id = "demo.needs_sel"
        title = "Needs Selection"

        @classmethod
        def poll(cls, ctx):
            return bool(ctx.selected_paths)

        def execute(self, ctx, params=None):
            return None

    host = PluginHostContext()
    with host.plugin_registration("demo"):
        host.register_class(NeedsSelection)
    assert host.command_available("demo.needs_sel") is False
    assert host.execute_command("demo.needs_sel") is False
    assert host.command_available("demo.needs_sel", extra_paths=("/lib/a.png",)) is True


def test_preferences_persist_across_host_instances(tmp_path):
    from AssetsManager.core.plugins.preferences import set_prefs_root

    set_prefs_root(tmp_path / "plugin_prefs")
    try:
        class Prefs(Preferences):
            settings = {"keep_days": {"type": "int", "default": 7}}

        host = PluginHostContext()
        with host._host_identity():
            host.grant_permissions("tracker", {"settings.read", "settings.write"})
        with host.plugin_registration("tracker"):
            assert host.register_class(Prefs) is True
            bag = host.preferences("tracker")
            assert bag.get("keep_days") == 7
            bag.set("keep_days", 30)

        other = PluginHostContext()
        with other._host_identity():
            other.grant_permissions("tracker", {"settings.read", "settings.write"})
        with other.plugin_registration("tracker"):
            other.register_class(Prefs)
            assert other.preferences("tracker").get("keep_days") == 30
    finally:
        set_prefs_root(None)


def test_v2_file_parser_registers_once():
    class Notes(FileParser):
        id = "notes.parser"

        @classmethod
        def match(cls, ctx, file_path):
            return file_path.endswith(".md")

        def parse(self, ctx, file_path):
            return {"kind": "note", "name": Path(file_path).name}

    host = PluginHostContext()
    PluginManagerService._instance = None
    manager = PluginManagerService(search_paths=[])
    with host._host_identity():
        host.grant_permissions("notes", {"filesystem.read"})
    with host.plugin_registration("notes"):
        assert host.register_class(Notes) is True
    manager.load_all_enabled(host)
    assert manager.parse_file("readme.md") == {"notes": {"kind": "note", "name": "readme.md"}}
    assert manager.parse_file("image.png") == {}


def test_operator_defaults_and_prompt_cancel():
    seen: list[dict] = []
    prompted: list[dict] = []

    class Rename(CommandOperator):
        id = "demo.rename"
        title = "Rename"
        params = {
            "name": {"type": "str", "default": "untitled"},
            "force": {"type": "bool", "default": False},
        }

        def execute(self, ctx, params=None):
            seen.append(dict(params or {}))

    host = PluginHostContext()
    with host.plugin_registration("demo"):
        host.register_class(Rename)

    assert host.execute_command("demo.rename") is True
    assert seen == [{"name": "untitled", "force": False}]

    seen.clear()
    host.set_param_prompt(lambda cls, defaults: prompted.append(defaults) or None)
    assert host.execute_command("demo.rename") is False
    assert seen == []
    assert prompted == [{"name": "untitled", "force": False}]

    prompted.clear()
    assert host.execute_command("demo.rename", params={"name": "kept"}) is True
    assert prompted == []
    assert seen == [{"name": "kept", "force": False}]


def test_undoable_operator_records_execute_result():
    undone: list[dict] = []

    class Clear(CommandOperator):
        id = "demo.clear"
        title = "Clear"
        undoable = True

        def execute(self, ctx, params=None):
            if not (params or {}).get("confirm"):
                return False
            return {"previous": ["a"]}

        def undo(self, ctx, record):
            undone.append(record)

    host = PluginHostContext()
    with host.plugin_registration("demo"):
        host.register_class(Clear)

    assert host.execute_command("demo.clear") is True
    assert host.undo_last_command() is False

    assert host.execute_command("demo.clear", params={"confirm": True}) is True
    assert host.undo_last_command() is True
    assert undone == [{"previous": ["a"]}]
    assert host.undo_last_command() is False


def test_panel_contributor_registers_tool_window_area():
    from AssetsManager.plugin_api import PanelContributor

    class History(PanelContributor):
        id = "demo.history"
        title = "History"
        area = "bottom"

        def build(self, ctx):
            return "panel"

    host = PluginHostContext()
    with host.plugin_registration("demo"):
        assert host.register_class(History) is True
    windows = host.tool_windows()
    assert len(windows) == 1
    assert windows[0].id == "demo.history"
    assert windows[0].title == "History"
    assert windows[0].area == "bottom"
    assert windows[0].factory() == "panel"


def test_download_tracker_v2_example(tmp_path):
    from AssetsManager.core.plugins.preferences import set_prefs_root
    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import FileSystemChanged

    addon = Path(__file__).resolve().parents[2] / "Plugins" / "Addons" / "download_tracker"
    set_prefs_root(tmp_path / "plugin_prefs")
    PluginManagerService._instance = None
    manager = PluginManagerService(search_paths=[addon.parent])
    manager.discover_plugins()
    host = PluginHostContext()
    record = manager.plugin_record("download_tracker")
    assert record is not None
    record.enabled = True
    record.state = PLUGIN_STATE_LOADABLE
    try:
        assert manager.load_plugin("download_tracker", host).ok
        imported = str(tmp_path / "asset.png")
        get_event_bus().publish(FileSystemChanged(kind="import", paths=(imported,)))
        parsed = manager.parse_file(imported)
        assert parsed["download_tracker"]["download_count"] == "1"
        assert parsed["download_tracker"]["last_downloaded"]

        assert host.execute_command("download_tracker.clear", params={"confirm": True}) is True
        assert manager.parse_file(imported) == {}
        assert host.undo_last_command() is True
        restored = manager.parse_file(imported)
        assert restored["download_tracker"]["download_count"] == "1"
    finally:
        manager.unload_plugin("download_tracker")
        set_prefs_root(None)
        PluginManagerService._instance = None


def test_v2_command_collision_does_not_leave_orphan_registry_entry():
    class Operator(CommandOperator):
        id = "shared.command"
        title = "Operator"

        def execute(self, ctx, params=None):
            return None

    host = PluginHostContext()
    assert host.register_command(
        {"id": "shared.command", "title": "Legacy"}, lambda: None, "legacy"
    ) is True
    with host.plugin_registration("plugin"):
        assert host.register_class(Operator) is False
    assert "shared.command" not in host._v2_commands
    assert host.execute_command("shared.command") is True


def test_v2_parser_permission_failure_is_atomic():
    class Parser(FileParser):
        id = "blocked.parser"

        @classmethod
        def match(cls, ctx, file_path):
            return True

        def parse(self, ctx, file_path):
            return {"ok": "yes"}

    host = PluginHostContext()
    with host.plugin_registration("blocked"):
        assert host.register_class(Parser) is False
    assert "blocked.parser" not in host._v2_parsers
    assert host.file_handlers() == []


def test_permissions_are_isolated_per_plugin():
    host = PluginHostContext()
    with host._host_identity():
        host.grant_permissions("alpha", {"filesystem.read"})

    with host.plugin_registration("alpha"):
        assert host.check_permission("filesystem.read") is True
        host.register_file_handler("alpha", lambda p: False, lambda p: {})
    assert len(host.file_handlers()) == 1

    # beta declared nothing: alpha's grant must not leak into beta.
    with host.plugin_registration("beta"):
        assert host.check_permission("filesystem.read") is False
        host.register_file_handler("beta", lambda p: False, lambda p: {})
    assert len(host.file_handlers()) == 1

    # The host itself is not granted anything by a plugin manifest either.
    assert host.check_permission("filesystem.read") is False

    # Unloading alpha (host-side) revokes its grants.
    with host._host_identity():
        host.unregister_plugin("alpha")
    with host.plugin_registration("alpha"):
        assert host.check_permission("filesystem.read") is False


def test_services_requires_host_services_permission(tmp_path):
    meta = object()
    tags = object()
    plugin_svc = object()
    host = PluginHostContext()
    window = _FakeWindow(tmp_path)
    window.services = SimpleNamespace(
        metadata_service=meta,
        tag_service=tags,
        plugin_service=plugin_svc,
        sharing_services=SimpleNamespace(token_secret="SECRET"),
        session=object(),
    )
    host.bind_window(window)
    ctx = host.plugin_context()

    # Neither the host nor a plugin without the permission sees services.
    assert ctx.services() is None
    with host._host_identity():
        host.grant_permissions("reader", {"filesystem.read"})
    with host.plugin_registration("reader"):
        assert ctx.services() is None

    with host._host_identity():
        host.grant_permissions("reader", {"host.services"})
    with host.plugin_registration("reader"):
        view = ctx.services()
        assert view is not None
        assert view.metadata_service is meta
        assert view.tag_service is tags
        assert not hasattr(view, "plugin_service")
        assert not hasattr(view, "sharing_services")
        assert getattr(view, "token_secret", None) is None
        assert not hasattr(view, "session")


def test_session_requires_host_services_permission(tmp_path):
    host = PluginHostContext()
    window = _FakeWindow(tmp_path)
    host.bind_window(window)
    ctx = host.plugin_context()

    # Neither the host nor a plugin without the permission sees the session.
    assert ctx.session is None
    with host._host_identity():
        host.grant_permissions("reader", {"filesystem.read"})
    with host.plugin_registration("reader"):
        assert ctx.session is None

    with host._host_identity():
        host.grant_permissions("reader", {"host.services"})
    with host.plugin_registration("reader"):
        assert ctx.session is window._library_session


def test_window_requires_host_services_permission(tmp_path):
    host = PluginHostContext()
    window = _FakeWindow(tmp_path)
    host.bind_window(window)
    ctx = host.plugin_context()

    assert ctx.window is None
    with host._host_identity():
        host.grant_permissions("reader", {"filesystem.read"})
    with host.plugin_registration("reader"):
        assert ctx.window is None

    with host._host_identity():
        host.grant_permissions("reader", {"host.services"})
    with host.plugin_registration("reader"):
        assert ctx.window is window


def test_registration_blocked_without_permission(caplog):
    import logging

    host = PluginHostContext()
    with caplog.at_level(logging.WARNING):
        with host.plugin_registration("bare"):
            host.register_file_handler("bare", lambda p: False, lambda p: {})
            host.register_category("bare", "cat", "Cat", {".x"})
            host.register_theme_token("bare", "token", "#fff")
            host.register_search_provider("bare", "sp", "SP", lambda q, r: [])
    assert len(host.file_handlers()) == 0
    assert len(host.categories()) == 0
    assert len(host.theme_tokens()) == 0
    assert len(host.search_providers()) == 0
    assert "without permission" in caplog.text


def test_registration_allowed_with_declared_permissions():
    host = PluginHostContext()
    with host._host_identity():
        host.grant_permissions("full", {"filesystem.read", "settings.write"})
    with host.plugin_registration("full"):
        host.register_file_handler("full", lambda p: False, lambda p: {})
        host.register_category("full", "cat", "Cat", {".x"})
        host.register_theme_token("full", "token", "#fff")
        host.register_search_provider("full", "sp", "SP", lambda q, r: [])
    assert len(host.file_handlers()) == 1
    assert len(host.categories()) == 1
    assert len(host.theme_tokens()) == 1
    assert len(host.search_providers()) == 1


def test_legacy_handler_internal_typeerror_not_retried():
    calls: list[str] = []

    def failing(path: str) -> None:
        calls.append(path)
        raise TypeError("boom")

    host = PluginHostContext()
    host.register_command({"id": "legacy.fail", "title": "Fail"}, failing, "legacy")
    with pytest.raises(TypeError, match="boom"):
        host.execute_command("legacy.fail", extra_paths=("/lib/a.png",))
    assert calls == ["/lib/a.png"]


def test_zero_arg_handler_internal_typeerror_propagates():
    calls: list[str] = []

    def failing() -> None:
        calls.append("called")
        raise TypeError("boom")

    host = PluginHostContext()
    host.register_command({"id": "legacy.fail0", "title": "Fail0"}, failing, "legacy")
    with pytest.raises(TypeError, match="boom"):
        host.execute_command("legacy.fail0", extra_paths=("/lib/a.png",))
    assert calls == ["called"]
