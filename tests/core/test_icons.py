"""Tests for the semantic desktop icon registry."""
from PySide6.QtCore import QSize

from AssetsManager.core import icons


def test_icon_registry_contains_core_semantic_names():
    expected = {
        "settings", "share", "folder", "file", "copy", "qr_code", "image", "video",
        "archive", "cube", "close", "maximize", "minimize", "plus", "minus", "eye_off",
        "arrow_down", "check", "trash", "chevron_down",
    }
    assert expected.issubset(set(icons.names()))
    assert icons.normalize("gear") == "settings"
    assert icons.normalize("unknown", fallback="wrench") == "wrench"


def test_icon_renders_and_is_cached():
    first = icons.icon("settings", color="#ffffff", size=16)
    second = icons.icon("settings", color="#ffffff", size=16)

    assert not first.isNull()
    assert first is second
    assert first.actualSize(QSize(16, 16)).isValid()

    icons.clear_cache()
    refreshed = icons.icon("settings", color="#ffffff", size=16)
    assert refreshed is not first


def test_icon_unknown_name_uses_safe_fallback():
    result = icons.icon("not-a-real-icon", fallback="close", size=18)

    assert not result.isNull()
