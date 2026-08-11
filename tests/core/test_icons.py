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


def test_icon_semantic_color_roles_resolve_from_theme():
    for role in ("icon_primary", "icon_secondary", "icon_muted",
                 "icon_on_accent", "icon_accent", "icon_disabled"):
        expected = themes.color(role)
        assert expected, f"theme token {role} must resolve"
        assert _line_tint("folder", role) == _hex_rgb(expected)


def test_icon_legacy_token_names_resolve():
    assert _line_tint("folder", "heading") == _hex_rgb(themes.color("heading"))
    assert _line_tint("folder", "favorite") == _hex_rgb(themes.color("favorite"))


def test_icon_explicit_hex_passthrough():
    assert _line_tint("folder", "#c480d4") == (196, 128, 212)


def test_icon_default_color_is_primary():
    default = _line_tint("folder", None)
    assert default == _hex_rgb(themes.color("icon_primary"))
