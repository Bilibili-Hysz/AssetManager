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


def test_builtin_filename_prefix_matches_dark_flag():
    """D_ themes must be dark and L_ themes light so grouping is unambiguous."""
    import json
    from AssetsManager.core.path_resolver import themes_dir

    for path in sorted(themes_dir().glob("D_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data.get("dark") is True, f"{path.name}: expected dark: true"

    for path in sorted(themes_dir().glob("L_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data.get("dark") is False, f"{path.name}: expected dark: false"


def test_bundled_mint_theme_groups_as_light():
    """Regression: Mint is light, so it must live under the L_ prefix."""
    from AssetsManager.core.theme_loader import ThemeLoader
    from AssetsManager.core.path_resolver import themes_dir

    loader = ThemeLoader(themes_dir=str(themes_dir()))
    loader.scan_directory()
    groups = loader.list_themes()

    light_names = [t["name"] for t in groups["Light"]]
    dark_names = [t["name"] for t in groups["Dark"]]
    assert "Mint" in light_names
    assert "Mint" not in dark_names


def test_get_theme():
    t = themes.get()
    assert "base" in t
    assert "accent" in t


def test_get_named_theme():
    t = themes.get("Forest")
    assert t["accent"] == "#40b870"


def test_selectable_themes_meet_text_contrast_contract():
    from AssetsManager.core.color_utils import contrast_ratio

    checks = (
        ("heading", "base", 4.5),
        ("heading", "panel", 4.5),
        ("body", "base", 4.5),
        ("body", "panel", 4.5),
        ("muted", "base", 3.0),
        ("muted", "panel", 3.0),
        ("on_accent", "accent", 4.5),
    )
    for name in themes.names():
        palette = themes.get(name)
        for foreground, background, threshold in checks:
            assert contrast_ratio(palette[foreground], palette[background]) >= threshold, (
                f"{name}: {foreground}/{background} contrast is below {threshold}:1"
            )


def test_selectable_themes_meet_extended_contrast_contract():
    """Input/tooltip text stays readable and scrollbars meet WCAG non-text 3:1."""
    from AssetsManager.core.color_utils import contrast_ratio

    checks = (
        ("input_text", "input_bg", 4.5),
        ("tooltip_text", "tooltip_bg", 4.5),
        ("scrollbar_thumb", "scrollbar_track", 3.0),
        ("scrollbar_thumb_hover", "scrollbar_track", 3.0),
    )
    for name in themes.names():
        palette = themes.get(name)
        for foreground, background, threshold in checks:
            assert contrast_ratio(palette[foreground], palette[background]) >= threshold, (
                f"{name}: {foreground}/{background} contrast is below {threshold}:1"
            )


def test_category_tokens_are_merged_with_historical_defaults():
    for name in themes.names():
        palette = themes.get(name)
        assert palette["category_blend"] == "#2f7aa3"
        assert palette["category_model"] == "#3f8c69"
        assert palette["category_texture"] == "#8a6d3b"
        assert palette["category_archive"] == "#6f5a92"
        assert palette["category_bundled"] == "#7c6a39"
        assert palette["category_default"] == "#49555d"


def test_font_size_tokens_exist_in_every_shipped_theme_and_fallback():
    for name in themes.names():
        palette = themes.get(name)
        font_sizes = palette["properties"]["font_size"]
        assert font_sizes["xxs"] == 9
        assert font_sizes["xs"] == 10
        assert font_sizes["caption"] == 11
        assert font_sizes["xxl"] == 22
    assert themes.font_size("sm") == 12
    assert themes.font_size("caption") == 11
    assert themes.font_size("missing", default=13) == 13


def test_badge_color_resolves_through_category_theme_token():
    from AssetsManager.panels.file_list._common import badge_color_for_extension

    expected = themes.get()["category_texture"]
    assert badge_color_for_extension(".png").name().lower() == expected


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


def test_stylesheet_contains_semantic_button_variants_and_focus_state():
    qss = themes.stylesheet()

    for variant in ("primary", "secondary", "ghost", "danger"):
        assert f'buttonVariant="{variant}"' in qss
    assert "QPushButton:focus" in qss


def test_border_subtle_token_derived_from_border_and_used_in_qss():
    from AssetsManager.core.color_utils import alpha

    t = themes.get("Navy")
    assert "border_subtle" in t
    assert t["border_subtle"] == alpha(t["border"], 0.5)

    qss = themes.stylesheet()
    # The hairline token drives container separation instead of the raw border.
    assert t["border_subtle"] in qss


def test_set_button_variant_updates_dynamic_property():
    from PySide6.QtWidgets import QPushButton

    button = QPushButton()
    themes.set_button_variant(button, "danger")
    assert button.property("buttonVariant") == "danger"
    themes.set_button_variant(button, "invalid")
    assert button.property("buttonVariant") == "primary"


def test_theme_mode_for_base():
    from AssetsManager.core.themes import theme_mode_for_base
    assert theme_mode_for_base("#1a1a1a") == "dark"
    assert theme_mode_for_base("#ffffff") == "light"
    assert theme_mode_for_base("#252525") == "dark"
    assert theme_mode_for_base("#f0f0f0") == "light"
    assert theme_mode_for_base("#808080") == "dark"  # exactly at boundary
    assert theme_mode_for_base("#888888") == "light"  # above boundary


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


def test_stylesheet_has_modern_item_hover_states():
    from AssetsManager.core.color_utils import alpha

    qss = themes.stylesheet()

    assert "QListWidget::item:hover" in qss
    assert "QTreeWidget::item:hover" in qss
    # Menu-bar hover uses the translucent overlay instead of the raw
    # hover_overlay color (white in dark themes would be a hard flash).
    hov = alpha(
        themes.get()["hover_overlay"],
        themes.get()["properties"]["opacity"]["hover"],
    )
    assert hov in qss


def test_stylesheet_themes_native_controls():
    """Check/radio indicators, progress bars, sliders, and tooltips must be
    themed by the global QSS: without rules they fall back to the system
    light palette under dark themes (white indicators, white progress
    track, native tooltip)."""
    qss = themes.stylesheet()

    for selector in (
        "QCheckBox::indicator",
        "QRadioButton::indicator",
        "QCheckBox::indicator:checked",
        "QRadioButton::indicator:checked",
        "QCheckBox::indicator:hover",
        "QProgressBar",
        "QProgressBar::chunk",
        "QSlider::groove:horizontal",
        "QSlider::sub-page:horizontal",
        "QSlider::add-page:horizontal",
        "QSlider::handle:horizontal",
        "QToolTip",
    ):
        assert selector in qss, f"missing {selector} in global stylesheet"

    t = themes.get()
    # Unchecked indicators use the input surface + border; checked use the
    # accent; hover uses the focus border — all via tokens, not literals.
    assert t["input_bg"] in qss
    assert t["tooltip_bg"] in qss
    assert t["tooltip_text"] in qss
