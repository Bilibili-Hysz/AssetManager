"""BackgroundManager — turns settings intent into a rendering backend plan.

Decision table (design D-1, validated against the frontend layer in the
design doc §10):

============  ====================  ==========================  =================================
source type   effect                GL available                 backend
============  ====================  ==========================  =================================
image         none/blur/mosaic/      any                          cpu (default, cached QPixmap)
              kuwahara
image         shader                yes                          gl (shader over wallpaper iChannel0)
image         shader                no                           none (why: shader needs GL)
video         any                   yes                          gl (VideoSource frames + effects)
video         any                   no                           cpu (first decoded frame as static)
shader        shader                yes                          gl (procedural preset + re-time)
shader        shader                no                           none (why: shader needs GL)
disabled /    —                     —                            none
no image path
============  ====================  ==========================  =================================
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from AssetsManager.background.gl import probe
from AssetsManager.background.model import BackendPlan, EffectChain
from AssetsManager.core import themes


class BackgroundManager(QObject):
    """Owns backend selection and re-planning; emits the active plan."""

    plan_changed = Signal(object)  # BackendPlan

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._plan = BackendPlan()

    @property
    def gl_ok(self) -> bool:
        return probe.gl_available()

    @property
    def plan(self) -> BackendPlan:
        return self._plan

    # ── plan building ────────────────────────────────────────────────────

    def build_plan(
        self,
        *,
        bg_enabled: bool | None = None,
        bg_type: str | None = None,
        bg_effect: str | None = None,
        bg_effect_intensity: int | None = None,
        bg_shader_preset: str | None = None,
        bg_image: str | None = None,
    ) -> BackendPlan:
        enabled = themes.bg_enabled() if bg_enabled is None else bg_enabled
        source_type = themes.bg_type() if bg_type is None else bg_type
        effect = themes.bg_effect() if bg_effect is None else bg_effect
        intensity = (
            themes.bg_effect_intensity() if bg_effect_intensity is None else bg_effect_intensity
        )
        preset = themes.bg_shader_preset() if bg_shader_preset is None else bg_shader_preset
        image_path = themes.bg_image() if bg_image is None else bg_image

        if not enabled or not image_path or image_path == "":
            return BackendPlan(backend="none", source_kind="image", reason="disabled or no path")

        chain = EffectChain.single(
            kind=effect if effect in ("none", "blur", "mosaic", "kuwahara", "shader") else "none",
            intensity=int(intensity) if intensity else 0,
            shader_key=preset or "plasma",
        )
        sources = ("image", "video", "shader")
        source_type = source_type if source_type in sources else "image"

        if source_type == "image":
            if effect == "shader":
                if self.gl_ok:
                    return BackendPlan(
                        backend="gl", source_kind="image", chain=chain,
                        shader_preset=chain.effects[0].shader_key,
                        source_path=image_path, reason="image+shader needs GL",
                    )
                return BackendPlan(
                    backend="none", source_kind="image",
                    reason="shader effect requires OpenGL",
                )
            return BackendPlan(
                backend="cpu", source_kind="image", chain=chain,
                source_path=image_path, reason="default CPU path",
            )

        if source_type == "video":
            if self.gl_ok:
                return BackendPlan(
                    backend="gl", source_kind="video", chain=chain,
                    source_path=image_path, reason="video via GL",
                )
            return BackendPlan(
                backend="cpu", source_kind="video", chain=chain,
                source_path=image_path, reason="video fallback: first frame via CPU",
            )

        # shader background type
        if self.gl_ok:
            return BackendPlan(
                backend="gl", source_kind="shader", chain=chain,
                shader_preset=chain.effects[0].shader_key,
                source_path=image_path, reason="procedural shader via GL",
            )
        return BackendPlan(
            backend="none", source_kind="shader",
            reason="shader background requires OpenGL",
        )

    def refresh(self) -> BackendPlan:
        """Rebuild the plan from current settings and announce it."""
        self._plan = self.build_plan()
        self.plan_changed.emit(self._plan)
        return self._plan