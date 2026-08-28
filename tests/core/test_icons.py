"""Tests for the semantic desktop icon registry."""
from PySide6.QtCore import QSize

from AssetsManager.core import icons, themes


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


def test_icon_pixmap_has_transparent_background():
    image = icons.icon("folder", color="#ffffff", size=16).pixmap(16, 16).toImage()

    alphas = [
        image.pixelColor(x, y).alpha()
        for x in range(image.width())
        for y in range(image.height())
    ]
    assert any(a == 0 for a in alphas), "no fully transparent pixels (black background regression)"
    assert any(a > 0 for a in alphas), "no visible content pixels (blank icon)"


def test_new_semantic_icons_render():
    expected = {
        "monitor", "save", "heart", "info", "external_link",
        "play", "pause", "upload", "download", "folder_open",
    }
    assert expected.issubset(set(icons.names()))
    for name in expected:
        assert not icons.icon(name, color="#ffffff", size=16).isNull()


def _line_tint(name, color):
    image = icons.icon(name, color=color, size=24).pixmap(24, 24).toImage()
    px = [
        image.pixelColor(x, y)
        for x in range(image.width())
        for y in range(image.height())
        if image.pixelColor(x, y).alpha() > 100
    ]
    assert px, f"icon {name} rendered blank"
    return (round(sum(p.red() for p in px) / len(px)),
            round(sum(p.green() for p in px) / len(px)),
            round(sum(p.blue() for p in px) / len(px)))


def _hex_rgb(value):
    v = value.lstrip("#")
    return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))


def _assert_tint_matches(actual, expected):
    # Platform tolerance: the SVG rasterizer's anti-aliased pixel averaging
    # rounds differently across Qt builds/platforms (Ubuntu CI rendered
    # (240,232,217) where Windows produced (240,232,216) — a ±1 LSB shift
    # per channel), so the semantic tint is asserted with a small
    # platform-independent tolerance instead of exact equality.
    assert all(abs(a - b) <= 2 for a, b in zip(actual, expected, strict=True)), (
        f"tint {actual} != expected {expected} (tolerance ±2)"
    )


def test_icon_semantic_color_roles_resolve_from_theme():
    for role in ("icon_primary", "icon_secondary", "icon_muted",
                 "icon_on_accent", "icon_accent", "icon_disabled"):
        expected = themes.color(role)
        assert expected, f"theme token {role} must resolve"
        _assert_tint_matches(_line_tint("folder", role), _hex_rgb(expected))


def test_icon_legacy_token_names_resolve():
    _assert_tint_matches(_line_tint("folder", "heading"), _hex_rgb(themes.color("heading")))
    _assert_tint_matches(_line_tint("folder", "favorite"), _hex_rgb(themes.color("favorite")))


def test_icon_explicit_hex_passthrough():
    _assert_tint_matches(_line_tint("folder", "#c480d4"), (196, 128, 212))


def test_icon_default_color_is_primary():
    default = _line_tint("folder", None)
    _assert_tint_matches(default, _hex_rgb(themes.color("icon_primary")))
