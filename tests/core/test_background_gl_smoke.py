"""GL smoke tests (design doc §7: FBO 冒烟 — skipped when GL is unavailable).

Runs only when a real OpenGL context can be created; otherwise pytest.skip.
Guards the regressions fixed in the M2 implementation: QOpenGLContext API,
VBO creation, uniform handling and the passthrough draw path.
"""
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget

from AssetsManager.background.gl.surface import BackgroundSurface
from AssetsManager.background.model import EffectChain


@pytest.fixture()
def gl_surface(_ensure_qapp):
    """A shown BackgroundSurface with a live GL context, or skip."""
    from AssetsManager.background.gl import probe

    if not probe.gl_available():
        pytest.skip("no OpenGL context available on this machine")
    app = QApplication.instance()
    win = QMainWindow()
    host = QWidget(win)
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    win.setCentralWidget(host)
    surface = BackgroundSurface(win)
    lay.addWidget(surface)
    win.resize(320, 240)
    win.show()
    for _ in range(50):
        app.processEvents()
        time.sleep(0.005)
    surface.makeCurrent()
    yield surface
    surface.doneCurrent()
    surface.cleanup()
    win.close()
    app.processEvents()


def test_fbo_smoke_passthrough_and_blur_readback(gl_surface):
    """Render a known solid color; passthrough must read it back unchanged."""
    pipeline = gl_surface._pipeline
    assert pipeline.ensure_ready(), pipeline.failure

    img = QImage(64, 48, QImage.Format.Format_RGB32)
    img.fill(QColor(220, 40, 40))

    # passthrough / no-op chain like the video fallback path
    out = pipeline.render_still(img, EffectChain.single("none", intensity=0), (64, 48))
    assert out is not None
    px = out.pixelColor(32, 24)
    assert (px.red(), px.green(), px.blue()) == (220, 40, 40), px.getRgb()

    # blur chain keeps the solid color (uniform input)
    out = pipeline.render_still(img, EffectChain.single("blur", intensity=8), (64, 48))
    assert out is not None
    px = out.pixelColor(32, 24)
    assert (px.red(), px.green(), px.blue()) == (220, 40, 40), px.getRgb()


def test_fbo_smoke_draw_texture_to_default_fb(gl_surface):
    """draw_texture (video passthrough path) actually paints the quad."""
    pipeline = gl_surface._pipeline
    assert pipeline.ensure_ready(), pipeline.failure
    img = QImage(64, 48, QImage.Format.Format_RGB32)
    img.fill(QColor(60, 180, 60))
    tex = pipeline.upload_image(img)
    assert tex is not None
    try:
        # Draw to the default framebuffer (what paintGL does for video),
        # then read the center pixel back.
        from PySide6.QtGui import QOpenGLContext

        gl = QOpenGLContext.currentContext().functions()
        size = (gl_surface.width(), gl_surface.height())
        gl.glViewport(0, 0, size[0], size[1])
        pipeline.draw_texture(tex.textureId(), size)
        gl.glFinish()

        # read back from the default framebuffer with a memoryview buffer
        buf = memoryview(bytearray(4))
        # format RGBA=0x1908, type UNSIGNED_BYTE=0x1401
        gl.glReadPixels(size[0] // 2, size[1] // 2, 1, 1, 0x1908, 0x1401, buf)
        r, g, b = buf[0], buf[1], buf[2]
        # green channel dominant (allow color-space tolerance)
        assert g > 100 and g > r * 2, (r, g, b)
    finally:
        tex.destroy()