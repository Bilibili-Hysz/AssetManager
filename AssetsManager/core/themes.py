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
    """Convert raw theme JSON data into merged flat dict with extended tokens."""
    if "name" not in data or "colors" not in data:
        return None

    colors = data.get("colors", {})
    for token in _REQUIRED_TOKENS:
        if token not in colors:
            return None

    merged = dict(colors)
    merged["dark"] = data.get("dark", True)
    merged["name"] = data["name"]
    merged["description"] = data.get("description", "")
    merged["properties"] = data.get("properties", {})

    for token, fallback_fn in _EXTENDED_FALLBACKS.items():
        if token not in merged:
            merged[token] = fallback_fn(merged)

    return merged


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
    try:
        settings = AppSettings.instance()
        settings.set("theme", migrated)
        settings.save()
    except Exception:
        pass
    bus().theme_changed.emit(migrated)


def invalidate_cache():
    """Force stylesheet regeneration on next access."""
    global _cached_stylesheet, _cached_stylesheet_theme
    with _themes_lock:
        _cached_stylesheet = None
        _cached_stylesheet_theme = None


def names() -> list[str]:
    """Return list of user-facing theme names (excludes 'Default' fallback)."""
    return [n for n in _THEME_NAMES if n != "Default"]


def reload_themes():
    """Reload all themes from disk. Called by file watcher or manual refresh."""
    global _current
    _load_all_themes()
    if _current not in _THEMES and _THEMES:
        _current = _THEME_NAMES[0] if _THEME_NAMES else "Default"
    invalidate_cache()
    bus().theme_changed.emit(_current)


_loader.themes_changed.connect(reload_themes)
_loader.watch_changes()


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
    return float(_bg_setting("panel_opacity", 0.88))


def bg_header_opacity() -> float:
    return float(_bg_setting("header_opacity", 1.0))


def bg_overall_opacity() -> float:
    return float(_bg_setting("opacity", 1.0))


def bg_type() -> str:
    """Background type: 'image' or 'video'."""
    return str(_bg_setting("type", "image"))


def bg_effect() -> str:
    """Active image effect: 'none', 'blur', or 'mosaic'."""
    return str(_bg_setting("effect", "none"))


def bg_effect_intensity() -> int:
    """Intensity of the active effect (1-50 for blur, 2-50 for mosaic)."""
    return int(_bg_setting("effect_intensity", 20))


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
    global _cached_stylesheet, _cached_stylesheet_theme
    with _themes_lock:
        if _cached_stylesheet is not None and _cached_stylesheet_theme == _current:
            return _cached_stylesheet
    from AssetsManager.core.ui_scale import scaled_px
    t = get()
    hov = alpha(t["hover_overlay"], t["properties"].get("opacity", {}).get("hover", 0.15))
    pane_opacity = bg_panel_opacity()
    hdr_opacity = bg_header_opacity()
    panel_alpha = alpha(t["panel"], pane_opacity * hdr_opacity) if bg_enabled() else t["panel"]
    main_bg = "transparent" if bg_enabled() else t["base"]
    dock_title_bg = alpha(t["header"], hdr_opacity)
    menubar_bg = alpha(t["header"], hdr_opacity) if bg_enabled() else t["header"]
    result = f"""
    QMainWindow {{ background: {main_bg}; }}
    QMainWindow::separator {{
        width: 2px; height: 2px; background: {t['base']};
    }}
    QDialog {{ background: {t['panel']}; }}
    QDockWidget {{ background: transparent; }}
    QDockWidget::title {{
        background: {dock_title_bg};
        border: 1px solid {t['border']};
        border-top-left-radius: {scaled_px(7)}px; border-top-right-radius: {scaled_px(7)}px;
        padding: 5px 10px;
        color: {t['heading']};
        font-size: 12px; font-weight: bold;
    }}
    QMenuBar {{ background: {menubar_bg}; color: {t['heading']}; border-bottom: 1px solid {t['border']}; }}
    QMenuBar::item:selected {{ background: {t['border']}; }}
    QMenu {{ background: {t['panel']}; color: {t['heading']}; border: 1px solid {t['border']}; }}
    QMenu::item:selected {{ background: {t['accent']}; color: {t['heading']}; }}
    QListWidget, QTreeWidget, QTabWidget::pane {{
        background: transparent; border: none; padding: {scaled_px(4)}px;
        color: {t['body']}; outline: none;
    }}
    QTabBar::tab {{
        background: {t['panel']}; color: {t['body']};
        border: 1px solid {t['border']}; padding: {scaled_px(4)}px {scaled_px(12)}px;
        border-top-left-radius: {scaled_px(4)}px; border-top-right-radius: {scaled_px(4)}px;
    }}
    QTabBar::tab:selected {{ background: {t['accent']}; color: {t['on_accent']}; }}
    QListWidget::item, QTreeWidget::item {{ padding: {scaled_px(3)}px {scaled_px(6)}px; }}
    QListWidget::item:selected, QTreeWidget::item:selected {{
        background: {t['accent']}; border-radius: {scaled_px(4)}px; color: {t['on_accent']};
    }}
    QLabel {{ color: {t['body']}; }}
    QLineEdit, QTextEdit, QComboBox, QSpinBox {{
        background: {t['input_bg']}; color: {t['input_text']};
        border: 1px solid {t['border']}; border-radius: {scaled_px(4)}px; padding: {scaled_px(3)}px {scaled_px(6)}px;
    }}
    QComboBox::drop-down {{ border: none; }}
    QComboBox QAbstractItemView {{
        background: {t['panel']}; color: {t['body']};
        border: 1px solid {t['border']}; selection-background-color: {t['accent']};
    }}
    QGroupBox {{
        color: {t['heading']}; border: 1px solid {t['border']};
        border-radius: {scaled_px(6)}px; margin-top: {scaled_px(8)}px; padding-top: {scaled_px(12)}px;
    }}
    QGroupBox::title {{ subcontrol-origin: margin; left: {scaled_px(10)}px; padding: 0 {scaled_px(5)}px; }}
    QRadioButton, QCheckBox {{ color: {t['body']}; }}
    QPushButton {{
        background: {t['accent']}; color: {t['on_accent']};
        border: none; border-radius: {scaled_px(4)}px; padding: {scaled_px(6)}px {scaled_px(16)}px;
    }}
    QPushButton:hover {{ background: {hov}; }}
    QPushButton:pressed {{ background: {t['muted']}; }}
    QPushButton:disabled {{
        background: {t['disabled_bg']}; color: {t['disabled_text']};
    }}
    QScrollBar:vertical {{
        background: {t['scrollbar_track']}; width: {scaled_px(8)}px;
        border-radius: {scaled_px(4)}px;
    }}
    QScrollBar::handle:vertical {{
        background: {t['scrollbar_thumb']}; border-radius: {scaled_px(4)}px; min-height: {scaled_px(20)}px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {t['scrollbar_thumb_hover']};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{
        background: {t['scrollbar_track']}; height: {scaled_px(8)}px;
        border-radius: {scaled_px(4)}px;
    }}
    QScrollBar::handle:horizontal {{
        background: {t['scrollbar_thumb']}; border-radius: {scaled_px(4)}px; min-width: {scaled_px(20)}px;
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
        background: {t['border']};
    }}
    QSplitter::handle:hover {{
        background: {t['accent']};
    }}
    QSplitter {{ background: transparent; }}
    #PanelContent {{
        background: {panel_alpha};
        border: 1px solid {t['border']};
        border-bottom-left-radius: {scaled_px(7)}px; border-bottom-right-radius: {scaled_px(7)}px;
        border-top: none;
    }}
"""
    with _themes_lock:
        _cached_stylesheet = result
        _cached_stylesheet_theme = _current
    return result


def apply_to(widget):
    """Apply the global stylesheet to a given widget."""
    widget.setStyleSheet(stylesheet())


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
