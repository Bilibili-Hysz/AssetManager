"""GL smoke tests (design doc §7: FBO 冒烟 — skipped when GL is unavailable).

Runs only when a real OpenGL context can be created; otherwise pytest.skip.
Guards the regressions fixed in the M2 implementation: QOpenGLContext API,
VBO creation, uniform handling, the passthrough draw path, HiDPI viewport
sizing and image orientation through the FBO readback.
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
        # then read the center pixel back.  The viewport must match the
        # device-pixel framebuffer size (paintGL now does exactly this).
        from PySide6.QtGui import QOpenGLContext

        gl = QOpenGLContext.currentContext().functions()
        dpr = gl_surface.devicePixelRatioF()
        size = (max(1, round(gl_surface.width() * dpr)),
                max(1, round(gl_surface.height() * dpr)))
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


def test_fbo_smoke_orientation_preserved(gl_surface):
    """A bright-top image must come out of the FBO readback bright-top."""
    pipeline = gl_surface._pipeline
    assert pipeline.ensure_ready(), pipeline.failure
    img = QImage(128, 96, QImage.Format.Format_RGB32)
    img.fill(QColor(0, 0, 0))
    for y in range(48):
        for x in range(128):
            img.setPixelColor(x, y, QColor(255, 255, 255))

    out = pipeline.render_still(img, EffectChain.single("blur", intensity=4), (128, 96))
    assert out is not None

    def lum(qimg, frac):
        y = int((qimg.height() - 1) * frac)
        total = n = 0
        for x in range(0, qimg.width(), 3):
            c = qimg.pixelColor(x, y)
            total += (c.red() + c.green() + c.blue()) / 3.0
            n += 1
        return total / n

    top, bottom = lum(out, 0.1), lum(out, 0.9)
    # one flip on upload, none on readback -> upright (bright stays on top)
    assert top > 150, (top, bottom)
    assert bottom < 100, (top, bottom)


def test_shadertoy_presets_render_non_black(gl_surface):
    """Every built-in preset compiles and draws non-black content (M4)."""
    from AssetsManager.background.gl import presets

    pipeline = gl_surface._pipeline
    assert pipeline.ensure_ready(), pipeline.failure
    for key in presets.preset_keys():
        snippet = presets.get_preset(key)
        assert snippet is not None
        ok = pipeline.draw_shadertoy(
            snippet.fragment, (160, 120), time_sec=1.0, strength=0.5, channels=None
        )
        assert ok, f"preset {key} failed to draw"
        # read a small region back and require some color variance/energy
        from PySide6.QtGui import QOpenGLContext

        gl = QOpenGLContext.currentContext().functions()
        buf = memoryview(bytearray(4 * 32))
        gl.glReadPixels(64, 44, 32, 1, 0x1908, 0x1401, buf)
        n = sum(1 for i in range(0, 4 * 32, 4) if (buf[i] + buf[i + 1] + buf[i + 2]) > 30)
        assert n > 8, f"preset {key} rendered blank"