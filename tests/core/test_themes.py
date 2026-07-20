"""Tests for theme system."""
import pytest

from AssetsManager.core import themes


@pytest.fixture(autouse=True)
def _restore_theme():
    """Ensure global theme state is restored after each test."""
    yield
    themes.set_theme("Navy")


def test_all_themes():
    names = themes.names()
    assert len(names) >= 21  # May grow as themes are added
    # Dark themes
    assert "Navy" in names
    assert "Slate" in names
    assert "Forest" in names
    assert "Amber" in names
    assert "Dracula" in names
    assert "Nord" in names
    assert "Gruvbox" in names
    assert "Rose Pine" in names
    assert "Midnight" in names
    assert "Charcoal" in names
    assert "Espresso" in names
    # Light themes
    assert "Dawn" in names
    assert "Silver" in names
    assert "Mint" in names
    assert "Lavender" in names
    assert "Peach" in names
    assert "Sky" in names
    assert "Rose" in names
    assert "Sage" in names
    assert "Coral" in names
    assert "Lilac" in names


def test_get_theme():
    t = themes.get()
    assert "base" in t
    assert "accent" in t


def test_get_named_theme():
    t = themes.get("Forest")
    assert t["accent"] == "#40b870"


def test_set_theme():
    themes.set_theme("Slate")
    assert themes.get() == themes.get("Slate")


def test_invalid_theme():
    themes.set_theme("Slate")
    themes.set_theme("Bogus")
    assert themes.get() == themes.get("Slate")


def test_stylesheet():
    qss = themes.stylesheet()
    assert "QMainWindow" in qss
    assert "QDockWidget" in qss
    assert "QPushButton" in qss


def test_theme_mode_for_base():
    from AssetsManager.core.themes import theme_mode_for_base
    assert theme_mode_for_base("#1a1a1a") == "dark"
    assert theme_mode_for_base("#ffffff") == "light"
    assert theme_mode_for_base("#252525") == "dark"
    assert theme_mode_for_base("#f0f0f0") == "light"
    assert theme_mode_for_base("#808080") == "dark"  # exactly at boundary
    assert theme_mode_for_base("#888888") == "light"  # above boundary


def test_bg_type_default():
    assert themes.bg_type() == "image"


def test_bg_effect_defaults():
    from AssetsManager.core.settings import AppSettings
    s = AppSettings.instance()
    s._data.pop("bg_effect", None)
    s._data.pop("bg_effect_intensity", None)
    assert themes.bg_effect() == "none"
    assert themes.bg_effect_intensity() == 20
    s._data.pop("bg_effect", None)
    s._data.pop("bg_effect_intensity", None)


def test_background_numeric_settings_fall_back_when_invalid(monkeypatch):
    values = {
        "panel_opacity": None,
        "header_opacity": "invalid",
        "opacity": "0.75",
        "effect_intensity": None,
    }
    monkeypatch.setattr(themes, "_bg_setting", lambda key, default: values.get(key, default))

    assert themes.bg_panel_opacity() == 0.88
    assert themes.bg_header_opacity() == 1.0
    assert themes.bg_overall_opacity() == 0.75
    assert themes.bg_effect_intensity() == 20
