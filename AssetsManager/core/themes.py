"""Unified theme system — JSON-driven, backward compatible.

v2 changes:
  - Themes loaded from JSON files in themes/ directory.
  - Extended color tokens (on_accent, scrollbar_thumb, etc.) for fine-grained control.
  - Non-color properties (border_radius, spacing, font_size) accessible via themes.prop().
  - Color utility module (color_utils.py) replaces hex-opacity hacks.
  - API fully backward compatible with v1 (get, set_theme, names, stylesheet, apply_to).

Performance:
  - Loads saved theme once at startup.
  - Theme changes trigger save to AppSettings and broadcast via signal_bus.
  - stylesheet() result cached (invalidated on theme change).
"""
import re
import sys
import threading
from AssetsManager.core.settings import AppSettings
from AssetsManager.core.signal_bus import get as bus
from AssetsManager.core.color_utils import alpha
from AssetsManager.core.theme_loader import ThemeLoader

# ── Internal state ────────────────────────────────────────

_THEMES: dict[str, dict] = {}          # name → merged dict (colors + properties)
_THEME_NAMES: list[str] = []           # display order
_DEFAULT_NAME = "Default"
_current = "Navy"
_cached_stylesheet: str | None = None
_cached_stylesheet_theme: str | None = None
_cached_stylesheet_scale: float | None = None
_themes_lock = threading.Lock()

# ThemeLoader singleton
_loader = ThemeLoader()


def _get_loader() -> ThemeLoader:
    """Return the ThemeLoader singleton."""
    return _loader

# Migration map: old lowercase names → new capitalized names
_MIGRATION_MAP: dict[str, str] = {
    "navy": "Navy",
    "slate": "Slate",
    "forest": "Forest",
    "amber": "Amber",
    "dracula": "Dracula",
    "nord": "Nord",
    "gruvbox": "Gruvbox",
    "rose pine": "Rose Pine",
    "midnight": "Midnight",
    "charcoal": "Charcoal",
    "espresso": "Espresso",
    "dawn": "Dawn",
    "silver": "Silver",
    "mint": "Mint",
    "lavender": "Lavender",
    "peach": "Peach",
    "sky": "Sky",
    "rose": "Rose",
    "sage": "Sage",
    "coral": "Coral",
    "lilac": "Lilac",
    "default": "Default",
}

# Required legacy tokens (v1 compatibility)
_REQUIRED_TOKENS = [
    "base", "panel", "header", "border",
    "heading", "body", "muted", "accent",
    "success", "warning", "danger",
    "favorite", "recent",
]

# Extended tokens with fallback sources
_EXTENDED_FALLBACKS = {
    "on_accent":           lambda t: "#ffffff",
    "hover_overlay":       lambda t: "#ffffff" if t.get("dark", True) else "#000000",
    "selected_overlay":    lambda t: t.get("accent", "#4a60b0"),
    "border_focus":        lambda t: t.get("accent", "#4a60b0"),
    "input_bg":            lambda t: t.get("panel", "#252525"),
    "input_text":          lambda t: t.get("heading", "#e0e0e0"),
    "scrollbar_track":     lambda t: t.get("base", "#1a1a1a"),
    "scrollbar_thumb":     lambda t: t.get("muted", "#666666"),
    "scrollbar_thumb_hover": lambda t: t.get("border", "#555555"),
    "disabled_text":       lambda t: t.get("muted", "#666666"),
    "disabled_bg":         lambda t: t.get("base", "#1a1a1a"),
    "tooltip_bg":          lambda t: t.get("header", "#2d2d2d"),
    "tooltip_text":        lambda t: t.get("heading", "#e0e0e0"),
    # Semantic file-category colors. Themes may override these so category
    # badges adapt to dark/light palettes while staying distinguishable from
    # chrome accents. Defaults preserve the historical fixed-hex palette.
    "category_blend":      lambda t: "#2f7aa3",
    "category_model":      lambda t: "#3f8c69",
    "category_texture":    lambda t: "#8a6d3b",
    "category_archive":    lambda t: "#6f5a92",
    "category_bundled":    lambda t: "#7c6a39",
    "category_default":    lambda t: "#49555d",
    # Low-contrast "hairline" border for container/panel separation. Kept
    # distinct from ``border`` (input outlines) so surfaces read as layered
    # rather than boxed-in.
    "border_subtle":       lambda t: alpha(t.get("border", "#555555"), 0.5),
    # Semantic icon colors — themes may override these to tune icon tint
    # without affecting text colors. Defaults inherit from text tokens.
    "icon_primary":        lambda t: t.get("heading", "#e0e0e0"),
    "icon_secondary":      lambda t: t.get("body", "#b0b0b0"),
    "icon_muted":          lambda t: t.get("muted", "#666666"),
    "icon_on_accent":      lambda t: t.get("on_accent", "#ffffff"),
    "icon_accent":         lambda t: t.get("accent", "#4a60b0"),
    "icon_disabled":       lambda t: t.get("disabled_text", "#666666"),
}


# ── Path resolution ───────────────────────────────────────

def _themes_dir() -> str:
    """Resolve themes/ directory (PyInstaller bundle or dev)."""
    return _loader.themes_dir


def _load_all_themes():
    """Scan themes/ directory via ThemeLoader, load all valid .json files."""
    global _THEMES, _THEME_NAMES
    _THEMES.clear()
    _THEME_NAMES.clear()

    _loader.scan_directory()

    for name, data in _loader._themes.items():
        merged = _merge_theme(data)
        if merged is not None:
            _THEMES[name] = merged
            _THEME_NAMES.append(name)

    if not _THEMES:
        print("[themes] ERROR: no valid themes found", file=sys.stderr)


def _merge_theme(data: dict) -> dict | None:
    """Convert raw theme JSON data into merged flat dict with extended tokens.

    Returns None (theme discarded) when the data is malformed: missing
    required keys, a non-dict ``colors`` block, any non-hex color token, or
    invalid token types that would crash QSS generation later.
    """
    if not isinstance(data, dict) or "name" not in data or "colors" not in data:
        return None

    colors = data.get("colors")
    if not isinstance(colors, dict):
        return None
    for token in _REQUIRED_TOKENS:
        if token not in colors or not _is_hex_color(colors[token]):
            return None

    merged = dict(colors)
    merged["dark"] = data.get("dark", True)
    merged["name"] = data["name"]
    merged["description"] = data.get("description", "")
    properties = data.get("properties")
    merged["properties"] = properties if isinstance(properties, dict) else {}

    for token, fallback_fn in _EXTENDED_FALLBACKS.items():
        if token not in merged:
            merged[token] = fallback_fn(merged)

    return merged


_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?$")


def _is_hex_color(value: object) -> bool:
    """Return True for '#RGB' / '#RRGGBB' hex color strings."""
    return isinstance(value, str) and bool(_HEX_COLOR_RE.match(value))


# ── Startup ───────────────────────────────────────────────

_load_all_themes()


def _load_saved():
    global _current
    try:
        settings = AppSettings.instance()
        settings.load()
        saved = settings.get("theme")
        # Migrate old lowercase name if needed
        if saved:
            saved = _MIGRATION_MAP.get(saved.lower(), saved)
        if saved in _THEMES:
            _current = saved
        elif _THEMES:
            _current = _THEME_NAMES[0] if _THEME_NAMES else "Default"
    except Exception:
        if _THEMES:
            _current = _THEME_NAMES[0] if _THEME_NAMES else "Default"


_load_saved()


def _invalidate_icon_cache() -> None:
    """Drop theme-tinted SVG pixmaps without creating a core import cycle."""
    try:
        from AssetsManager.core import icons
        icons.clear_cache()
    except Exception:
        # Theme loading must remain usable before the icon registry is ready.
        pass


# ── Public API ────────────────────────────────────────────

def get(name: str | None = None) -> dict:
    """Return the merged theme dict for the given or current theme.

    The returned dict contains all color tokens and properties as
    flat keys. Use t['accent'] or t['properties']['border_radius']['md'].

    Always returns a valid dict — falls back to first available theme
    if the requested name is not loaded.
    """
    key = name or _current
    if key in _THEMES:
        return _THEMES[key]
    if _THEMES:
        return next(iter(_THEMES.values()))
    return {}


def set_theme(name: str):
    """Switch to the named theme, persist, and broadcast.

    Handles migration of old lowercase names to new capitalized names.
    Does nothing if the theme is not loaded.
    """
    global _current, _cached_stylesheet
    # Migrate old lowercase name if needed
    migrated = _MIGRATION_MAP.get(name.lower(), name) if name else name
    with _themes_lock:
        if migrated not in _THEMES:
            print(f"[themes] WARNING: theme '{name}' not found", file=sys.stderr)
            return
        _current = migrated
        _cached_stylesheet = None
        _invalidate_icon_cache()
    try:
        settings = AppSettings.instance()
        settings.set("theme", migrated)
        settings.save()
    except Exception:
        pass
    bus().theme_changed.emit(migrated)


def invalidate_cache():
    """Force stylesheet regeneration on next access."""
    global _cached_stylesheet, _cached_stylesheet_theme, _cached_stylesheet_scale
    with _themes_lock:
        _cached_stylesheet = None
        _cached_stylesheet_theme = None
        _cached_stylesheet_scale = None


def names() -> list[str]:
    """Return list of user-facing theme names (excludes 'Default' fallback)."""
    return [n for n in _THEME_NAMES if n != "Default"]


def reload_themes():
    """Reload all themes from disk. Called by file watcher or manual refresh."""
    global _current
    previous = _current
    _load_all_themes()
    # Restore the previously active theme when it survived the rescan; a
    # transient failure to parse one file (e.g. a mid-write JSON) must not
    # permanently reset the user's selection to the first theme.
    if previous in _THEMES:
        _current = previous
    elif _THEMES:
        _current = _THEME_NAMES[0] if _THEME_NAMES else "Default"
    invalidate_cache()
    _invalidate_icon_cache()
    bus().theme_changed.emit(_current)


_loader.themes_changed.connect(reload_themes)
_loader.watch_changes()


# ── Font size tokens ─────────────────────────────────────
# Semantic font-size steps. Shipped themes carry these keys in their
# ``properties.font_size`` block (see Assets/Themes/*.json); the fallback map
# keeps custom/user themes that predate the extended keys safe.
_FONT_SIZE_FALLBACKS: dict[str, int] = {
    "xxs": 9,
    "xs": 10,
    "caption": 11,
    "sm": 12,
    "md": 13,
    "lg": 14,
    "xl": 16,
    "xxl": 22,
}


def font_size(key: str, default: int = 12) -> int:
    """Return a semantic font-size token in unscaled points.

    Unlike :func:`prop`, a missing key falls back to the built-in semantic
    map instead of ``0`` so QSS never collapses to an unreadable 0px font
    when a custom theme predates the extended font_size keys.
    """
    value = prop("font_size", key)
    if value:
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    return _FONT_SIZE_FALLBACKS.get(key, default)


def dark_themes() -> list[str]:
    """Return dark-mode theme names only."""
    return [n for n in names() if _THEMES.get(n, {}).get("dark", True)]


def light_themes() -> list[str]:
    """Return light-mode theme names only."""
    return [n for n in names() if not _THEMES.get(n, {}).get("dark", True)]


def categories() -> list[tuple[str, list[str]]]:
    """Return themes grouped by category for UI display.
    
    Returns list of (label, [theme_names]) suitable for grouped radio buttons.
    """
    return [
        ("Dark", dark_themes()),
        ("Light", light_themes()),
    ]


def name() -> str:
    """Return the current theme name."""
    return _current


def is_dark() -> bool:
    """Return True if the current theme is dark mode."""
    t = get()
    return t.get("dark", True)


def color(token: str) -> str:
    """Return a single color token value from the current theme.

    Args:
        token: e.g. 'accent', 'scrollbar_thumb', 'disabled_text'.

    Returns:
        Hex color string (e.g. '#4a60b0').
    """
    return get().get(token, "")


def prop(category: str, key: str) -> int | float:
    """Return a property value from the current theme.

    Args:
        category: 'border_radius', 'spacing', 'font_size', 'opacity', 'animation'.
        key: e.g. 'md', 'lg', 'sm'.

    Returns:
        Numeric value from the theme's properties section.
    """
    props = get().get("properties", {})
    cat = props.get(category, {})
    return cat.get(key, 0)


def set_button_variant(widget, variant: str = "primary"):
    """Apply a semantic button variant and repolish the widget.

    Variants are represented by a dynamic property so global QSS and dialog
    local stylesheets can share the same semantic vocabulary.
    """
    allowed = {"primary", "secondary", "ghost", "danger"}
    normalized = str(variant or "primary").strip().lower()
    if normalized not in allowed:
        normalized = "primary"
    widget.setProperty("buttonVariant", normalized)
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()
    return widget


# ── Background image API ─────────────────────────────────

def _bg_defaults() -> dict:
    """Return default background settings from the current theme JSON."""
    return get().get("background", {})


def _bg_setting(key: str, default=None):
    """Read an AppSettings override, falling back to theme default."""
    try:
        val = AppSettings.instance().get(f"bg_{key}")
        if val is not None:
            return val
    except Exception:
        pass
    return _bg_defaults().get(key, default)


def _bg_number(key: str, default: float) -> float:
    """Return a numeric background setting or its safe default."""
    value = _bg_setting(key, default)
    if not isinstance(value, (str, int, float)):
        return default
    try:
        return float(value)
    except ValueError:
        return default


def bg_enabled() -> bool:
    """Whether background image is enabled (user setting overrides theme default)."""
    return bool(_bg_setting("enabled"))


def bg_image() -> str:
    """Path to background image, or '' if none."""
    return str(_bg_setting("image", ""))


def bg_scale() -> str:
    """Scaling mode: 'fill', 'fit', 'center', 'tile'."""
    return str(_bg_setting("scale", "fill"))


def bg_panel_opacity() -> float:
    return _bg_number("panel_opacity", 0.88)


def bg_header_opacity() -> float:
    return _bg_number("header_opacity", 1.0)


def bg_overall_opacity() -> float:
    return _bg_number("opacity", 1.0)


def bg_type() -> str:
    """Background type: 'image' or 'video'."""
    return str(_bg_setting("type", "image"))


def bg_effect() -> str:
    """Active image effect: 'none', 'blur', or 'mosaic'."""
    return str(_bg_setting("effect", "none"))


def bg_effect_intensity() -> int:
    """Intensity of the active effect (1-50 for blur, 2-50 for mosaic)."""
    return int(_bg_number("effect_intensity", 20.0))


def panel_color() -> str:
    """Return the effective panel background color.

    Accounts for header opacity so that the combined transparency of
    PanelContent + its inner header matches across all panels
    (including File List where the header sits inside the panel).
    """
    if bg_enabled():
        return alpha(get()["panel"], bg_panel_opacity() * bg_header_opacity())
    return get()["panel"]


def header_for_dock() -> str:
    """Return dock/header background, semi-transparent when bg image is enabled."""
    if bg_enabled():
        return alpha(get()["header"], bg_header_opacity())
    return get()["header"]


# ── Stylesheet ────────────────────────────────────────────

def stylesheet() -> str:
    """Build and return the global QSS stylesheet for the current theme.

    Cached result is invalidated on theme change.
    """
    global _cached_stylesheet, _cached_stylesheet_theme, _cached_stylesheet_scale
    from AssetsManager.core.ui_scale import get_ui_scale, scaled_px, scaled_pt
    scale = get_ui_scale()
    with _themes_lock:
        if (
            _cached_stylesheet is not None
            and _cached_stylesheet_theme == _current
            and _cached_stylesheet_scale == scale
        ):
            return _cached_stylesheet
    t = get()
    props = t.get("properties", {})
    radius = props.get("border_radius", {})
    r_sm = scaled_px(int(radius.get("sm", 8)))
    r_md = scaled_px(int(radius.get("md", 10)))
    r_lg = scaled_px(int(radius.get("lg", 14)))
    spacing = props.get("spacing", {})
    s_xs = scaled_px(int(spacing.get("xs", 4)))
    s_sm = scaled_px(int(spacing.get("sm", 8)))
    s_md = scaled_px(int(spacing.get("md", 12)))
    s_lg = scaled_px(int(spacing.get("lg", 16)))
    font = props.get("font_size", {})
    f_sm = scaled_pt(int(font.get("sm", 12)))
    hov = alpha(t["hover_overlay"], props.get("opacity", {}).get("hover", 0.15))
    hairline = t.get("border_subtle", alpha(t["border"], 0.5))
    pane_opacity = bg_panel_opacity()
    hdr_opacity = bg_header_opacity()
    panel_alpha = alpha(t["panel"], pane_opacity * hdr_opacity) if bg_enabled() else t["panel"]
    main_bg = "transparent" if bg_enabled() else t["base"]
    dock_title_bg = alpha(t["header"], hdr_opacity)
    menubar_bg = alpha(t["header"], hdr_opacity) if bg_enabled() else t["header"]
    result = f"""
    QMainWindow {{ background: {main_bg}; }}
    QDialog {{ background: {t['panel']}; }}
    QDockWidget {{ background: transparent; }}
    QDockWidget::title {{
        background: {dock_title_bg};
        border: 1px solid {hairline};
        border-top-left-radius: {r_md}px; border-top-right-radius: {r_md}px;
        padding: {s_sm}px {s_md}px;
        color: {t['heading']};
        font-size: {f_sm}px; font-weight: bold;
    }}
    QMenuBar {{ background: {menubar_bg}; color: {t['heading']}; border-bottom: 1px solid {hairline}; }}
    QMenuBar::item:selected {{ background: {hov}; }}
    QMenu {{ background: {t['panel']}; color: {t['heading']}; border: 1px solid {hairline}; border-radius: {r_md}px; padding: {s_xs}px; }}
    QMenu::item {{ padding: {s_sm}px {s_lg}px; border-radius: {r_sm}px; }}
    QMenu::item:selected {{ background: {t['accent']}; color: {t['on_accent']}; }}
    QListWidget, QTreeWidget, QTabWidget::pane {{
        background: transparent; border: none; padding: {s_xs}px;
        color: {t['body']}; outline: none;
    }}
    QTabBar::tab {{
        background: transparent; color: {t['muted']};
        border: 1px solid transparent; padding: {s_sm}px {s_md}px;
        border-radius: {r_md}px; margin-right: {s_xs}px;
    }}
    QTabBar::tab:hover:!selected {{ background: {hov}; }}
    QTabBar::tab:selected {{ background: {t['panel']}; color: {t['heading']}; border-color: {hairline}; }}
    QListWidget::item, QTreeWidget::item {{ padding: {s_sm}px {s_md}px; border-radius: {r_sm}px; }}
    QListWidget::item:hover, QTreeWidget::item:hover {{
        background: {hov}; border-radius: {r_sm}px;
    }}
    QListWidget::item:selected, QTreeWidget::item:selected {{
        background: {t['accent']}; border-radius: {r_sm}px; color: {t['on_accent']};
    }}
    QLabel {{ color: {t['body']}; }}
    QLineEdit, QTextEdit, QComboBox, QSpinBox {{
        background: {t['input_bg']}; color: {t['input_text']};
        border: 1px solid {t['border']}; border-radius: {r_sm}px; padding: {s_sm}px {s_md}px;
        selection-background-color: {t['accent']}; selection-color: {t['on_accent']};
    }}
    QLineEdit:focus, QTextEdit:focus, QSpinBox:focus {{ border: 1px solid {t['border_focus']}; }}
    QComboBox::drop-down {{ border: none; width: {s_lg}px; }}
    QComboBox QAbstractItemView {{
        background: {t['panel']}; color: {t['body']};
        border: 1px solid {hairline}; selection-background-color: {t['accent']}; selection-color: {t['on_accent']};
    }}
    QGroupBox {{
        color: {t['heading']}; border: 1px solid {hairline};
        border-radius: {r_md}px; margin-top: {s_md}px; padding-top: {s_md}px;
    }}
    QGroupBox::title {{ subcontrol-origin: margin; left: {s_md}px; padding: 0 {s_xs}px; }}
    QRadioButton, QCheckBox {{ color: {t['body']}; spacing: {s_sm}px; }}
    QPushButton {{
        background: {t['accent']}; color: {t['on_accent']};
        border: none; border-radius: {r_sm}px; padding: {s_sm}px {s_lg}px;
        font-weight: 600;
    }}
    QPushButton:hover {{ background: {alpha(t['accent'], 0.88)}; }}
    QPushButton:pressed {{ background: {alpha(t['accent'], 0.72)}; }}
    QPushButton:focus {{ border: 1px solid {t['border_focus']}; padding: {s_sm}px {s_lg}px; }}
    QPushButton[buttonVariant="primary"] {{
        background: {t['accent']}; color: {t['on_accent']};
    }}
    QPushButton[buttonVariant="primary"]:hover {{
        background: {alpha(t['accent'], 0.88)};
    }}
    QPushButton[buttonVariant="primary"]:pressed {{
        background: {alpha(t['accent'], 0.72)};
    }}
    QPushButton[buttonVariant="secondary"] {{
        background: {t['panel']}; color: {t['heading']};
        border: 1px solid {hairline};
    }}
    QPushButton[buttonVariant="secondary"]:hover {{
        background: {hov};
    }}
    QPushButton[buttonVariant="secondary"]:pressed {{
        background: {alpha(t['accent'], 0.18)};
    }}
    QPushButton[buttonVariant="ghost"] {{
        background: transparent; color: {t['body']};
        border: 1px solid transparent;
    }}
    QPushButton[buttonVariant="ghost"]:hover {{
        background: {hov};
        color: {t['heading']};
    }}
    QPushButton[buttonVariant="danger"] {{
        background: {t['danger']}; color: {t['on_accent']};
    }}
    QPushButton[buttonVariant="danger"]:hover {{
        background: {alpha(t['danger'], 0.88)};
    }}
    QPushButton:disabled {{
        background: {t['disabled_bg']}; color: {t['disabled_text']};
    }}
    QScrollBar:vertical {{
        background: transparent; width: {scaled_px(6)}px;
    }}
    QScrollBar::handle:vertical {{
        background: {t['scrollbar_thumb']}; border-radius: {r_sm}px; min-height: {scaled_px(24)}px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {t['scrollbar_thumb_hover']};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{
        background: transparent; height: {scaled_px(6)}px;
    }}
    QScrollBar::handle:horizontal {{
        background: {t['scrollbar_thumb']}; border-radius: {r_sm}px; min-width: {scaled_px(24)}px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {t['scrollbar_thumb_hover']};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget#qt_scrollarea_viewport {{
        background: {t['panel']};
    }}
    QSplitter::handle {{
        background: {hairline}; border-radius: {r_sm}px;
    }}
    QSplitter::handle:hover {{
        background: {t['accent']};
    }}
    QSplitter {{ background: transparent; }}
    #PanelContent {{
        background: {panel_alpha};
        border: 1px solid {hairline};
        border-bottom-left-radius: {r_lg}px; border-bottom-right-radius: {r_lg}px;
        border-top: none;
    }}
"""
    with _themes_lock:
        _cached_stylesheet = result
        _cached_stylesheet_theme = _current
        _cached_stylesheet_scale = scale
    return result


def apply_to(widget):
    """Apply the global stylesheet to a given widget."""
    style = stylesheet()
    # QApplication/QWidget style application reparses and repolishes the
    # complete widget tree. Avoid doing that when a refresh did not actually
    # change the generated stylesheet (common during dialog/theme cascades).
    if widget.styleSheet() != style:
        widget.setStyleSheet(style)


def theme_mode_for_base(hex_color: str) -> str:
    """Return 'dark' or 'light' based on base color luminance."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except (ValueError, IndexError):
        return "dark"
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return "light" if luminance >= 128 else "dark"
