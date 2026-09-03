"""G5 snapshot — StyleKit factory QSS output is pinned.

The StyleKit generators are the sanctioned single entry point for local QSS
(check_style_sources.py exempts them for exactly that reason), so accidental
changes to their output would silently restyle every consumer at once.  The
snapshot pins each factory's output against a fixed theme (identity scale —
scaling is orthogonal to the token logic).

Intentional changes: run with ``STYLEKIT_SNAPSHOT_UPDATE=1`` and land the
snapshot diff in the same commit as the change, with the design rationale
in the commit message (same culture as ``gen_ts_types.py --check``).
"""
from __future__ import annotations

import copy
import os
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from AssetsManager.core import themes
from AssetsManager.widgets.stylekit import StyleKit, _identity_px, _identity_pt

SNAPSHOT_PATH = Path(__file__).parent / "snapshots" / "stylekit_factories_snapshot.txt"


def _snapshot_theme_name() -> str:
    """Pin the snapshot to the first registry theme.

    Theme registry keys come from the theme files' internal names (Amber,
    Charcoal, …), NOT the D_/L_ filename prefixes.
    """
    return themes.names()[0]


def _frozen_theme() -> dict:
    return copy.deepcopy(themes.get(_snapshot_theme_name()))


def _build_sections() -> dict[str, str]:
    app = QApplication.instance() or QApplication([])
    del app
    sk = StyleKit(theme=_frozen_theme(), px=_identity_px, pt=_identity_pt)
    sections: dict[str, str] = {
        "label_css": sk.label_css(),
        "label_css.heading.bold": sk.label_css("heading", size=14, bold=True),
        "heading_css": sk.heading_css(),
        "muted_css": sk.muted_css(),
        "state_css.idle": sk.state_css("idle"),
        "state_css.error": sk.state_css("error"),
        "dialog_css": sk.dialog_css(),
        "tab_css": sk.tab_css(),
        "button_css.primary": sk.button_css("primary"),
        "button_css.secondary": sk.button_css("secondary"),
        "button_css.ghost": sk.button_css("ghost"),
        "button_css.danger": sk.button_css("danger"),
        "switch_css": sk.switch_css(),
        "nav_css": sk.nav_css(),
        "status_bar_css": sk.status_bar_css(),
    }
    badge = sk.make_status_badge("idle")
    sections["make_status_badge.styleSheet"] = badge.styleSheet()
    badge.deleteLater()
    pill = sk.make_pill_button("Go")
    sections["make_pill_button.styleSheet"] = pill.styleSheet()
    pill.deleteLater()
    return sections


def _render() -> str:
    sections = _build_sections()
    body = "\n\n".join(
        f"=== {name} ===\n{text}" for name, text in sorted(sections.items())
    )
    return f"# theme: {_snapshot_theme_name()}\n\n" + body + "\n"


@pytest.fixture
def snapshot_file():
    if os.environ.get("STYLEKIT_SNAPSHOT_UPDATE") == "1":
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_PATH.write_text(_render(), encoding="utf-8")
    return SNAPSHOT_PATH


def test_stylekit_factories_match_snapshot(snapshot_file):
    assert snapshot_file.is_file(), (
        "snapshot missing — run STYLEKIT_SNAPSHOT_UPDATE=1 once to seed it")
    expected = snapshot_file.read_text(encoding="utf-8")
    assert _render() == expected, (
        "StyleKit factory output changed — if intentional, regenerate with "
        "STYLEKIT_SNAPSHOT_UPDATE=1 and justify the diff in the commit")
