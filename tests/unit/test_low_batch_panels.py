"""Panel-layer defect regression tests (batch D: tag_tree / sidebar / image_viewer).

All tests run headless (offscreen platform) with a lazily created QApplication,
mirroring the pattern used by tests/desktop/*.py.
"""
import os
import time
from pathlib import Path
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QWheelEvent
from PySide6.QtWidgets import QApplication, QWidget

from AssetsManager.panels.image_viewer import (
    MAX_DIM, ImageViewerOverlay, _GraphicsView,
)
from AssetsManager.panels.sidebar import _PreloadTask
from AssetsManager.panels.tag_tree import TagTreePanel


def _app():
    return QApplication.instance() or QApplication([])


def _make_png(path, w, h):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(Qt.GlobalColor.white)
    assert img.save(str(path)), f"failed to save test image {path}"
    return path


def _wait_for_state(app, viewer, state, timeout=5.0):
    """Pump the event loop until the viewer reaches *state* (async decode)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if viewer._state == state:
            return True
        time.sleep(0.005)
    app.processEvents()
    return viewer._state == state


# ── tag_tree: _populate refresh after mutations (A1) ───────────────

def test_tag_tree_populate_is_idempotent():
    _app()
    panel = TagTreePanel()
    try:
        ctrl = Mock()
        ctrl.get_tag_with_files.return_value = [
            {"tag": "hero", "count": 1, "files": [str(Path("C:/x/a.txt"))], "icon": ""},
        ]
        panel._controller = ctrl
        panel._populate()
        assert panel._tree.topLevelItemCount() == 1
        # Second call must not raise or duplicate items.
        panel._populate()
        assert panel._tree.topLevelItemCount() == 1
        _app().processEvents()  # flush the deferred update-batch restore
        assert panel._tree_update_restore_pending is False
    finally:
        panel.shutdown()
        panel.deleteLater()
        _app().processEvents()


def test_tag_tree_file_click_emits_directory_selected():
    _app()
    panel = TagTreePanel()
    try:
        file_path = str(Path("C:/lib/a.txt"))
        ctrl = Mock()
        ctrl.get_tag_with_files.return_value = [
            {"tag": "hero", "count": 1, "files": [file_path], "icon": ""},
        ]
        panel._controller = ctrl
        panel._populate()
        emitted = []
        panel.directory_selected.connect(emitted.append)

        top = panel._tree.topLevelItem(0)
        child = top.child(0)
        assert child is not None
        panel._on_click(child, 0)

        assert emitted == [file_path]
    finally:
        panel.shutdown()
        panel.deleteLater()
        _app().processEvents()


def test_tag_browser_dialog_forwards_file_click(monkeypatch):
    _app()
    from AssetsManager.dialogs.tag_browser_dialog import TagBrowserDialog
    from AssetsManager.panels.tag_tree import TagTreePanel

    # Avoid the controller/tag-store query during construction; the dialog
    # only needs the panel to exist for the forwarding assertion.
    monkeypatch.setattr(TagTreePanel, "set_scoped_services", lambda self, services, **kw: None)
    dlg = TagBrowserDialog(object())
    try:
        emitted = []
        dlg.directory_selected.connect(emitted.append)
        dlg._on_file_selected("C:/lib/a.png")
        assert emitted == ["C:/lib/a.png"]
    finally:
        dlg.close()
        dlg.deleteLater()
        _app().processEvents()


def test_tag_tree_rename_refreshes_tree(monkeypatch):
    _app()
    panel = TagTreePanel()
    try:
        ctrl = Mock()
        ctrl.get_tag_with_files.return_value = []
        panel._controller = ctrl
        populated = []
        monkeypatch.setattr(panel, "_populate", lambda: populated.append(True))

        class _FakeInput:
            @staticmethod
            def getText(*args, **kwargs):
                return ("new_name", True)

        monkeypatch.setattr("AssetsManager.panels.tag_tree.QInputDialog", _FakeInput)
        panel._rename_tag("old_name")

        ctrl.rename_tag.assert_called_once_with("old_name", "new_name")
        assert populated == [True]
    finally:
        panel.shutdown()
        panel.deleteLater()
        _app().processEvents()


def test_tag_tree_delete_refreshes_tree(monkeypatch):
    _app()
    panel = TagTreePanel()
    try:
        ctrl = Mock()
        ctrl.get_tag_with_files.return_value = []
        ctrl.get_files_for_tag.return_value = ["C:/x/a.txt"]
        panel._controller = ctrl
        populated = []
        monkeypatch.setattr(panel, "_populate", lambda: populated.append(True))

        class _FakeMsgBox:
            class StandardButton:
                Yes = 1
                No = 2

            @staticmethod
            def question(*args, **kwargs):
                return _FakeMsgBox.StandardButton.Yes

        monkeypatch.setattr("AssetsManager.panels.tag_tree.QMessageBox", _FakeMsgBox)
        panel._delete_tag("old_tag")

        ctrl.delete_tag.assert_called_once_with("old_tag")
        assert populated == [True]
    finally:
        panel.shutdown()
        panel.deleteLater()
        _app().processEvents()


def test_tag_tree_remove_tag_refreshes_tree():
    _app()
    panel = TagTreePanel()
    try:
        ctrl = Mock()
        ctrl.get_tag_with_files.return_value = []
        panel._controller = ctrl
        populated = []
        panel._populate = lambda: populated.append(True)  # type: ignore[method-assign]

        panel._remove_tag("C:/x/a.txt", "hero")

        ctrl.remove_tag_from_file.assert_called_once_with("C:/x/a.txt", "hero")
        assert populated == [True]
    finally:
        panel.shutdown()
        panel.deleteLater()
        _app().processEvents()


def test_tag_tree_set_library_root_without_services(tmp_path):
    _app()
    panel = TagTreePanel()
    try:
        panel.set_library_root(str(tmp_path))
        assert panel._library_root == str(Path(tmp_path).resolve())
        assert panel._controller is None
        panel._populate()  # no controller: safe no-op
    finally:
        panel.shutdown()
        panel.deleteLater()
        _app().processEvents()


# ── image_viewer: downsampling (C1), dir cache (C2), zoom clamp (C3) ─

def test_viewer_downsamples_large_images(tmp_path):
    app = _app()
    png = _make_png(tmp_path / "big.png", 3000, 2000)
    host = QWidget()
    viewer = ImageViewerOverlay(host)
    try:
        viewer.load_image(str(png))
        assert _wait_for_state(app, viewer, "ready")
        assert viewer._pixmap is not None
        w, h = viewer._pixmap.width(), viewer._pixmap.height()
        assert w <= MAX_DIM and h <= MAX_DIM
        assert abs(w / h - 1.5) < 0.01  # 3000x2000 aspect preserved
    finally:
        viewer.close()
        host.deleteLater()
        _app().processEvents()


def test_viewer_directory_scan_is_cached_per_directory(monkeypatch, tmp_path):
    _app()
    _make_png(tmp_path / "a.png", 64, 64)
    _make_png(tmp_path / "b.png", 64, 64)

    real_scandir = os.scandir
    calls = {"n": 0}

    def counting_scandir(path):
        calls["n"] += 1
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", counting_scandir)
    host = QWidget()
    viewer = ImageViewerOverlay(host)
    try:
        viewer.load_image(str(tmp_path / "a.png"))
        assert calls["n"] == 1
        # Same directory, unchanged -> cached list, no rescan.
        viewer.load_image(str(tmp_path / "b.png"))
        assert calls["n"] == 1
        assert len(viewer._dir_list_cache) == 1
        # A new file changes the directory mtime -> rescan and rebuild.
        time.sleep(0.02)
        _make_png(tmp_path / "c.png", 64, 64)
        time.sleep(0.02)
        viewer.load_image(str(tmp_path / "c.png"))
        assert calls["n"] == 2
        assert len(viewer._dir_list_cache) == 1
        assert "c.png" in [Path(p).name for p in viewer._image_list]
    finally:
        viewer.close()
        host.deleteLater()
        _app().processEvents()


def _wheel_event(dy):
    return QWheelEvent(
        QPointF(50, 50), QPointF(50, 50),
        QPoint(0, 0), QPoint(0, dy),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate, False,
    )


def test_viewer_wheel_zoom_is_clamped():
    _app()
    view = _GraphicsView()
    try:
        for _ in range(300):
            view.wheelEvent(_wheel_event(120))
        assert abs(view.transform().m11() - 64.0) < 1e-9
        for _ in range(300):
            view.wheelEvent(_wheel_event(-120))
        assert abs(view.transform().m11() - 0.05) < 1e-9
    finally:
        view.deleteLater()
        _app().processEvents()


# ── sidebar: _PreloadTask lifetime (B1) ────────────────────────────

def test_preload_task_autodelete_and_run(tmp_path):
    _app()
    (tmp_path / "a.txt").write_text("x")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.txt").write_text("y")

    task = _PreloadTask([str(tmp_path)], "query", 1, str(tmp_path), max_depth=2)
    task2 = _PreloadTask([str(tmp_path)], "query", 2, str(tmp_path), max_depth=1)
    try:
        # The pool must be able to reclaim the C++ runnable after run() so a
        # replaced task (self._preload_task = None) cannot leak.
        assert task.autoDelete() is True
        assert task2.autoDelete() is True
        # Direct execution (no pool): scanning must not raise, and emitting
        # done with no receivers must be harmless.
        task.run()
        task2.run()
    finally:
        _app().processEvents()
