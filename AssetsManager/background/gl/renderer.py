"""GL rendering pipeline: textures, FBO ping-pong passes, readback and live draw.

All OpenGL calls must happen with a current context (the widget's
``initializeGL``/``paintGL`` or an explicit ``makeCurrent``).  Failures are
surfaced as ``False``/``None`` + a log line — the background pipeline falls
back to CPU instead of crashing (design D-3).
"""
from __future__ import annotations

from PySide6.QtGui import QImage, QOpenGLContext
from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLShader, QOpenGLShaderProgram, QOpenGLTexture

from AssetsManager.background.gl import shaders
from AssetsManager.background.model import EffectChain, EffectSpec

_FULLSCREEN_QUAD = (-1.0, -1.0, 1.0, -1.0, -1.0, 1.0, 1.0, 1.0)


class GlPipeline:
    """Compiles the GLSL programs and runs effect passes on textures/FBOs."""

    def __init__(self) -> None:
        self._programs: dict[str, QOpenGLShaderProgram] = {}
        self._quad_vbo: int = 0
        self._fbo_a: QOpenGLFramebufferObject | None = None
        self._fbo_b: QOpenGLFramebufferObject | None = None
        self._ready = False
        self._failure = ""

    # ── setup ────────────────────────────────────────────────────────────

    def ensure_ready(self) -> bool:
        """Compile programs once. Requires a current GL context."""
        if self._ready or self._failure:
            return self._ready
        ctx = QOpenGLContext.current()
        if ctx is None:
            self._failure = "no current OpenGL context"
            return False
        gl = ctx.functions()
        self._programs["passthrough"] = self._compile(
            VERT=shaders.VERT_SRC, FRAG=shaders.PASSTHROUGH_FRAG
        )
        self._programs["blur"] = self._compile(
            VERT=shaders.VERT_SRC, FRAG=shaders.BLUR_FRAG
        )
        self._programs["mosaic"] = self._compile(
            VERT=shaders.VERT_SRC, FRAG=shaders.MOSAIC_FRAG
        )
        self._programs["kuwahara"] = self._compile(
            VERT=shaders.VERT_SRC, FRAG=shaders.KUW_FRAG
        )
        if all(p is not None for p in self._programs.values()):
            self._quad_vbo = gl.glGenBuffers(1)  # type: ignore[attr-defined]
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._quad_vbo)
            from ctypes import c_float, c_int32

            buf = (c_float * len(_FULLSCREEN_QUAD))(*_FULLSCREEN_QUAD)
            size = c_int32(len(_FULLSCREEN_QUAD) * 4)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, size, buf, gl.GL_STATIC_DRAW)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
            self._ready = True
        return self._ready

    def _compile(self, **sources: str) -> QOpenGLShaderProgram | None:
        program = QOpenGLShaderProgram()
        for shader_type_name, src in sources.items():
            shader_type = (
                QOpenGLShader.ShaderTypeBit.Vertex
                if shader_type_name == "VERT"
                else QOpenGLShader.ShaderTypeBit.Fragment
            )
            shader_obj = QOpenGLShader(shader_type, program)
            if not shader_obj.compileSourceCode(src):
                self._failure = shader_obj.log().strip()
                return None
            if not program.addShader(shader_obj):
                return None
        if not program.link():
            self._failure = program.log().strip()
            return None
        return program

    def shadertoy_program(self, preset_fragment: str) -> QOpenGLShaderProgram | None:
        """Compile a Shadertoy-style preset on demand (called once per preset)."""
        src = shaders.SHADERTOY_HEADER + "\n" + preset_fragment
        return self._compile(VERT=shaders.VERT_SRC, FRAG=src)

    @property
    def failure(self) -> str:
        return self._failure

    # ── textures ─────────────────────────────────────────────────────────

    @staticmethod
    def upload_image(image: QImage) -> QOpenGLTexture | None:
        """Upload a QImage as a mirrored-repeat RGBA texture."""
        if image.isNull():
            return None
        img = image.convertToFormat(QImage.Format.Format_RGBA8888).mirrored()
        tex = QOpenGLTexture(img)
        tex.setMinificationFilter(QOpenGLTexture.Filter.Linear)
        tex.setMagnificationFilter(QOpenGLTexture.Filter.Linear)
        wrap = QOpenGLTexture.WrapMode.MirroredRepeat
        tex.setWrapMode(QOpenGLTexture.Direction.S, wrap)
        tex.setWrapMode(QOpenGLTexture.Direction.T, wrap)
        return tex

    def _draw_quad(self, program: QOpenGLShaderProgram) -> None:
        ctx = QOpenGLContext.current()
        gl = ctx.functions()
        program.bind()
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._quad_vbo)
        program.enableAttributeArray("a_pos")
        program.setAttributeBuffer("a_pos", gl.GL_FLOAT, 0, 2)
        gl.glDrawArrays(gl.GL_TRIANGLE_STRIP, 0, 4)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
        program.release()

    @staticmethod
    def _bind_texture(program: QOpenGLShaderProgram, tex_id: int, unit: int = 0) -> None:
        ctx = QOpenGLContext.current()
        gl = ctx.functions()
        gl.glActiveTexture(gl.GL_TEXTURE0 + unit)
        gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
        program.setUniformValue("u_tex", unit)

    def _resize_fbos(self, size: tuple[int, int]) -> None:
        if (
            self._fbo_a is not None
            and self._fbo_a.width() == size[0]
            and self._fbo_a.height() == size[1]
        ):
            return
        for attr in ("_fbo_a", "_fbo_b"):
            fbo = getattr(self, attr)
            if fbo is not None:
                fbo.deleteLater()
        self._fbo_a = QOpenGLFramebufferObject(size[0], size[1])
        self._fbo_b = QOpenGLFramebufferObject(size[0], size[1])

    # ── still rendering (image -> processed QImage) ───────────────────────

    def render_still(
        self, image: QImage, chain: EffectChain, size: tuple[int, int]
    ) -> QImage | None:
        """Run a CPU-kind effect chain on GPU and read back the result."""
        if not self.ensure_ready():
            return None
        if chain.is_empty:
            return image
        tex = self.upload_image(image.scaled(size[0], size[1]))
        if tex is None:
            return None
        try:
            final = self._apply_chain_to_fbo(tex.textureId(), size, chain)
            if final is None:
                return None
            image_out = final.toImage().mirrored()
            return image_out if not image_out.isNull() else None
        finally:
            tex.destroy()

    def _apply_chain_to_fbo(
        self, src_tex: int, size: tuple[int, int], chain: EffectChain
    ) -> QOpenGLFramebufferObject | None:
        """Ping-pong the chain passes; returns the FBO holding the result.

        A single ``blur`` stage expands to two passes (horizontal then
        vertical) so the separable kernel matches the CPU blur look.
        """
        if not self.ensure_ready():
            return None
        self._resize_fbos(size)
        ctx = QOpenGLContext.current()
        gl = ctx.functions()
        passes: list[tuple[EffectSpec, tuple[float, float] | None]] = []
        for effect in chain.effects:
            if not effect.active:
                continue
            if effect.kind == "blur":
                passes.append((effect, (1.0, 0.0)))
                passes.append((effect, (0.0, 1.0)))
            else:
                passes.append((effect, None))
        if not passes:
            return None
        src: int = src_tex
        src_size = size
        flip = False
        for effect, direction in passes:
            target = self._fbo_b if not flip else self._fbo_a
            dst_size = (target.width(), target.height())
            target.bind()
            gl.glViewport(0, 0, dst_size[0], dst_size[1])
            gl.glClearColor(0.0, 0.0, 0.0, 1.0)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT)
            program = self._program_for(effect)
            if program is None:
                target.release()
                return None
            self._draw_pass(program, src, src_size, effect, direction)
            target.release()
            src = target.texture()
            src_size = dst_size
            flip = not flip
        return self._fbo_b if flip else self._fbo_a

    def _program_for(self, effect: EffectSpec) -> QOpenGLShaderProgram | None:
        name = {
            "blur": "blur",
            "mosaic": "mosaic",
            "kuwahara": "kuwahara",
            "shader": "shadertoy",
        }.get(effect.kind)
        return self._programs.get(name) if name else None

    def _draw_pass(
        self, program: QOpenGLShaderProgram, src_tex: int, src_size: tuple[int, int],
        effect: EffectSpec, direction: tuple[float, float] | None = None,
    ) -> None:
        ctx = QOpenGLContext.current()
        gl = ctx.functions()
        program.bind()
        self._bind_texture(program, src_tex)
        if effect.kind == "blur":
            texel = (1.0 / src_size[0], 1.0 / src_size[1])
            program.setUniformValue("u_texel", *texel)
            program.setUniformValue("u_dir", *direction)
            program.setUniformValue("u_radius", float(effect.intensity))
            self._draw_quad(program)
        elif effect.kind == "mosaic":
            block = max(2, effect.intensity)
            program.setUniformValue(
                "u_block", src_size[0] / block, src_size[1] / block
            )
            self._draw_quad(program)
        elif effect.kind == "kuwahara":
            texel = (1.0 / src_size[0], 1.0 / src_size[1])
            program.setUniformValue("u_texel", *texel)
            program.setUniformValue("u_radius", float(effect.intensity))
            self._draw_quad(program)
        gl.glFlush()

    # ── live rendering (video / shadertoy) ────────────────────────────────

    def draw_shadertoy(
        self,
        preset_fragment: str,
        size: tuple[int, int],
        time_sec: float,
        strength: float,
        channels: dict[int, int] | None = None,
    ) -> bool:
        """Draw a procedural preset to the current (screen) framebuffer."""
        if not self.ensure_ready():
            return False
        program = self.shadertoy_program(preset_fragment)
        if program is None:
            return False
        ctx = QOpenGLContext.current()
        gl = ctx.functions()
        gl.glViewport(0, 0, size[0], size[1])
        program.bind()
        program.setUniformValue("iResolution", float(size[0]), float(size[1]), 1.0)
        program.setUniformValue("iTime", float(time_sec))
        program.setUniformValue("u_strength", float(strength))
        for unit, tex_id in (channels or {}).items():
            gl.glActiveTexture(gl.GL_TEXTURE0 + unit)
            gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
            program.setUniformValue(f"iChannel{unit}", unit)
        self._draw_quad(program)
        program.release()
        return True

    def draw_texture(self, tex_id: int, size: tuple[int, int]) -> None:
        """Blit a texture (e.g. latest video frame) to the current FBO/screen."""
        if not self.ensure_ready():
            return
        ctx = QOpenGLContext.current()
        gl = ctx.functions()
        gl.glViewport(0, 0, size[0], size[1])
        self._draw_pass(self._programs["passthrough"], tex_id, size, EffectSpec("none"))
        gl.glFlush()