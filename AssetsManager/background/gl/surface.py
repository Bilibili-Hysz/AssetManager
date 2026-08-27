"""GPU background canvas — the GL backend's host widget.

``BackgroundSurface`` is a QOpenGLWidget placed as the main-window central
widget when the BackgroundManager selects the GL backend (video / shader /
image+shader).  The file-list panel is re-parented *inside* this widget; Qt
composites regular child widgets above the GL content, which is exactly the
hybrid mount point validated in the design doc §10.1 (risk R-1 spike).

Fallbacks (design D-3): any GL failure is reported through
:attr:`rendering_failed` and the window manager reverts to the CPU backend.
"""
from __future__ import annotations

from PySide6.QtCore import QElapsedTimer, Signal
from PySide6.QtGui import QImage
from PySide6.QtOpenGL import QOpenGLTexture
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from AssetsManager.background.gl.renderer import GlPipeline
from AssetsManager.background.model import BackendPlan
from AssetsManager.background.sources import VideoSource


class BackgroundSurface(QOpenGLWidget):
    rendering_failed = Signal(str)
    visibility_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pipeline = GlPipeline()
        self._plan: BackendPlan | None = None
        self._video: VideoSource | None = None
        self._source_image: QImage | None = None  # image+shader -> iChannel0
        self._source_image_key: int = 0
        self._still_image: QImage | None = None  # GL still path (convenience)
        self._frame_texture: QOpenGLTexture | None = None
        self._still_texture: QOpenGLTexture | None = None
        self._elapsed = QElapsedTimer()
        self._elapsed.start()
        self._time_sec = 0.0
        self._gl_ok = False
        self.setMinimumSize(320, 200)
        # Child-host container: the file-list panel fills the GL canvas.
        from PySide6.QtWidgets import QVBoxLayout

        self._host_layout = QVBoxLayout(self)
        self._host_layout.setContentsMargins(0, 0, 0, 0)
        self._host_layout.setSpacing(0)

    # ── public API ───────────────────────────────────────────────────────

    def set_plan(self, plan: BackendPlan) -> None:
        self._plan = plan
        self._stop_video()
        if plan.source_kind == "video" and plan.backend == "gl" and plan.source_path:
            self._video = VideoSource(plan.source_path)
            self._video.frame_ready.connect(self._on_frame)
            self._video.start()
        self.update()

    def set_source_image(self, image: QImage | None) -> None:
        self._source_image = image
        self.update()

    def cleanup(self) -> None:
        self._stop_video()
        if self._frame_texture is not None:
            self._frame_texture.destroy()
            self._frame_texture = None
        if self._still_texture is not None:
            self._still_texture.destroy()
            self._still_texture = None

    def _on_frame(self, _image: QImage) -> None:
        self.update()

    def _stop_video(self) -> None:
        if self._video is not None:
            self._video.stop()
            self._video.deleteLater()
            self._video = None

    # ── QOpenGLWidget overrides ──────────────────────────────────────────

    def initializeGL(self) -> None:
        self._gl_ok = self._pipeline.ensure_ready()
        if not self._gl_ok:
            self.rendering_failed.emit(self._pipeline.failure or "GL init failed")

    def paintGL(self) -> None:
        if not self._gl_ok or self._plan is None:
            return
        size = (max(1, self.width()), max(1, self.height()))
        if self.isVisible():
            self._time_sec = self._elapsed.elapsed() / 1000.0
        if self._plan.source_kind == "shader":
            self._draw_shader(size)
        elif self._plan.source_kind == "video":
            self._draw_video(size)
        else:
            self._draw_still(size)

    def _draw_shader(self, size: tuple[int, int]) -> None:
        from AssetsManager.background.gl import presets

        key = presets.resolve(self._plan.shader_preset or "")
        snippet = presets.get_preset(key)
        if snippet is None:
            return
        tex_id: int | None = None
        if self._source_image is not None and not self._source_image.isNull():
            image_key = self._source_image.cacheKey()
            if self._frame_texture is None or image_key != self._source_image_key:
                if self._frame_texture is not None:
                    self._frame_texture.destroy()
                    self._frame_texture = None
                self._frame_texture = self._pipeline.upload_image(self._source_image)
                self._source_image_key = image_key
            if self._frame_texture is not None:
                tex_id = self._frame_texture.textureId()
        self._pipeline.draw_shadertoy(
            snippet.fragment, size, self._time_sec,
            float(self._plan.chain.effects[0].intensity if self._plan.chain.effects else 0) / 50.0,
            {0: tex_id} if tex_id is not None else None,
        )

    def _draw_video(self, size: tuple[int, int]) -> None:
        frame = self._video.current_frame() if self._video is not None else None
        if frame is None:
            return
        tex = self._pipeline.upload_image(frame)
        if tex is None:
            return
        final = self._pipeline._apply_chain_to_fbo(tex.textureId(), size, self._plan.chain)
        if final is not None:
            self._pipeline.draw_texture(final.texture(), size)
        else:
            self._pipeline.draw_texture(tex.textureId(), size)
        tex.destroy()

    def _draw_still(self, size: tuple[int, int]) -> None:
        if self._still_image is None:
            return
        if self._still_texture is None:
            self._still_texture = self._pipeline.upload_image(self._still_image)
        if self._still_texture is not None:
            self._pipeline.draw_texture(self._still_texture.textureId(), size)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.visibility_changed.emit(self.isVisible())

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.visibility_changed.emit(False)

    def resizeGL(self, width: int, height: int) -> None:
        pass  # viewport is set per draw; the still texture refits lazily