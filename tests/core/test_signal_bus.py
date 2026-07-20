"""Tests for the presentation-only signal bus singleton."""
import ast
from pathlib import Path

from AssetsManager.core.signal_bus import get, _SignalBus


def test_singleton():
    a = get()
    b = get()
    assert a is b
    assert isinstance(a, _SignalBus)


def test_signals_are_limited_to_presentation_coordination():
    bus = get()
    expected = {
        "directory_changed",
        "file_focused",
        "refresh_requested",
        "theme_changed",
        "language_changed",
        "sidebar_depth_changed",
        "ui_scale_changed",
    }
    assert all(hasattr(bus, name) for name in expected)

    source = Path("AssetsManager/core/signal_bus.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    defined = {
        node.targets[0].id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "Signal"
    }
    assert defined == expected


def test_every_presentation_signal_has_a_producer_and_consumer_contract():
    root = Path(__file__).resolve().parents[2]

    contracts = {
        "directory_changed": (
            "AssetsManager/panels/file_list/_navigation.py",
            "bus().directory_changed.emit(",
            "AssetsManager/window.py",
            "b.directory_changed.connect(self._on_dir_selected)",
        ),
        "file_focused": (
            "AssetsManager/panels/file_list/_actions.py",
            "bus().file_focused.emit(",
            "AssetsManager/window.py",
            "b.file_focused.connect(self._on_file_focused_safe)",
        ),
        "refresh_requested": (
            "AssetsManager/panels/tag_tree.py",
            "bus().refresh_requested.emit()",
            "AssetsManager/panels/sidebar.py",
            "self._connect_bus(bus().refresh_requested, self._populate)",
        ),
        "theme_changed": (
            "AssetsManager/core/themes.py",
            "bus().theme_changed.emit(",
            "AssetsManager/window.py",
            "b.theme_changed.connect(",
        ),
        "language_changed": (
            "AssetsManager/i18n/__init__.py",
            "bus().language_changed.emit(",
            "AssetsManager/window.py",
            "b.language_changed.connect(self._refresh_language)",
        ),
        "sidebar_depth_changed": (
            "AssetsManager/panels/sidebar.py",
            "bus().sidebar_depth_changed.emit(",
            "AssetsManager/panels/info.py",
            "self._connect_bus(bus().sidebar_depth_changed, self._on_sidebar_depth_changed)",
        ),
        "ui_scale_changed": (
            "AssetsManager/dialogs/settings_dialog.py",
            "bus().ui_scale_changed.emit(",
            "AssetsManager/window.py",
            "b.ui_scale_changed.connect(self._on_ui_scale_changed)",
        ),
    }

    for signal, (publisher_path, emit, consumer_path, connect) in contracts.items():
        publisher = (root / publisher_path).read_text(encoding="utf-8")
        consumer = (root / consumer_path).read_text(encoding="utf-8")
        assert emit in publisher, f"{signal} is missing its presentation publisher"
        assert connect in consumer, f"{signal} is missing its presentation consumer"
