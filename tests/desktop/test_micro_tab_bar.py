"""Tests for MicroTabBar modern fluid tab control."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QEasingCurve, QRect, Qt
from PySide6.QtGui import QPaintEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from AssetsManager.widgets.micro_tab_bar import MicroTabBar


@pytest.fixture
def qapp():
    """Ensure QApplication instance exists for offscreen desktop tests."""
    app = QApplication.instance() or QApplication([])
    yield app


# ── 1. Initialization & Button Count ─────────────────────────────────


def test_micro_tab_bar_init_with_tabs(qapp):
    """Verify tab initialization and button count with a list of tab names."""
    tab_names = ["Overview", "Details", "Media", "Settings"]
    bar = MicroTabBar(tabs=tab_names)
    try:
        # Check count queries
        assert bar.count() == 4
        assert bar.tab_count() == 4
        assert bar.button_count() == 4
        assert len(bar.tabs) == 4
        assert len(bar.buttons) == 4

        # Check buttons are child QPushButton widgets
        buttons = bar.findChildren(QPushButton)
        assert len(buttons) == 4

        # Check titles and accessible names
        for idx, title in enumerate(tab_names):
            assert bar.tab_text(idx) == title
            assert buttons[idx].text() == title
            assert f"Tab: {title}" in buttons[idx].accessibleName()

        # Initial active index should be 0
        assert bar.current_index == 0
        assert bar.currentIndex() == 0
        assert bar.current_index() == 0
        assert buttons[0].isChecked()
        assert not buttons[1].isChecked()
    finally:
        bar.close()
        bar.deleteLater()
        qapp.processEvents()


def test_micro_tab_bar_empty_init(qapp):
    """Verify empty MicroTabBar initialization handles zero tabs gracefully."""
    bar = MicroTabBar()
    try:
        assert bar.count() == 0
        assert bar.tab_count() == 0
        assert bar.button_count() == 0
        assert len(bar.tabs) == 0
        assert len(bar.buttons) == 0
        assert bar.findChildren(QPushButton) == []
        assert bar.current_index == -1
        assert bar.currentIndex() == -1
        assert bar.tab_text(0) == ""
    finally:
        bar.close()
        bar.deleteLater()
        qapp.processEvents()


def test_micro_tab_bar_dynamic_add_and_set_tabs(qapp):
    """Verify dynamically modifying tabs updates button count and structure."""
    bar = MicroTabBar()
    try:
        # add_tab
        idx0 = bar.add_tab("Tab 1")
        assert idx0 == 0
        assert bar.count() == 1
        assert bar.button_count() == 1
        assert bar.current_index == 0

        idx1 = bar.add_tab("Tab 2")
        assert idx1 == 1
        assert bar.count() == 2
        assert bar.button_count() == 2

        # set_tabs replaces all
        bar.set_tabs(["A", "B", "C"])
        assert bar.count() == 3
        assert bar.button_count() == 3
        assert len(bar.findChildren(QPushButton)) == 3
        assert bar.tab_text(0) == "A"
        assert bar.tab_text(1) == "B"
        assert bar.tab_text(2) == "C"

        # remove_tab
        bar.remove_tab(1)
        assert bar.count() == 2
        assert bar.tab_text(0) == "A"
        assert bar.tab_text(1) == "C"

        # clear
        bar.clear()
        assert bar.count() == 0
        assert bar.current_index == -1
    finally:
        bar.close()
        bar.deleteLater()
        qapp.processEvents()


# ── 2. Signal current_changed on set_current_index ────────────────────


def test_set_current_index_triggers_signal(qapp):
    """Verify set_current_index emits current_changed signal and updates button states."""
    bar = MicroTabBar(tabs=["Tab 0", "Tab 1", "Tab 2"])
    emitted = []
    bar.current_changed.connect(emitted.append)

    try:
        # Switch to index 1
        bar.set_current_index(1)
        assert emitted == [1]
        assert bar.current_index == 1
        assert bar.currentIndex() == 1
        assert not bar.buttons[0].isChecked()
        assert bar.buttons[1].isChecked()
        assert not bar.buttons[2].isChecked()

        # Switch to index 2
        bar.set_current_index(2)
        assert emitted == [1, 2]
        assert bar.current_index == 2
        assert bar.buttons[2].isChecked()

        # Switching to same active index must not re-emit
        bar.set_current_index(2)
        assert emitted == [1, 2]

        # Switch back to index 0
        bar.set_current_index(0)
        assert emitted == [1, 2, 0]
        assert bar.current_index == 0
        assert bar.buttons[0].isChecked()
    finally:
        bar.close()
        bar.deleteLater()
        qapp.processEvents()


def test_button_click_triggers_current_changed(qapp):
    """Verify user clicking a tab button updates index and emits signal."""
    bar = MicroTabBar(tabs=["Alpha", "Beta", "Gamma"])
    emitted = []
    bar.current_changed.connect(emitted.append)

    try:
        # Click on second button (index 1)
        btn1 = bar.buttons[1]
        btn1.click()
        assert emitted == [1]
        assert bar.current_index == 1

        # Click on third button (index 2)
        btn2 = bar.buttons[2]
        btn2.click()
        assert emitted == [1, 2]
        assert bar.current_index == 2
    finally:
        bar.close()
        bar.deleteLater()
        qapp.processEvents()


# ── 3. Out-of-Bounds Index Protection ────────────────────────────────


def test_out_of_bounds_protection(qapp):
    """Verify out-of-bounds index requests are safely rejected without exception."""
    bar = MicroTabBar(tabs=["Left", "Right"])
    emitted = []
    bar.current_changed.connect(emitted.append)

    try:
        initial_idx = bar.current_index
        assert initial_idx == 0

        # Negative indices
        bar.set_current_index(-1)
        assert bar.current_index == 0
        assert emitted == []

        bar.set_current_index(-100)
        assert bar.current_index == 0
        assert emitted == []

        # Exceeding upper boundary
        bar.set_current_index(2)
        assert bar.current_index == 0
        assert emitted == []

        bar.set_current_index(999)
        assert bar.current_index == 0
        assert emitted == []

        # Empty bar bounds protection
        empty_bar = MicroTabBar()
        empty_emitted = []
        empty_bar.current_changed.connect(empty_emitted.append)
        empty_bar.set_current_index(0)
        empty_bar.set_current_index(1)
        empty_bar.set_current_index(-1)
        assert empty_bar.current_index == -1
        assert empty_emitted == []
        empty_bar.close()
        empty_bar.deleteLater()
    finally:
        bar.close()
        bar.deleteLater()
        qapp.processEvents()


# ── 4. Indicator Geometry & Animation Properties ─────────────────────


def test_indicator_animation_and_instant_switch(qapp):
    """Verify indicator_geometry property, animation setup, and instant switching."""
    bar = MicroTabBar(tabs=["First", "Second", "Third"])
    bar.resize(300, 32)
    bar.show()
    qapp.processEvents()

    try:
        # Check property animation configuration
        assert bar._indicator_anim.duration() == 200
        assert bar._indicator_anim.easingCurve().type() == QEasingCurve.Type.OutCubic

        # Property getter and setter
        test_rect = QRect(10, 2, 80, 24)
        bar.indicator_geometry = test_rect
        assert bar.indicator_geometry == test_rect

        # Instant switch with animate=False
        bar.set_current_index(2, animate=False)
        target2 = bar._target_indicator_rect(2)
        assert bar.indicator_geometry == target2

        # Switch with animate=True
        bar.set_current_index(0, animate=True)
        # Animation starts running
        qapp.processEvents()
        assert bar.current_index == 0
    finally:
        bar.close()
        bar.deleteLater()
        qapp.processEvents()


# ── 5. PaintEvent Rendering & Visual Robustness ──────────────────────


def test_paint_event_renders_without_exceptions(qapp):
    """Verify paintEvent executes and renders properly offscreen."""
    bar = MicroTabBar(tabs=["Tab A", "Tab B", "Tab C"])
    bar.resize(280, 32)
    bar.show()
    qapp.processEvents()

    try:
        # Grab offscreen pixmap (exercises paintEvent and child button painting)
        pixmap = bar.grab()
        assert not pixmap.isNull()
        assert pixmap.width() > 0 and pixmap.height() > 0

        # Direct paintEvent call with QPaintEvent
        event = QPaintEvent(bar.rect())
        bar.paintEvent(event)

        # Empty bar paint
        empty_bar = MicroTabBar()
        empty_bar.resize(200, 32)
        empty_bar.show()
        qapp.processEvents()
        empty_pm = empty_bar.grab()
        assert not empty_pm.isNull()
        empty_bar.close()
        empty_bar.deleteLater()

        # Theme and HighDPI scale refresh
        bar.refresh_theme()
        bar.refresh_scale(1.5)
        bar.update()
        qapp.processEvents()
        scaled_pm = bar.grab()
        assert not scaled_pm.isNull()
    finally:
        bar.close()
        bar.deleteLater()
        qapp.processEvents()


# ── 6. Keyboard Navigation ───────────────────────────────────────────


def test_keyboard_navigation(qapp):
    """Verify arrow keys and Home/End switch tabs."""
    bar = MicroTabBar(tabs=["One", "Two", "Three", "Four"])
    bar.resize(320, 32)
    bar.show()
    qapp.processEvents()

    try:
        bar.set_current_index(0, animate=False)
        assert bar.current_index == 0

        # Right arrow moves to next tab
        QTest.keyClick(bar, Qt.Key.Key_Right)
        assert bar.current_index == 1

        QTest.keyClick(bar, Qt.Key.Key_Right)
        assert bar.current_index == 2

        # Left arrow moves to previous tab
        QTest.keyClick(bar, Qt.Key.Key_Left)
        assert bar.current_index == 1

        # End key moves to last tab
        QTest.keyClick(bar, Qt.Key.Key_End)
        assert bar.current_index == 3

        # Home key moves to first tab
        QTest.keyClick(bar, Qt.Key.Key_Home)
        assert bar.current_index == 0
    finally:
        bar.close()
        bar.deleteLater()
        qapp.processEvents()
