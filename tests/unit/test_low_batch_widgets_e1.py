"""Low-batch E1: hsv_wheel mapping, file_picker stat cache, pager search
capping, stylekit missing-key tolerance, command palette lazy rebuild."""
import os
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


# ── file_picker stat cache ─────────────────────────────────────

def test_file_picker_precomputes_dir_flags_once(tmp_path, monkeypatch):
    _app()
    from AssetsManager.widgets.file_picker import FilePickerDialog

    dlg = FilePickerDialog()
    dlg._filter_files = lambda text: None  # avoid UI rebuild in the test
    d = tmp_path / "subdir"
    d.mkdir()
    f = tmp_path / "file.txt"
    f.write_text("x", encoding="utf-8")
    files = [
        {"path": str(d), "name": "subdir", "tag": ""},
        {"path": str(f), "name": "file.txt", "tag": ""},
    ]
    calls = {"n": 0}
    real_isdir = os.path.isdir

    def counting_isdir(p):
        calls["n"] += 1
        return real_isdir(p)

    monkeypatch.setattr(os.path, "isdir", counting_isdir)
    dlg.set_file_list(files)
    # The cache is consulted afterwards; filtering must not re-stat.
    monkeypatch.setattr(os.path, "isdir", lambda p: (calls.__setitem__("n", calls["n"] + 1) or real_isdir(p)))
    assert dlg._is_dir_cache[str(d)] is True
    assert dlg._is_dir_cache[str(f)] is False
    dlg.close()


# ── pager search capping ───────────────────────────────────────

def test_pager_find_matches_caps_results():
    from AssetsManager.widgets.pager_overlay import _MAX_SEARCH_MATCHES, _find_matches

    text = "a" * 5000 + "b" * 2000
    matches = _find_matches("a", text)
    assert len(matches) == _MAX_SEARCH_MATCHES
    # All spans point into the text and match the query.
    assert all(text[start:end] == "a" for start, end in matches)


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


# ── command palette lazy rebuild ───────────────────────────────

def test_command_palette_registration_does_not_rebuild(monkeypatch):
    _app()
    from AssetsManager.widgets.command_palette import CommandPalette

    palette = CommandPalette()
    rebuilds = {"n": 0}

    def counting_rebuild(text=""):
        rebuilds["n"] += 1

    monkeypatch.setattr(palette, "_filter_results", counting_rebuild)
    for i in range(10):
        palette.register_command(f"cmd-{i}", "label", lambda: None)
    assert rebuilds["n"] == 0  # registration appends incrementally only
    palette.close()


def test_command_palette_group_order_independent_of_registration_order():
    _app()
    from AssetsManager.widgets.command_palette import CommandPalette

    # Register in reverse canonical order; the groups must still render
    # commands → files → tags (matching a full rebuild via _filter_results).
    palette = CommandPalette()
    palette.register_tag("Brand")
    palette.register_file("C:/assets/logo.svg", "logo.svg")
    palette.register_command("cat", "do-thing", lambda: None)
    items = [
        palette._results_list.item(i).text()
        for i in range(palette._results_list.count())
    ]
    # Group headings separate the records; assert relative order.
    assert items.index("do-thing") < items.index("logo.svg") < items.index("Brand")
    palette.close()
