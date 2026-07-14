"""UI Scale — global zoom factor for layout, fonts, and thumbnail sizes.

Read from AppSettings key "ui_scale" (float, default 1.0).
Live update via signal_bus().ui_scale_changed.
"""
from __future__ import annotations

from AssetsManager.core.settings import AppSettings


def get_ui_scale() -> float:
    """Return the current UI scale factor (0.5 – 3.0)."""
    try:
        s = AppSettings.instance().get("ui_scale", 1.0)
        if isinstance(s, (int, float)):
            return max(0.5, min(3.0, float(s)))
    except Exception:
        pass
    return 1.0


def scaled_px(px: int) -> int:
    """Scale a pixel value by the UI scale factor."""
    return max(1, round(px * get_ui_scale()))


def scaled_pt(pt: int) -> int:
    """Scale a point size by the UI scale factor."""
    return max(6, round(pt * get_ui_scale()))
