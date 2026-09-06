"""MainWindow 启动淡入 — reduce_motion 遵循 + 时长具名化（V07）。

showEvent 的首显淡入此前无条件 300ms：不检查 reduce_motion（TabbedDialog
的 ``_start_dialog_fade`` 已有检查先例）、时长为裸字面量。V07 修法：

* ``reduce_motion=True`` → 直接 ``setWindowOpacity(1.0)`` 跳过动画（中断
  语义：窗口立即完全不透明），完全不构造动画对象；
* ``reduce_motion=False`` → 动画正常启动，时长 = ``themes.motion("slow")``
  （档位表 slow=300，零漂移）。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QAbstractAnimation
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QApplication, QMainWindow

from AssetsManager import window as window_module
from AssetsManager.core import themes
from AssetsManager.window import MainWindow


class _FadeHost(MainWindow):
    """Bare MainWindow shell exercising showEvent without the bootstrap.

    ``MainWindow.__init__`` builds the full docking workspace; the startup
    fade path only touches ``_startup_anim_done`` / ``_startup_anim``, so
    the host skips it deliberately. ``closeEvent`` is neutered for the same
    reason (MainWindow's resource shutdown expects a bootstrapped window).
    """

    def __init__(self):
        QMainWindow.__init__(self)
        self._startup_anim_done = False
        self._startup_anim = None

    def closeEvent(self, event):
        event.accept()


def _make_host(monkeypatch, reduce_motion: bool) -> _FadeHost:
    monkeypatch.setattr(
        window_module.StyleKit, "reduce_motion", staticmethod(lambda: reduce_motion)
    )
    return _FadeHost()


def _teardown(host: _FadeHost) -> None:
    app = QApplication.instance()
    if host._startup_anim is not None:
        host._startup_anim.stop()
    host.deleteLater()
    if app is not None:
        app.processEvents()


def test_startup_fade_skipped_under_reduce_motion(monkeypatch):
    host = _make_host(monkeypatch, True)
    try:
        def _no_animation(*_args, **_kwargs):
            raise AssertionError(
                "startup fade must not construct an animation under reduce_motion")

        monkeypatch.setattr(window_module, "QPropertyAnimation", _no_animation)

        host.showEvent(QShowEvent())

        assert host.windowOpacity() == 1.0
        assert host._startup_anim is None
        assert host._startup_anim_done is True
    finally:
        _teardown(host)


def test_startup_fade_runs_with_named_slow_duration(monkeypatch):
    host = _make_host(monkeypatch, False)
    try:
        host.showEvent(QShowEvent())

        anim = host._startup_anim
        assert anim is not None
        # Duration comes from the named tier, not a bare literal.
        assert anim.duration() == themes.motion("slow")
        assert anim.startValue() == 0.0
        assert anim.endValue() == 1.0
        assert anim.state() == QAbstractAnimation.State.Running
        # The fade starts from transparent.
        assert host.windowOpacity() == 0.0
    finally:
        _teardown(host)
