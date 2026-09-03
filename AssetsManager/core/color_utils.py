"""Color utility functions for theme-aware styling.

Replaces hex-opacity string concatenation and QColor.lighter() calls
with explicit, readable, testable functions.
"""
import colorsys


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert '#RRGGBB' to (R, G, B) 0-255 tuple."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    """Convert (R, G, B) 0-255 to '#RRGGBB'."""
    return f"#{r:02x}{g:02x}{b:02x}"


def alpha(hex_color: str, opacity: float) -> str:
    """Return CSS rgba() string with given opacity.

    Args:
        hex_color: '#RRGGBB' hex color string.
        opacity: 0.0 (transparent) to 1.0 (fully opaque).

    Returns:
        'rgba(R, G, B, opacity)' CSS string.

    Examples:
        alpha("#4a60b0", 0.19)  → "rgba(74, 96, 176, 0.19)"
        alpha("#12121a", 0.5)   → "rgba(18, 18, 26, 0.5)"
    """
    r, g, b = _hex_to_rgb(hex_color)
    return f"rgba({r}, {g}, {b}, {opacity:.2f})"


def contrast_on(
    hex_color: str,
    *,
    dark: str = "#1b1b1b",
    light: str = "#ffffff",
    fallback: str = "#ffffff",
) -> str:
    """Return a readable foreground (dark or light) for a colored background.

    Mirrors the historical tag swatch heuristic (HSL lightness > 160/255 gets
    dark text) so callers can share one implementation without visual drift.
    Invalid colors return ``fallback``.
    """
    try:
        r, g, b = _hex_to_rgb(hex_color)
    except (ValueError, IndexError):
        return fallback
    _, lightness, _ = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    return dark if lightness > (160.0 / 255.0) else light


def lighten(hex_color: str, factor: float = 1.3) -> str:
    """Lighten a color by multiplying its HSL lightness.

    Args:
        hex_color: '#RRGGBB' hex color string.
        factor: Multiplier for lightness (1.0 = unchanged, >1.0 = lighter).

    Returns:
        '#RRGGBB' hex string.

    Examples:
        lighten("#1e1e2a", 1.3)  → lighter navy
        lighten("#f0ede6", 1.1)  → slightly lighter cream
    """
    r, g, b = _hex_to_rgb(hex_color)
    r_n, g_n, b_n = r / 255.0, g / 255.0, b / 255.0
    h, lightness, s = colorsys.rgb_to_hls(r_n, g_n, b_n)
    lightness = min(1.0, lightness * factor)
    r2, g2, b2 = colorsys.hls_to_rgb(h, lightness, s)
    return _rgb_to_hex(int(r2 * 255), int(g2 * 255), int(b2 * 255))


def darken(hex_color: str, factor: float = 0.8) -> str:
    """Darken a color by multiplying its HSL lightness.

    Args:
        hex_color: '#RRGGBB' hex color string.
        factor: Multiplier for lightness (1.0 = unchanged, <1.0 = darker).

    Returns:
        '#RRGGBB' hex string.

    Examples:
        darken("#faf7f2", 0.9)  → slightly darker cream
        darken("#606060", 0.7)  → much darker gray
    """
    r, g, b = _hex_to_rgb(hex_color)
    r_n, g_n, b_n = r / 255.0, g / 255.0, b / 255.0
    h, lightness, s = colorsys.rgb_to_hls(r_n, g_n, b_n)
    lightness = max(0.0, lightness * factor)
    r2, g2, b2 = colorsys.hls_to_rgb(h, lightness, s)
    return _rgb_to_hex(int(r2 * 255), int(g2 * 255), int(b2 * 255))


def lighter(hex_color: str, factor: int = 110) -> str:
    """Lighten a color the way ``QColor.lighter`` does (HSV value scaling).

    This is the CANONICAL hover algorithm for accent buttons across the
    app (Design System audit 2026-09-03, finding B4): opaque result that
    does not depend on the widget stack beneath it, unlike ``alpha()``.
    ``StyleKit._lighter`` and the central QSS both route through this
    formula; do not introduce additional hover/pressed recipes.

    Args:
        hex_color: '#RRGGBB' hex color string.
        factor: Percentage multiplier for HSV value (110 = 10% lighter).

    Returns:
        '#RRGGBB' hex string.
    """
    r, g, b = _hex_to_rgb(hex_color)
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    v = min(1.0, v * factor / 100.0)
    r2, g2, b2 = colorsys.hsv_to_rgb(h, s, v)
    return _rgb_to_hex(round(r2 * 255), round(g2 * 255), round(b2 * 255))


def darker(hex_color: str, factor: int = 115) -> str:
    """Darken a color the way ``QColor.darker`` does (HSV value scaling).

    Canonical pressed algorithm for accent/danger buttons — the pressed
    counterpart of :func:`lighter`.

    Args:
        hex_color: '#RRGGBB' hex color string.
        factor: Percentage divisor for HSV value (115 = ~13% darker).

    Returns:
        '#RRGGBB' hex string.
    """
    r, g, b = _hex_to_rgb(hex_color)
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    v = max(0.0, v / (factor / 100.0))
    r2, g2, b2 = colorsys.hsv_to_rgb(h, s, v)
    return _rgb_to_hex(round(r2 * 255), round(g2 * 255), round(b2 * 255))


def contrast_ratio(fg_hex: str, bg_hex: str) -> float:
    """Calculate WCAG 2.0 contrast ratio between two colors.

    Args:
        fg_hex: Foreground hex color.
        bg_hex: Background hex color.

    Returns:
        Float ratio (1.0 to 21.0). 4.5 is minimum for body text, 7.0 for headings.

    Examples:
        contrast_ratio("#b0b0c8", "#1e1e2a")  → ~8.5 (good)
        contrast_ratio("#6a6a80", "#1e1e2a")  → ~3.5 (insufficient)
    """
    def _relative_luminance(r: int, g: int, b: int) -> float:
        def _lin(c: float) -> float:
            c /= 255.0
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)

    l1 = _relative_luminance(*_hex_to_rgb(fg_hex))
    l2 = _relative_luminance(*_hex_to_rgb(bg_hex))
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)
