"""G4 contract — the central theme QSS must stay complete and render clean.

Guards the central stylesheet against the failure modes from the Design
System audit (2026-09-03, findings B1/B3/E5):

* key widget selectors may not silently disappear (a selector removed here
  orphans every widget that relied on the central rule);
* the four ``buttonVariant`` rules must stay in lockstep with
  ``themes.set_button_variant``'s allowed set (danger was defined but never
  used — pinning it here keeps the variant vocabulary honest);
* every theme must render QSS without the two known broken-output shapes:
  ``font-size: 0px`` (a missing ``font_size`` token resolves to 0) and
  empty declarations (a missing color token resolves to ``""``).
"""
from __future__ import annotations

import re

import pytest

from AssetsManager.core import themes
from AssetsManager.core.settings import AppSettings

REQUIRED_SELECTORS = [
    "QMainWindow",
    "QDialog",
    "QDockWidget",
    "QMenuBar",
    "QMenu",
    "QListWidget",
    "QTreeWidget",
    "QTabBar",
    "QLineEdit",
    "QTextEdit",
    "QComboBox",
    "QSpinBox",
    "QGroupBox",
    "QPushButton",
    "QPushButton[buttonVariant=\"primary\"]",
    "QPushButton[buttonVariant=\"secondary\"]",
    "QPushButton[buttonVariant=\"ghost\"]",
    "QPushButton[buttonVariant=\"danger\"]",
    "QPushButton:disabled",
    "QPushButton:checked",
    "QHeaderView::section",
    "QMenu::separator",
    "QLineEdit:disabled",
    "QScrollBar:vertical",
    "QScrollBar:horizontal",
    "QScrollArea",
    "QSplitter::handle",
    "QProgressBar",
    "QSlider",
    "QToolTip",
    "#PanelContent",
]

VARIANT_RE = re.compile(r"QPushButton\[buttonVariant=\"(\w+)\"\]")


@pytest.fixture
def restored_theme():
    """Save the persisted theme and restore it after the test."""
    saved = AppSettings.instance().get("theme")
    yield saved
    if saved:
        themes.set_theme(saved)


def test_central_qss_contains_required_selectors():
    qss = themes.stylesheet()
    missing = [selector for selector in REQUIRED_SELECTORS if selector not in qss]
    assert not missing, f"central QSS lost required selectors: {missing}"


def test_button_variants_match_allowed_set():
    qss = themes.stylesheet()
    found = set(VARIANT_RE.findall(qss))
    assert found == {"primary", "secondary", "ghost", "danger"}, (
        "buttonVariant QSS rules and themes.set_button_variant's allowed set "
        "must stay in lockstep (danger must remain defined)")


def test_metrics_builtin_tokens_resolvable():
    """I2 (audit E6): the metrics token family must stay resolvable."""
    for key in ("icon_sm", "icon_xs", "hit_area", "control_height_md", "radius_xs"):
        assert themes.metrics(key) > 0
    assert themes.metrics("nonexistent_metric") == 0


@pytest.mark.parametrize("name", themes.names())
def test_qss_renders_clean_for_every_theme(name, restored_theme):
    themes.set_theme(name)
    qss = themes.stylesheet()
    # Missing font_size tokens resolve to 0 → "font-size: 0px".
    assert "font-size: 0px" not in qss
    # Missing color tokens resolve to "" → empty declarations.
    assert "color: ;" not in qss
    assert "background: ;" not in qss
    assert "border: ;" not in qss
