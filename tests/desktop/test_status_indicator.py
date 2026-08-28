"""Tests for StatusIndicator widget and EmptyPanel factory helpers."""


from PySide6.QtWidgets import QApplication, QLabel

from AssetsManager.core import themes
from AssetsManager.core.settings import AppSettings
from AssetsManager.panels.empty import EmptyPanel
from AssetsManager.widgets.status_indicator import StatusIndicator


# ── StatusIndicator tests ────────────────────────────────────


def test_status_indicator_renders_idle():
    """StatusIndicator with idle state shows no icon."""
    app = QApplication.instance() or QApplication([])
    ind = StatusIndicator("idle", title="Ready")
    ind.show()
    app.processEvents()
    try:
        assert ind.isVisible()
        assert ind._icon_name == ""
        assert ind._icon_label.pixmap().isNull()
        assert ind._title_label.text() == "Ready"
        assert "Idle" in ind.accessibleName()
        assert "Ready" in ind.accessibleName()
    finally:
        ind.close()
        ind.deleteLater()
        app.processEvents()


def test_status_indicator_loading_shows_icon_and_starts_pulse():
    """Loading state uses a semantic icon and starts pulse animation."""
    app = QApplication.instance() or QApplication([])
    ind = StatusIndicator("loading", title="Scanning…")
    ind.show()
    app.processEvents()
    try:
        assert ind._icon_name == "clock"
        assert not ind._icon_label.pixmap().isNull()
        assert ind._title_label.text() == "Scanning…"
        assert ind._icon_label.accessibleName() == "Loading"
        # Pulse animation should be running (unless reduce_motion)
        settings = AppSettings.instance()
        if not settings.get("reduce_motion", False):
            assert ind._pulse_anim.state() == ind._pulse_anim.State.Running
    finally:
        ind.close()
        ind.deleteLater()
        app.processEvents()


def test_status_indicator_error_uses_danger_color():
    """Error state uses danger token for icon color."""
    app = QApplication.instance() or QApplication([])
    t = themes.get()
    ind = StatusIndicator("error", title="Failed")
    ind.show()
    app.processEvents()
    try:
        assert ind._icon_name == "close"
        assert not ind._icon_label.pixmap().isNull()
        assert ind._icon_color == t["danger"]
    finally:
        ind.close()
        ind.deleteLater()
        app.processEvents()


def test_status_indicator_retry_uses_warning_color():
    """Retry state uses warning token for icon color."""
    app = QApplication.instance() or QApplication([])
    t = themes.get()
    ind = StatusIndicator("retry", title="Try again?")
    ind.show()
    app.processEvents()
    try:
        assert ind._icon_name == "refresh"
        assert not ind._icon_label.pixmap().isNull()
        assert ind._icon_color == t["warning"]
    finally:
        ind.close()
        ind.deleteLater()
        app.processEvents()


def test_status_indicator_set_status_switches():
    """set_status() changes icon, title, subtitle, and animation."""
    app = QApplication.instance() or QApplication([])
    ind = StatusIndicator("idle", title="Start")
    ind.show()
    app.processEvents()
    try:
        ind.set_status("loading", title="Working…", subtitle="Please wait")
        app.processEvents()
        assert ind._icon_name == "clock"
        assert ind._title_label.text() == "Working…"
        assert ind._subtitle_label.text() == "Please wait"
        assert ind.accessibleName() == "Loading: Working…"
        assert ind.accessibleDescription() == "Please wait"

        ind.set_status("success", title="Done!", subtitle="All clear")
        app.processEvents()
        assert ind._icon_name == "check"
        assert not ind._icon_label.pixmap().isNull()
        assert ind._title_label.text() == "Done!"
        # Pulse should stop on non-loading states
        assert ind._pulse_anim.state() != ind._pulse_anim.State.Running
    finally:
        ind.close()
        ind.deleteLater()
        app.processEvents()


def test_status_indicator_reduce_motion_skips_pulse():
    """Loading state skips pulse animation when reduce_motion is active."""
    app = QApplication.instance() or QApplication([])
    settings = AppSettings.instance()
    original = settings.get("reduce_motion", False)
    settings.set("reduce_motion", True)
    try:
        ind = StatusIndicator("loading", title="Working…")
        ind.show()
        app.processEvents()
        assert ind._pulse_anim.state() != ind._pulse_anim.State.Running
    finally:
        settings.set("reduce_motion", original)
        ind.close()
        ind.deleteLater()
        app.processEvents()


def test_status_indicator_success_uses_success_color():
    """Success state uses success token for icon color."""
    app = QApplication.instance() or QApplication([])
    t = themes.get()
    ind = StatusIndicator("success", title="Complete")
    ind.show()
    app.processEvents()
    try:
        assert ind._icon_name == "check"
        assert ind._icon_color == t["success"]
    finally:
        ind.close()
        ind.deleteLater()
        app.processEvents()


def test_status_indicator_icon_is_horizontally_centered():
    """The fixed-size icon label is centered in the full widget width."""
    app = QApplication.instance() or QApplication([])
    ind = StatusIndicator("loading", title="Centered")
    ind.resize(320, 180)
    ind.show()
    app.processEvents()
    try:
        icon_center = ind._icon_label.geometry().center().x()
        widget_center = ind.rect().center().x()
        assert abs(icon_center - widget_center) <= 1
    finally:
        ind.close()
        ind.deleteLater()
        app.processEvents()


def test_status_indicator_refresh_theme_preserves_state_and_text():
    """Theme refresh redraws without losing the current semantic state."""
    app = QApplication.instance() or QApplication([])
    ind = StatusIndicator("error", title="Failed", subtitle="Try later")
    ind.show()
    app.processEvents()
    try:
        ind.refresh_theme()
        app.processEvents()
        assert ind._status == "error"
        assert ind._title == "Failed"
        assert ind._subtitle == "Try later"
        assert ind._icon_name == "close"
        assert not ind._icon_label.pixmap().isNull()
        assert ind.accessibleName() == "Error: Failed"
    finally:
        ind.close()
        ind.deleteLater()
        app.processEvents()


def test_status_indicator_refresh_scale_updates_all_scaled_metrics():
    """A live 1x -> 2x refresh resizes chrome, text, and the icon canvas."""
    app = QApplication.instance() or QApplication([])
    settings = AppSettings.instance()
    original_scale = settings.get("ui_scale", 1.0)
    settings.set("ui_scale", 1.0)
    ind = StatusIndicator("loading", title="Scaling", subtitle="Details")
    ind.show()
    app.processEvents()
    try:
        assert ind.minimumHeight() == 100
        assert ind._icon_label.size().width() == 32
        assert ind.layout().spacing() == 6

        settings.set("ui_scale", 2.0)
        ind.refresh_scale()
        app.processEvents()

        pixmap = ind._icon_label.pixmap()
        margins = ind.layout().contentsMargins()
        assert ind.minimumHeight() == 200
        assert ind._icon_label.size().width() == 64
        assert ind._icon_label.size().height() == 64
        assert ind.layout().spacing() == 12
        assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (
            0, 0, 0, 0)
        assert pixmap.width() == 48
        assert pixmap.height() == 48
        assert pixmap.width() <= ind._icon_label.width()
        assert pixmap.height() <= ind._icon_label.height()
        assert "font-size: 28px" in ind._title_label.styleSheet()
        assert "font-size: 24px" in ind._subtitle_label.styleSheet()
    finally:
        settings.set("ui_scale", original_scale)
        ind.close()
        ind.deleteLater()
        app.processEvents()


def test_status_indicator_loading_pulse_tracks_hide_close_and_show():
    """Loading pulse stops off-screen and resumes when the widget is shown."""
    app = QApplication.instance() or QApplication([])
    settings = AppSettings.instance()
    original = settings.get("reduce_motion", False)
    settings.set("reduce_motion", False)
    ind = StatusIndicator("loading", title="Working…")
    try:
        ind.show()
        app.processEvents()
        assert ind._pulse_anim.state() == ind._pulse_anim.State.Running

        ind.hide()
        app.processEvents()
        assert ind._pulse_anim.state() != ind._pulse_anim.State.Running

        ind.show()
        app.processEvents()
        assert ind._pulse_anim.state() == ind._pulse_anim.State.Running

        ind.close()
        app.processEvents()
        assert ind._pulse_anim.state() != ind._pulse_anim.State.Running

        ind.show()
        app.processEvents()
        assert ind._pulse_anim.state() == ind._pulse_anim.State.Running
    finally:
        settings.set("reduce_motion", original)
        ind.close()
        ind.deleteLater()
        app.processEvents()


def test_status_indicator_refresh_motion_preference_updates_live_pulse():
    """The explicit motion refresh applies preference changes at runtime."""
    app = QApplication.instance() or QApplication([])
    settings = AppSettings.instance()
    original = settings.get("reduce_motion", False)
    settings.set("reduce_motion", False)
    ind = StatusIndicator("loading", title="Working…")
    ind.show()
    app.processEvents()
    try:
        assert ind._pulse_anim.state() == ind._pulse_anim.State.Running

        settings.set("reduce_motion", True)
        ind.refresh_motion_preference()
        assert ind._pulse_anim.state() != ind._pulse_anim.State.Running

        settings.set("reduce_motion", False)
        ind.refresh_motion_preference()
        assert ind._pulse_anim.state() == ind._pulse_anim.State.Running

        ind.set_status("success")
        ind.refresh_motion_preference()
        assert ind._pulse_anim.state() != ind._pulse_anim.State.Running
    finally:
        settings.set("reduce_motion", original)
        ind.close()
        ind.deleteLater()
        app.processEvents()


# ── EmptyPanel factory tests ─────────────────────────────────


def test_empty_panel_for_loading():
    """for_loading() returns panel with accent-colored loading text."""
    app = QApplication.instance() or QApplication([])
    t = themes.get()
    panel = EmptyPanel.for_loading()
    panel.resize(400, 200)
    panel.show()
    app.processEvents()
    try:
        labels = panel.findChildren(QLabel)
        texts = [lb.text() for lb in labels]
        # Should contain "Loading…" text
        assert any("Loading" in txt or "加载" in txt or "読み込" in txt
                    for txt in texts), f"Expected loading text in {texts}"
        # The main label should use accent color
        main_labels = [lb for lb in labels
                       if "Loading" in lb.text() or "加载" in lb.text()
                       or "読み込" in lb.text()]
        assert len(main_labels) >= 1
        ss = main_labels[0].styleSheet()
        assert t["accent"] in ss
    finally:
        panel.close()
        panel.deleteLater()
        app.processEvents()


def test_empty_panel_for_error():
    """for_error() returns panel with danger-colored error text."""
    app = QApplication.instance() or QApplication([])
    t = themes.get()
    panel = EmptyPanel.for_error(message="Network timeout")
    panel.resize(400, 200)
    panel.show()
    app.processEvents()
    try:
        labels = panel.findChildren(QLabel)
        texts = [lb.text() for lb in labels]
        assert "Network timeout" in texts
        # Main label should use danger color
        err_labels = [lb for lb in labels if lb.text() == "Network timeout"]
        assert len(err_labels) >= 1
        ss = err_labels[0].styleSheet()
        assert t["danger"] in ss
    finally:
        panel.close()
        panel.deleteLater()
        app.processEvents()


def test_empty_panel_for_error_default_message():
    """for_error() without message uses i18n default."""
    app = QApplication.instance() or QApplication([])
    panel = EmptyPanel.for_error()
    panel.resize(400, 200)
    panel.show()
    app.processEvents()
    try:
        labels = panel.findChildren(QLabel)
        texts = [lb.text() for lb in labels]
        # Should have the error text (from i18n or fallback)
        has_error = any("Error" in txt or "错误" in txt or "エラー" in txt
                        for txt in texts)
        assert has_error, f"Expected error text in {texts}"
    finally:
        panel.close()
        panel.deleteLater()
        app.processEvents()
