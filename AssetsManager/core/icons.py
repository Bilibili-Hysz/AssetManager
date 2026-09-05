"""Small, theme-aware SVG icon registry for the desktop UI.

The registry intentionally keeps the icon vocabulary small and semantic.  It
renders line icons through QtSvg instead of relying on platform glyphs, which
keeps the visual result stable across Windows themes and fonts.
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from typing import cast

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from AssetsManager.core import themes
from AssetsManager.core.ui_scale import scaled_px

_log = logging.getLogger(__name__)

# Bounded LRU: keys are (icon, tint, pixel_size, dpr) so a long-lived session
# mixing many sizes/colors/dprs cannot grow the cache without limit. Entries
# past the cap evict the least-recently-used pixmap.
_CACHE_MAX = 4096

_ICON_PATHS: dict[str, str] = {
    "settings": (
        '<path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z"/>'
        '<path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-1.9 1.9-.06-.06a1.7 1.7 0 0 0-1.88-.34 1.7 1.7 0 0 0-1.03 1.56V21h-2.7v-.99a1.7 1.7 0 0 0-1.03-1.56 1.7 1.7 0 0 0-1.88.34l-.06.06-1.9-1.9.06-.06A1.7 1.7 0 0 0 7.75 15a1.7 1.7 0 0 0-1.56-1.03H5.2v-2.7h.99A1.7 1.7 0 0 0 7.75 10a1.7 1.7 0 0 0-.34-1.88l-.06-.06 1.9-1.9.06.06a1.7 1.7 0 0 0 1.88.34 1.7 1.7 0 0 0 1.03-1.56V4h2.7v.99a1.7 1.7 0 0 0 1.03 1.56 1.7 1.7 0 0 0 1.88-.34l.06-.06 1.9 1.9-.06.06A1.7 1.7 0 0 0 19.4 10a1.7 1.7 0 0 0 1.56 1.03H22v2.7h-1.04A1.7 1.7 0 0 0 19.4 15Z"/>'
    ),
    "share": (
        '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/>'
        '<circle cx="18" cy="19" r="3"/><path d="m8.7 10.5 6.6-3.9M8.7 13.5l6.6 3.9"/>'
    ),
    "wrench": (
        '<path d="M14.7 6.3a4.5 4.5 0 0 0-5.96 5.96L3.5 17.5a2.12 2.12 0 0 0 3 3l5.24-5.24a4.5 4.5 0 0 0 5.96-5.96l-2.55 2.55-2.12-2.12Z"/>'
    ),
    "puzzle": (
        '<path d="M19 13h-1.5a2.5 2.5 0 1 1-5 0V11.5a2.5 2.5 0 1 0-5 0V13H5a2 2 0 0 0-2 2v4a2 2 0 0 0 2 2h4v-1.5a2.5 2.5 0 1 1 5 0V21h5a2 2 0 0 0 2-2v-4a2 2 0 0 0-2-2Z"/>'
    ),
    "folder": '<path d="M3 6h6l2 2h10v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/>',
    "file": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6M8 13h8M8 17h6"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    "qr_code": '<path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h2v2h-2zM18 14h2v2h-2zM14 18h2v2h-2zM18 18h2v2h-2z"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9" r="1.5"/><path d="m4 17 4.5-4 3 2.5 2.5-2 6 5.5"/>',
    "video": '<rect x="3" y="6" width="13" height="12" rx="2"/><path d="m16 10 5-3v10l-5-3Z"/>',
    "archive": '<path d="M4 6h16v14H4zM3 4h18v3H3z"/><path d="M10 11h4"/>',
    "cube": '<path d="m12 3 8 4.5v9L12 21l-8-4.5v-9Z"/><path d="m4 7.5 8 4.5 8-4.5M12 12v9"/>',
    "code": '<path d="m8 8-4 4 4 4M16 8l4 4-4 4M14 4l-4 16"/>',
    "star": '<path d="m12 3 2.78 5.63 6.22.9-4.5 4.39 1.06 6.2L12 17.2l-5.56 2.92 1.06-6.2L3 9.53l6.22-.9Z"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "tag": '<path d="M20.59 13.41 13.4 20.6a2 2 0 0 1-2.83 0L3.4 13.41a2 2 0 0 1 0-2.82V4h6.59a2 2 0 0 1 1.41.59l9.19 9.18a2 2 0 0 1 0 2.83Z"/><circle cx="7.5" cy="7.5" r="1"/>',
    "home": '<path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1Z"/><path d="M9 21v-6h6v6"/>',
    "chevron_right": '<path d="m9 18 6-6-6-6"/>',
    "grid": '<rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><rect x="14" y="14" width="6" height="6" rx="1"/>',
    "list": '<path d="M8 6h13M8 12h13M8 18h13"/><path d="M3 6h.01M3 12h.01M3 18h.01"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
    "more_horizontal": '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
    "maximize": '<path d="M8 3H5a2 2 0 0 0-2 2v3M16 3h3a2 2 0 0 1 2 2v3M8 21H5a2 2 0 0 1-2-2v-3M16 21h3a2 2 0 0 0 2-2v-3"/>',
    "minimize": '<path d="M5 12h14"/>',
    "close": '<path d="m6 6 12 12M18 6 6 18"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "check": '<path d="m5 12 4 4L19 6"/>',
    "trash": '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7l1-3h4l1 3"/>',
    "arrow_left": '<path d="M19 12H5M12 19l-7-7 7-7"/>',
    "arrow_right": '<path d="M5 12h14M12 5l7 7-7 7"/>',
    "arrow_up": '<path d="M12 19V5M5 12l7-7 7 7"/>',
    "arrow_down": '<path d="M12 5v14M5 12l7 7 7-7"/>',
    "arrow_up_down": '<path d="m7 7 5-4 5 4M7 17l5 4 5-4M12 3v18"/>',
    "chevron_down": '<path d="m6 9 6 6 6-6"/>',
    "eye": '<path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z"/><circle cx="12" cy="12" r="2.5"/>',
    "eye_off": '<path d="m3 3 18 18M10.6 10.6a2 2 0 0 0 2.8 2.8M9.9 5.2A10.7 10.7 0 0 1 12 5c6.5 0 10 7 10 7a17.6 17.6 0 0 1-3.1 3.9M6.2 6.2C3.8 7.8 2 12 2 12s3.5 7 10 7c1 0 1.9-.2 2.7-.5"/>',
    "refresh": '<path d="M20 11a8 8 0 1 0 1 4"/><path d="M20 4v7h-7"/>',
    "download": '<path d="M12 5v11M5 9l7 7 7-7M4 20h16"/>',
    "external_link": '<path d="M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
    "folder_open": '<path d="m6 14 1.45-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.55 6a2 2 0 0 1-1.94 1.5H4a2 2 0 0 1-2-2V5c0-1.1.9-2 2-2h3.93a2 2 0 0 1 1.66.9l.82 1.2a2 2 0 0 0 1.66.9H18a2 2 0 0 1 2 2v2"/>',
    "heart": '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/>',
    "monitor": '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>',
    "pause": '<path d="M9 4v16M15 4v16"/>',
    "play": '<path d="m6 3 14 9-14 9Z"/>',
    "save": '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z"/><path d="M17 21v-8H7v8M7 3v4h8"/>',
    "upload": '<path d="M12 16V5M5 12l7-7 7 7M4 20h16"/>',
}

_ALIASES = {
    "gear": "settings",
    "globe": "share",
    "plugin": "puzzle",
    "chevron-right": "chevron_right",
    "more-horizontal": "more_horizontal",
    "monitor_screen": "monitor",
    "screen": "monitor",
    "floppy": "save",
    "external": "external_link",
    "open_folder": "folder_open",
}
_CACHE: "OrderedDict[tuple[str, str, int, float], QIcon]" = OrderedDict()

# Theme tokens accepted as semantic color roles by icon(). Anything not in
# this set is treated as an explicit color string (hex / rgb / rgba).
_SEMANTIC_COLORS = frozenset({
    "heading", "body", "muted", "accent", "on_accent",
    "favorite", "recent", "success", "warning", "danger",
    "disabled_text",
    "icon_primary", "icon_secondary", "icon_muted",
    "icon_on_accent", "icon_accent", "icon_disabled",
})


def _resolve_tint(color: str | None) -> str:
    """Resolve a semantic token name or explicit color to a hex string."""
    if color is None:
        return themes.color("icon_primary") or themes.color("heading") or "#ffffff"
    if color in _SEMANTIC_COLORS:
        return themes.color(color) or "#ffffff"
    return color


def normalize(name: str | None, fallback: str = "file") -> str:
    """Return a known semantic icon name without exposing glyph fallbacks."""
    key = str(name or "").strip().lower().replace(" ", "_").replace("-", "_")
    key = _ALIASES.get(key, key)
    return key if key in _ICON_PATHS else fallback


def names() -> tuple[str, ...]:
    return tuple(sorted(_ICON_PATHS))


def has(name: str | None) -> bool:
    key = str(name or "").strip().lower().replace(" ", "_").replace("-", "_")
    return _ALIASES.get(key, key) in _ICON_PATHS


def _detect_dpr(explicit_dpr: float | None = None) -> float:
    """Detect the exact DPR for the current focused window or primary screen."""
    if explicit_dpr is not None and explicit_dpr > 0:
        return float(explicit_dpr)

    app = QGuiApplication.instance()
    if app is None:
        return 1.0

    # 1. Focused window takes precedence
    focus_win = QGuiApplication.focusWindow()
    if focus_win is not None:
        try:
            dpr = focus_win.devicePixelRatio()
            if dpr > 0:
                return float(dpr)
        except Exception:
            pass
        try:
            scr = focus_win.screen()
            if scr is not None and scr.devicePixelRatio() > 0:
                return float(scr.devicePixelRatio())
        except Exception:
            pass

    # 2. Active widget window via application
    active_win_fn = getattr(app, "activeWindow", None)
    if callable(active_win_fn):
        try:
            active_win = active_win_fn()
            if active_win is not None:
                dpr_fn = getattr(active_win, "devicePixelRatioF", None)
                if callable(dpr_fn):
                    # QWindow.devicePixelRatioF; fetched via getattr so the
                    # static type is the untyped object.
                    dpr = cast("float", dpr_fn())
                    if dpr > 0:
                        return float(dpr)
                scr = getattr(active_win, "screen", lambda: None)()
                if scr is not None and scr.devicePixelRatio() > 0:
                    return float(scr.devicePixelRatio())
        except Exception:
            pass

    # 3. Any visible top-level window
    try:
        for win in QGuiApplication.topLevelWindows():
            if win.isVisible():
                dpr = win.devicePixelRatio()
                if dpr > 0:
                    return float(dpr)
    except Exception:
        pass

    # 4. Fallback to primary screen
    try:
        screen = QGuiApplication.primaryScreen()
        if screen is not None and screen.devicePixelRatio() > 0:
            return float(screen.devicePixelRatio())
    except Exception:
        pass

    return 1.0


def icon(
    name: str | None,
    *,
    color: str | None = None,
    size: int | None = None,
    fallback: str = "file",
    dpr: float | None = None,
) -> QIcon:
    """Render a semantic line icon using the current theme color.

    ``color`` accepts a semantic theme token name (e.g. "icon_primary",
    "heading", "favorite") or an explicit color string (e.g. "#c480d4").
    None resolves to the theme's primary icon color.
    ``dpr`` optionally forces an exact device pixel ratio; otherwise detects
    from the current focused window or primary screen.
    """
    resolved = normalize(name, fallback=fallback)
    tint = _resolve_tint(color)
    pixel_size = max(1, int(size or scaled_px(16)))
    effective_dpr = max(1.0, _detect_dpr(dpr))
    cache_key = (resolved, tint, pixel_size, effective_dpr)
    cached = _CACHE.get(cache_key)
    if cached is not None:
        _CACHE.move_to_end(cache_key)
        return cached

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="{tint}" stroke-width="1.8" '
        f'stroke-linecap="round" stroke-linejoin="round">{_ICON_PATHS[resolved]}</svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(int(pixel_size * effective_dpr), int(pixel_size * effective_dpr))
    pixmap.setDevicePixelRatio(effective_dpr)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        renderer.render(painter, QRectF(0, 0, pixel_size, pixel_size))
    finally:
        painter.end()
    result = QIcon(pixmap)
    if abs(effective_dpr - 1.0) > 0.01:
        base_pixmap = QPixmap(pixel_size, pixel_size)
        base_pixmap.setDevicePixelRatio(1.0)
        base_pixmap.fill(Qt.GlobalColor.transparent)
        bp = QPainter(base_pixmap)
        try:
            renderer.render(bp, QRectF(0, 0, pixel_size, pixel_size))
        finally:
            bp.end()
        result.addPixmap(base_pixmap)
    _CACHE[cache_key] = result
    _CACHE.move_to_end(cache_key)
    if len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return result


def clear_cache() -> None:
    """Clear rendered icon pixmaps after a theme or scale refresh."""
    _CACHE.clear()
