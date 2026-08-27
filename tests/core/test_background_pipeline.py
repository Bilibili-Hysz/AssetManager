"""Tests for the background rendering pipeline (model / manager / CPU / presets).

Design: ``docs/plans/bg-gpu-shader-architecture-2026-08-27.md``.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage

from AssetsManager.background import manager as bm_module
from AssetsManager.background.cpu import render_chain
from AssetsManager.background.gl import presets
from AssetsManager.background.manager import BackgroundManager
from AssetsManager.background.model import BackendPlan, EffectChain, EffectSpec


# ── EffectSpec / EffectChain semantics ───────────────────────────────────

def test_effect_spec_active_rules():
    assert EffectSpec(kind="none", intensity=0).active is False
    assert EffectSpec(kind="blur", intensity=0).active is False
    assert EffectSpec(kind="blur", intensity=1).active is True
    assert EffectSpec(kind="mosaic", intensity=1).active is False
    assert EffectSpec(kind="mosaic", intensity=2).active is True
    assert EffectSpec(kind="kuwahara", intensity=1).active is True
    assert EffectSpec(kind="shader", intensity=1).active is True


def test_effect_chain_gl_and_cpu_support():
    assert EffectChain.single("none").is_empty
    assert EffectChain.single("shader", intensity=5).requires_gl()
    assert not EffectChain.single("blur", intensity=5).requires_gl()
    assert EffectChain.single("kuwahara", intensity=5).cpu_supported()
    assert not EffectChain.single("shader", intensity=5).cpu_supported()


# ── BackgroundManager decision table (design D-1) ────────────────────────

def _manager_with_gl(monkeypatch, gl_ok: bool):
    monkeypatch.setattr(bm_module.probe, "gl_available", lambda force_refresh=False: gl_ok)
    return BackgroundManager()


def test_plan_disabled_no_path(monkeypatch):
    mgr = _manager_with_gl(monkeypatch, gl_ok=True)
    plan = mgr.build_plan(bg_enabled=False, bg_image="C:/bg.png")
    assert plan.backend == "none"
    plan = mgr.build_plan(bg_enabled=True, bg_image="")
    assert plan.backend == "none"


def test_plan_image_cpu_path(monkeypatch):
    for gl_ok in (True, False):
        mgr = _manager_with_gl(monkeypatch, gl_ok=gl_ok)
        for effect in ("none", "blur", "mosaic", "kuwahara"):
            plan = mgr.build_plan(
                bg_enabled=True, bg_type="image", bg_effect=effect,
                bg_effect_intensity=10, bg_image="C:/bg.png",
            )
            assert plan.backend == "cpu", f"{effect}/gl={gl_ok}"
            assert plan.source_path == "C:/bg.png"


def test_plan_image_shader_needs_gl(monkeypatch):
    mgr = _manager_with_gl(monkeypatch, gl_ok=True)
    plan = mgr.build_plan(
        bg_enabled=True, bg_type="image", bg_effect="shader",
        bg_effect_intensity=10, bg_shader_preset="plasma", bg_image="C:/bg.png",
    )
    assert plan.backend == "gl"
    assert plan.source_kind == "image"
    assert plan.shader_preset == "plasma"

    mgr = _manager_with_gl(monkeypatch, gl_ok=False)
    plan = mgr.build_plan(
        bg_enabled=True, bg_type="image", bg_effect="shader",
        bg_effect_intensity=10, bg_shader_preset="plasma", bg_image="C:/bg.png",
    )
    assert plan.backend == "none"
    assert plan.reason  # human-readable reason present


def test_plan_video_gl_or_cpu_fallback(monkeypatch):
    mgr = _manager_with_gl(monkeypatch, gl_ok=True)
    plan = mgr.build_plan(
        bg_enabled=True, bg_type="video", bg_effect="none",
        bg_image="C:/clip.mp4",
    )
    assert plan.backend == "gl"
    assert plan.source_kind == "video"
    assert plan.source_path == "C:/clip.mp4"

    mgr = _manager_with_gl(monkeypatch, gl_ok=False)
    plan = mgr.build_plan(
        bg_enabled=True, bg_type="video", bg_effect="none",
        bg_image="C:/clip.mp4",
    )
    # D-1: no GL -> first-frame static via CPU, never a black screen
    assert plan.backend == "cpu"
    assert plan.source_kind == "video"


def test_plan_shader_type_gl(monkeypatch):
    mgr = _manager_with_gl(monkeypatch, gl_ok=True)
    plan = mgr.build_plan(
        bg_enabled=True, bg_type="shader", bg_effect="shader",
        bg_effect_intensity=10, bg_shader_preset="grid-flow", bg_image="C:/bg.png",
    )
    assert plan.backend == "gl"
    assert plan.source_kind == "shader"
    assert plan.shader_preset == "grid-flow"

    mgr = _manager_with_gl(monkeypatch, gl_ok=False)
    plan = mgr.build_plan(
        bg_enabled=True, bg_type="shader", bg_effect="shader",
        bg_image="C:/bg.png",
    )
    assert plan.backend == "none"


def test_plan_refresh_emits(monkeypatch):
    mgr = _manager_with_gl(monkeypatch, gl_ok=True)
    seen = []
    mgr.plan_changed.connect(seen.append)
    plan = mgr.refresh()
    assert seen == [plan]
    assert isinstance(plan, BackendPlan)


# ── CPU render chain ─────────────────────────────────────────────────────

def test_render_chain_cpu_effects():
    img = QImage(64, 48, QImage.Format.Format_RGB32)
    img.fill(QColor(90, 140, 200))
    for kind, intensity in (("blur", 5), ("mosaic", 6), ("kuwahara", 4), ("none", 0)):
        out = render_chain(img, EffectChain.single(kind, intensity=intensity))
        assert out is not None
        assert not out.isNull()
        assert out.size() == img.size()


# ── VideoSource frame-rate cap ───────────────────────────────────────────

def test_videosource_max_fps_caps_emissions(monkeypatch):
    """max_fps drops converted frames beyond the budget (no QtMultimedia
    needed: the decode/emit path is exercised through a fake frame feed)."""
    import time

    from AssetsManager.background.sources import VideoSource

    src = VideoSource("C:/fake.mp4", max_fps=20.0)
    emitted = []
    src.frame_ready.connect(lambda img: emitted.append(img))

    class FakeFrame:
        def toImage(self):
            img = QImage(8, 8, QImage.Format.Format_RGB32)
            img.fill(QColor(255, 255, 255))
            return img

    # simulate 60 frames arriving back-to-back: a small number should be
    # emitted (60 * 0.5ms of sleep can straddle the 50ms cap window, so
    # allow 1-3), far fewer than the 60 decoded frames.
    for _ in range(60):
        src._on_frame(FakeFrame())
        time.sleep(0.0005)
    assert 1 <= len(emitted) <= 3, f"expected ~1 emission, got {len(emitted)}"

    # after the cap window elapses another frame passes
    time.sleep(0.06)
    src._on_frame(FakeFrame())
    assert len(emitted) >= 2


# ── Shader presets ───────────────────────────────────────────────────────

def test_presets_resolve_and_fallback():
    keys = presets.preset_keys()
    assert "plasma" in keys
    assert len(keys) >= 2
    for key in keys:
        preset = presets.get_preset(key)
        assert preset is not None
        assert preset.fragment.strip()
    # unknown preset falls back to the first built-in (never blank)
    resolved = presets.resolve("does-not-exist")
    assert resolved in keys
    assert presets.resolve("plasma") == "plasma"