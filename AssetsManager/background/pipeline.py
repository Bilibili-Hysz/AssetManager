"""Image + effect -> processed image, GPU-first with a CPU fallback.

This is the *filter* layer only.  The wallpaper source is always a static
image; the whole-window composition stays the plain CPU ``paintEvent`` in
``MainWindow``, so the filtered image covers the full window (no native
QOpenGLWidget background layer, no video/程序化背景).

Decision (design D-3, D-4, D-5): try the offscreen GL pipeline; if GL is
unavailable, fall back to the CPU ``bg_effects`` chain for blur/mosaic/
kuwahara.  A "shader" effect is GL-only: without GL it degrades to the
unmodified image (never a black screen), with a warning.
"""
from __future__ import annotations

import logging
from typing import cast

from PySide6.QtGui import QImage, QOffscreenSurface, QOpenGLContext

from AssetsManager.background.cpu import render_chain
from AssetsManager.background.gl import presets
from AssetsManager.background.gl.renderer import GlPipeline
from AssetsManager.background.model import EffectChain

_log = logging.getLogger(__name__)


class ImageEffectRenderer:
    """Renders the image background effect chain, GL when possible."""

    def __init__(self) -> None:
        self._ctx: QOpenGLContext | None = None
        self._surface: QOffscreenSurface | None = None
        self._pipeline: GlPipeline | None = None
        self._gl_ready: bool | None = None  # None = not probed yet

    # ── GL bootstrap ──────────────────────────────────────────────────────

    def _ensure_gl(self) -> bool:
        """Create an offscreen context once; True when the pipeline is ready."""
        if self._gl_ready is not None:
            return self._gl_ready
        self._gl_ready = False
        try:
            surface = QOffscreenSurface()
            surface.create()
            if not surface.isValid():
                return False
            ctx = QOpenGLContext()
            if not ctx.create():
                return False
            if not ctx.makeCurrent(surface):
                return False
            pipeline = GlPipeline()
            ready = pipeline.ensure_ready()
            ctx.doneCurrent()
            if not ready:
                _log.warning("GL effect pipeline failed to compile: %s", pipeline.failure)
                return False
            self._surface = surface
            self._ctx = ctx
            self._pipeline = pipeline
            self._gl_ready = True
            return True
        except Exception:
            _log.exception("OpenGL effect pipeline unavailable; using CPU effects")
            self._gl_ready = False
            return False

    # ── public API ────────────────────────────────────────────────────────

    def render(
        self,
        image: QImage,
        effect: str,
        intensity: int,
        preset_key: str = "",
    ) -> QImage:
        """Apply ``effect`` to ``image`` and return the processed image.

        ``effect``: none / blur / mosaic / kuwahara / shader.
        ``preset_key``: only used when ``effect == 'shader'``.
        """
        if image is None or image.isNull():
            return image
        if effect not in ("none", "blur", "mosaic", "kuwahara", "shader"):
            effect = "none"
        chain = EffectChain.single(effect, intensity=intensity)

        if effect == "shader":
            return self._render_shader(image, intensity, preset_key)

        # blur / mosaic / kuwahara / none: GL first, then CPU.
        if self._ensure_gl() and self._pipeline is not None:
            try:
                if self._ctx is not None:
                    # _ctx and _surface are assigned together in _ensure_gl,
                    # so a live context implies a live surface.
                    self._ctx.makeCurrent(cast("QOffscreenSurface", self._surface))
                size = (image.width(), image.height())
                out = self._pipeline.render_still(image, chain, size)
                if self._ctx is not None:
                    self._ctx.doneCurrent()
                if out is not None:
                    return out
            except Exception:
                _log.exception("GL effect render failed; falling back to CPU")
                if self._ctx is not None:
                    self._ctx.doneCurrent()
        return render_chain(image, chain)

    def _render_shader(self, image: QImage, intensity: int, preset_key: str) -> QImage:
        key = presets.resolve(preset_key or "")
        snippet = presets.get_preset(key)
        if snippet is None:
            return image
        if not self._ensure_gl() or self._pipeline is None:
            _log.warning("shader effect requires OpenGL; showing unmodified image")
            return image
        try:
            if self._ctx is not None:
                # _ctx and _surface are assigned together in _ensure_gl,
                # so a live context implies a live surface.
                self._ctx.makeCurrent(cast("QOffscreenSurface", self._surface))
            size = (image.width(), image.height())
            out = self._pipeline.render_shader_preset(
                image, snippet.fragment, size, 0.0, intensity / 50.0
            )
            if self._ctx is not None:
                self._ctx.doneCurrent()
            return out if out is not None else image
        except Exception:
            _log.exception("shader effect render failed; showing unmodified image")
            if self._ctx is not None:
                self._ctx.doneCurrent()
            return image