import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout

from AssetsManager.core.settings import AppSettings
from AssetsManager.dialogs.tabbed_dialog import TabbedDialog
from AssetsManager.widgets.elevation import apply_elevation


class _VisualDialog(TabbedDialog):
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Visual test"))


def test_dialog_fade_respects_reduce_motion_setting():
    app = QApplication.instance() or QApplication([])
    settings = AppSettings.instance()
    original = settings.get("reduce_motion", False)
    settings.set("reduce_motion", True)
    dialog = _VisualDialog(min_size=(240, 120))
    try:
        dialog.show()
        app.processEvents()
        assert dialog.windowOpacity() == 1.0
        assert dialog._dialog_fade_anim is None
    finally:
        settings.set("reduce_motion", original)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_elevation_reuses_existing_graphics_effect():
    app = QApplication.instance() or QApplication([])
    from PySide6.QtWidgets import QWidget

    widget = QWidget()
    try:
        first = apply_elevation(widget, level=1)
        second = apply_elevation(widget, level=2)
        assert first is second
        assert widget.graphicsEffect() is first
        assert second.blurRadius() > 0
    finally:
        widget.deleteLater()
        app.processEvents()
