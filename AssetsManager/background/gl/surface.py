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
        self._video_texture: QOpenGLTexture | None = None
        self._video_texture_key: int = 0
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
        same_video = (
            self._video is not None
            and plan.source_kind == "video"
            and plan.backend == "gl"
            and plan.source_path
            and self._video.path == plan.source_path
        )
        if not same_video:
            self._stop_video()
            if plan.source_kind == "video" and plan.backend == "gl" and plan.source_path:
                self._video = VideoSource(plan.source_path)
                self._video.frame_ready.connect(self._on_frame)
                self._video.state_changed.connect(self._on_video_state)
                self._video.start()
        self._plan = plan
        self.update()

    def set_source_image(self, image: QImage | None) -> None:
        # Keep the still path and the iChannel0 texture in sync.
        self._source_image = image
        if self._still_image is not image:
            if self._still_texture is not None:
                self._still_texture.destroy()
                self._still_texture = None
            self._still_image = image
        self.update()

    def cleanup(self) -> None:
        self._stop_video()
        for attr in ("_frame_texture", "_still_texture", "_video_texture"):
            tex = getattr(self, attr)
            if tex is not None:
                tex.destroy()
                setattr(self, attr, None)

    def _on_frame(self, _image: QImage) -> None:
        self.update()

    def _on_video_state(self, state: str) -> None:
        """D-3: a decode failure must fall back to CPU, never a black screen."""
        if state == "error" and self._plan is not None and self._plan.backend == "gl":
            video = self._video
            errors = video.errors() if video is not None else []
            self.rendering_failed.emit("; ".join(errors[-2:]) or "video decode failed")

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
        # Device-pixel size: the QOpenGLWidget default framebuffer is sized at
        # widget_size * devicePixelRatio, so the GL viewport must match it or
        # content is drawn into a sub-region (HiDPI distortion).
        dpr = self.devicePixelRatioF()
        size = (max(1, round(self.width() * dpr)), max(1, round(self.height() * dpr)))
        if self.isVisible():
            self._time_sec = self._elapsed.elapsed() / 1000.0
        if self._plan.source_kind == "shader" or self._plan.chain.requires_gl():
            # Both a shader-type background and an image+shader plan render
            # the preset (the image, when present, feeds iChannel0).
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
        # Reuse the uploaded texture while the frame is unchanged (paused /
        # static frames) instead of allocating a texture on every paint.
        key = frame.cacheKey()
        if self._video_texture is None or key != self._video_texture_key:
            if self._video_texture is not None:
                self._video_texture.destroy()
            self._video_texture = self._pipeline.upload_image(frame)
            self._video_texture_key = key
        if self._video_texture is None:
            return
        tex_id = self._video_texture.textureId()
        final = self._pipeline._apply_chain_to_fbo(tex_id, size, self._plan.chain)
        if final is not None:
            self._pipeline.draw_texture(final.texture(), size)
        else:
            self._pipeline.draw_texture(tex_id, size)

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