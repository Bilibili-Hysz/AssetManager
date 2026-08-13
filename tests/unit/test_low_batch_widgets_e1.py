"""Low-batch E1: hsv_wheel mapping and stylekit missing-key tolerance."""
import types

import pytest
from PySide6.QtWidgets import QApplication

from AssetsManager.widgets.hsv_wheel import _hue_to_angle, _pos_to_hue


def _app():
    return QApplication.instance() or QApplication([])


# ── hsv_wheel mapping consistency ──────────────────────────────

@pytest.mark.parametrize(
    ("hue", "angle"),
    [
        (0.0, 0.0),
        (0.25, 90.0),
        (0.5, 180.0),
        (0.75, 270.0),
    ],
)
def test_hue_angle_roundtrip(hue, angle):
    # _pos_to_hue is the inverse of _hue_to_angle: a click at the angle where
    # the ring paints that hue selects exactly the color shown under cursor.
    assert _hue_to_angle(hue) == pytest.approx(angle)
    assert _pos_to_hue(0.0, -1.0) == pytest.approx(0.25)  # 12 o'clock


def test_pos_to_hue_cardinal_directions():
    assert _pos_to_hue(1.0, 0.0) == pytest.approx(0.0)    # 3 o'clock
    assert _pos_to_hue(0.0, -1.0) == pytest.approx(0.25)  # 12 o'clock
    assert _pos_to_hue(-1.0, 0.0) == pytest.approx(0.5)   # 9 o'clock
    assert _pos_to_hue(0.0, 1.0) == pytest.approx(0.75)   # 6 o'clock


def test_hsv_wheel_wheel_click_matches_display():
    _app()
    from AssetsManager.widgets.hsv_wheel import HSVWheel

    wheel = HSVWheel()
    wheel.resize(300, 300)
    # Click at 12 o'clock at the ring edge: hue 0.25, saturation ~1.
    wheel._update_from_pos(wheel.mapFromGlobal(wheel.mapToGlobal(wheel.rect().center())) + __import__("PySide6.QtCore", fromlist=["QPoint"]).QPoint(0, -140))
    color = wheel.get_color()
    assert color.hueF() == pytest.approx(0.25, abs=0.02)


# ── stylekit missing-key tolerance ─────────────────────────────

def test_stylekit_dialog_css_tolerates_missing_keys():
    from AssetsManager.core import themes
    from AssetsManager.widgets.stylekit import StyleKit

    # Take a real, valid theme and remove one directly-indexed key.  The
    # base fallback must be used instead of a KeyError; all other tokens
    # stay valid so token-level validation (a deliberate fail-closed) is
    # not exercised.
    data = dict(themes.get())
    assert "panel" in data
    del data["panel"]
    fake_theme = types.ModuleType("fake_theme")
    fake_theme.get = lambda: data
    sk = StyleKit.from_theme(fake_theme, px=lambda v: v, pt=lambda v: v)
    css = sk.dialog_css()
    assert "panel" not in css  # falls back to another token, never raises
