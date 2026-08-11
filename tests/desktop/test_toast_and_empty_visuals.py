"""Tests for Toast and EmptyPanel visual components."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QApplication, QLabel, QWidget
from shiboken6 import isValid

from AssetsManager.core import themes
from AssetsManager.core.settings import AppSettings
from AssetsManager.core.ui_scale import scaled_px
from AssetsManager.panels.empty import EmptyPanel
from AssetsManager.widgets.toast import Toast


# ── Toast tests ───────────────────────────────────────────────


def _global_rect(widget: QWidget) -> QRect:
    return QRect(widget.mapToGlobal(QPoint(0, 0)), widget.size())


def _accent_bar(toast: Toast) -> QWidget:
    bar = toast.layout().itemAt(0).widget()
    assert bar is not None
    return bar


def _flush_deferred_deletes(app: QApplication):
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_toast_renders_with_theme_tokens():
    """Toast border bar and body use current theme tokens."""
    app = QApplication.instance() or QApplication([])
    t = themes.get()
    parent = QWidget()
    parent.resize(800, 600)
    parent.show()
    app.processEvents()
    try:
        toast = Toast(parent, "Hello", level="info")
        toast.show()
        app.processEvents()
        assert toast.isVisible()
        shell_ss = toast.styleSheet()
        assert "border-radius" in shell_ss
        assert t["accent"] in _accent_bar(toast).styleSheet()
        body = toast.layout().itemAt(1).widget()
        assert body is not None
        assert t["panel"] in body.styleSheet()
        assert t["border"] in body.styleSheet()
    finally:
        toast.dismiss_immediately()
        parent.close()
        parent.deleteLater()
        app.processEvents()


def test_toast_icon_and_subtitle():
    """Toast displays SVG icon and subtitle when provided."""
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(800, 600)
    parent.show()
    app.processEvents()
    try:
        toast = Toast(parent, "Saved", icon="check", subtitle="backup created")
        toast.show()
        app.processEvents()
        assert toast.isVisible()
        labels = toast.findChildren(QLabel)
        icon_labels = [lb for lb in labels if lb.pixmap() is not None and not lb.pixmap().isNull()]
        assert len(icon_labels) == 1
        sub_labels = [lb for lb in labels if lb.text() == "backup created"]
        assert len(sub_labels) == 1
    finally:
        toast.dismiss_immediately()
        parent.close()
        parent.deleteLater()
        app.processEvents()


def test_toast_non_semantic_icon_is_skipped():
    """Non-semantic icon values (e.g. emoji) are not rendered as text."""
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(800, 600)
    parent.show()
    app.processEvents()
    try:
        toast = Toast(parent, "Saved", icon="!")
        toast.show()
        app.processEvents()
        labels = toast.findChildren(QLabel)
        icon_labels = [lb for lb in labels if lb.pixmap() is not None and not lb.pixmap().isNull()]
        assert len(icon_labels) == 0
    finally:
        toast.dismiss_immediately()
        parent.close()
        parent.deleteLater()
        app.processEvents()


def test_toast_success_level_uses_success_color():
    """Toast success level applies success token to accent bar."""
    app = QApplication.instance() or QApplication([])
    t = themes.get()
    parent = QWidget()
    parent.resize(800, 600)
    parent.show()
    app.processEvents()
    try:
        toast = Toast(parent, "Done", level="success")
        toast.show()
        app.processEvents()
        assert t["success"] in _accent_bar(toast).styleSheet()
    finally:
        toast.dismiss_immediately()
        parent.close()
        parent.deleteLater()
        app.processEvents()


def test_toast_reduce_motion_skips_fade_in():
    """Toast skips fade-in animation when reduce_motion is active."""
    app = QApplication.instance() or QApplication([])
    settings = AppSettings.instance()
    original = settings.get("reduce_motion", False)
    settings.set("reduce_motion", True)
    parent = QWidget()
    parent.resize(800, 600)
    parent.show()
    app.processEvents()
    try:
        toast = Toast(parent, "Quick", level="info")
        toast.show()
        app.processEvents()
        assert toast._opacity_effect.opacity() == pytest.approx(1.0)
        assert toast._fade_in_anim.state() != toast._fade_in_anim.State.Running
    finally:
        toast.dismiss_immediately()
        parent.close()
        parent.deleteLater()
        app.processEvents()
        settings.set("reduce_motion", original)


def test_toast_reduce_motion_dismiss_is_immediate():
    """Toast dismiss skips fade-out and closes immediately when reduce_motion is active."""
    app = QApplication.instance() or QApplication([])
    settings = AppSettings.instance()
    original = settings.get("reduce_motion", False)
    settings.set("reduce_motion", True)
    parent = QWidget()
    parent.resize(800, 600)
    parent.show()
    app.processEvents()
    try:
        toast = Toast.info(parent, "Gone")
        app.processEvents()
        toast._start_fade_out()
        app.processEvents()
        assert not toast.isVisible()
        assert Toast._instance is None
    finally:
        parent.close()
        parent.deleteLater()
        app.processEvents()
        settings.set("reduce_motion", original)


def test_toast_singleton_recovers_after_parent_is_deleted():
    """Deleting a parent clears the singleton before another toast is created."""
    app = QApplication.instance() or QApplication([])
    first_parent = QWidget()
    first_parent.show()
    app.processEvents()

    first_toast = Toast.info(first_parent, "First", duration=60_000)
    first_parent.deleteLater()
    _flush_deferred_deletes(app)

    assert not isValid(first_toast)
    assert Toast._instance is None

    second_parent = QWidget()
    second_parent.show()
    app.processEvents()
    try:
        second_toast = Toast.info(second_parent, "Second", duration=60_000)
        app.processEvents()
        assert isValid(second_toast)
        assert Toast._instance is second_toast
    finally:
        if Toast._instance is not None and isValid(Toast._instance):
            Toast._instance.dismiss_immediately()
        second_parent.deleteLater()
        _flush_deferred_deletes(app)


@pytest.mark.parametrize("parent_action", ["hide", "close", "destroy"])
def test_toast_is_removed_when_parent_stops_being_visible(parent_action):
    """A parent lifecycle transition cannot leave an orphaned Tool toast."""
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.show()
    app.processEvents()
    toast = Toast.info(parent, "Lifecycle", duration=60_000)
    app.processEvents()

    if parent_action == "destroy":
        parent.deleteLater()
    else:
        getattr(parent, parent_action)()
    _flush_deferred_deletes(app)

    assert Toast._instance is None
    assert not isValid(toast)

    if isValid(parent):
        parent.deleteLater()
        _flush_deferred_deletes(app)


def test_toast_emits_one_accessibility_alert_per_instance(monkeypatch):
    """A visible toast announces one Alert without repeating after re-show."""
    app = QApplication.instance() or QApplication([])
    observed = []

    def record_accessibility_event(event):
        observed.append((event.type(), event.object()))

    monkeypatch.setattr(QAccessible, "updateAccessibility", record_accessibility_event)
    parent = QWidget()
    parent.show()
    app.processEvents()
    try:
        toast = Toast.info(parent, "Accessible", duration=60_000)
        app.processEvents()
        app.processEvents()

        assert observed == [(QAccessible.Event.Alert, toast)]

        toast.hide()
        toast.show()
        app.processEvents()
        app.processEvents()
        assert observed == [(QAccessible.Event.Alert, toast)]
    finally:
        if Toast._instance is not None and isValid(Toast._instance):
            Toast._instance.dismiss_immediately()
        parent.deleteLater()
        _flush_deferred_deletes(app)


def test_toast_tracks_parent_bottom_center_after_move_and_resize():
    """A Tool toast uses global coordinates and follows its parent geometry."""
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.setGeometry(80, 70, 520, 360)
    parent.show()
    app.processEvents()
    try:
        toast = Toast(parent, "Positioned")
        toast.show()
        app.processEvents()

        for geometry in ((120, 100, 520, 360), (160, 130, 360, 280)):
            parent.setGeometry(*geometry)
            app.processEvents()
            parent_rect = _global_rect(parent)
            toast_rect = _global_rect(toast)
            assert parent_rect.contains(toast_rect)
            assert abs(toast_rect.center().x() - parent_rect.center().x()) <= 1
            assert parent_rect.bottom() - toast_rect.bottom() == scaled_px(24)
    finally:
        toast.dismiss_immediately()
        parent.close()
        parent.deleteLater()
        app.processEvents()


def test_toast_long_text_is_stable_and_bounded_in_narrow_parent():
    """Long text wraps without escaping the parent or available screen."""
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    screen_rect = app.primaryScreen().availableGeometry()
    parent.setGeometry(screen_rect.right() - 179, screen_rect.top() + 40, 240, 420)
    parent.show()
    app.processEvents()
    try:
        message = "A long notification message that should wrap cleanly " * 3
        toast = Toast(parent, message, subtitle="Additional details also remain bounded.")
        toast.show()
        app.processEvents()

        parent_rect = _global_rect(parent)
        screen_rect = parent.screen().availableGeometry()
        placement_bounds = parent_rect.intersected(screen_rect)
        toast_rect = _global_rect(toast)
        expected_maximum = min(
            scaled_px(420), placement_bounds.width() - 2 * scaled_px(8)
        )
        assert toast.maximumWidth() == expected_maximum
        assert toast.width() <= expected_maximum
        assert parent_rect.contains(toast_rect)
        assert screen_rect.contains(toast_rect)

        stable_geometry = toast.geometry()
        app.processEvents()
        app.processEvents()
        assert toast.geometry() == stable_geometry
    finally:
        toast.dismiss_immediately()
        parent.close()
        parent.deleteLater()
        app.processEvents()


# ── EmptyPanel tests ──────────────────────────────────────────


def test_empty_panel_renders_with_subtitle():
    """EmptyPanel shows main label and subtitle with theme tokens."""
    app = QApplication.instance() or QApplication([])
    t = themes.get()
    panel = EmptyPanel()
    panel.resize(400, 200)
    panel.show()
    app.processEvents()
    try:
        labels = panel.findChildren(QLabel)
        texts = [lb.text() for lb in labels]
        # Main label
        assert "Empty" in texts
        # Default subtitle hint
        hint = t.get("panel.empty.hint", "")
        found = any("Drop files" in txt or hint in txt for txt in texts)
        assert found, f"Expected subtitle hint in labels, got {texts}"
    finally:
        panel.close()
        panel.deleteLater()
        app.processEvents()


def test_empty_panel_custom_subtitle():
    """EmptyPanel accepts a custom subtitle."""
    app = QApplication.instance() or QApplication([])
    panel = EmptyPanel(subtitle="No assets loaded")
    panel.resize(400, 200)
    panel.show()
    app.processEvents()
    try:
        labels = panel.findChildren(QLabel)
        texts = [lb.text() for lb in labels]
        assert "No assets loaded" in texts
    finally:
        panel.close()
        panel.deleteLater()
        app.processEvents()
