"""Consumer integration tests for the media decoder registry (N-B).

Covers the three consumption surfaces end to end against the real decoders
(psd-tools generates the fixture documents) plus the missing-dependency
fallback: with the registry empty every surface behaves exactly as before
N-B (failure marker / refused load / 404).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication, QWidget

from AssetsManager.application.media import decoders
from AssetsManager.panels import image_viewer as viewer_module
from AssetsManager.panels.file_list import _loader as loader_module
from AssetsManager.panels.file_list._common import pil_image_to_qimage
from AssetsManager.panels.file_list._loader import ThumbnailLoader
from AssetsManager.panels.image_viewer import ImageViewerOverlay


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def registry_state():
    """Snapshot/restore the module-level decoder registry around injections.

    Mutations hold ``_registry_lock`` because these tests spawn real loader
    worker threads whose ``decoder_for`` lookups rebuild the registry.
    """
    with decoders._registry_lock:
        saved_decoders = list(decoders._decoders)
        saved_by_ext = dict(decoders._decoder_by_ext)
        saved_dirty = decoders._registry_dirty
    yield
    with decoders._registry_lock:
        decoders._decoders[:] = saved_decoders
        decoders._decoder_by_ext.clear()
        decoders._decoder_by_ext.update(saved_by_ext)
        decoders._registry_dirty = saved_dirty


def _write_psd(path, size=(600, 400), color=(200, 60, 30)):
    psd_tools = pytest.importorskip("psd_tools")
    psd_tools.PSDImage.new(mode="RGB", size=size, color=color).save(path)
    return path


def _wait_for(app, condition, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.005)
    app.processEvents()
    return condition()


# ── Desktop thumbnail loader ──────────────────────────────────────


def test_loader_renders_psd_thumbnail_and_bakes_webp(tmp_path, monkeypatch, qapp):
    source = _write_psd(tmp_path / "art.psd")
    monkeypatch.setattr(loader_module, "get_bake_size", lambda: 512)
    loader = ThumbnailLoader()
    loader.set_cache_dir(str(tmp_path / "thumbs"))
    loader.set_lib_root(str(tmp_path))

    image = loader._load_image(str(source), loader._runtime())

    assert image is not None and not image.isNull()
    # 600x400 source decoded at the 512 bake cap, then scaled to the
    # display size for the memory cache.
    assert max(image.width(), image.height()) <= 96
    baked = sorted(Path(loader._cache_dir).glob("*.webp"))
    assert baked, "decoded media thumbnail was not baked into the disk cache"


def test_loader_failure_for_media_formats_matches_existing_path(
    tmp_path, monkeypatch, qapp
):
    """Missing decoder (extras not installed): zero behavior change."""
    source = tmp_path / "art.psd"
    source.write_bytes(b"no decoder for this")
    monkeypatch.setattr(loader_module, "decoder_for", lambda ext: None)

    loader = ThumbnailLoader()
    assert loader._load_image(str(source), loader._runtime()) is None

    # And the request path engages the pre-existing failure machinery.
    failed = []
    failing_loader = ThumbnailLoader()
    failing_loader.thumbnail_failed.connect(failed.append)
    failing_loader.request(0, str(source))
    failing_loader._pool.waitForDone(5000)
    qapp.processEvents()  # thumbnail_failed is a queued cross-thread signal
    assert failed == [str(source)]
    assert failing_loader.is_failed(str(source))


def test_loader_routes_injected_fake_decoder(tmp_path, qapp, registry_state, monkeypatch):
    with decoders._registry_lock:
        decoders._decoders.clear()
        decoders._decoder_by_ext.clear()

    class _FakeDecoder:
        def extensions(self):
            return (".fakeimg",)

        def decode(self, path, *, max_dim=None):
            return Image.new("RGB", (600, 400), (12, 34, 56))

    decoders.register(_FakeDecoder())
    monkeypatch.setattr(loader_module, "get_bake_size", lambda: 512)

    source = tmp_path / "asset.fakeimg"
    source.write_bytes(b"decoded by the fake")
    loader = ThumbnailLoader()
    loader.set_cache_dir(str(tmp_path / "thumbs"))
    loader.set_lib_root(str(tmp_path))

    image = loader._load_image(str(source), loader._runtime())
    assert image is not None and not image.isNull()
    assert any(Path(loader._cache_dir).glob("*.webp"))


def test_loader_admission_bounds_media_sources_before_decode(tmp_path, monkeypatch, qapp):
    from AssetsManager.application.thumbnail_service import (
        MAX_THUMBNAIL_SOURCE_BYTES,
        ThumbnailAdmissionError,
    )

    source = _write_psd(tmp_path / "huge.psd")

    def _admit(path, limit=None):
        raise ThumbnailAdmissionError(Path(path), MAX_THUMBNAIL_SOURCE_BYTES + 1, MAX_THUMBNAIL_SOURCE_BYTES)

    monkeypatch.setattr(loader_module, "admit_thumbnail_source", _admit)

    class _BoomDecoder:
        def extensions(self):
            return ()

        def decode(self, path, *, max_dim=None):
            raise AssertionError("decode must not run for oversize sources")

    oversize = ThumbnailLoader()
    oversize.set_cache_dir(str(tmp_path / "thumbs"))
    assert oversize._load_image(str(source), oversize._runtime()) is None


# ── Desktop viewer ────────────────────────────────────────────────


def test_viewer_opens_psd_through_media_decoder(tmp_path, qapp):
    source = _write_psd(tmp_path / "art.psd")
    host = QWidget()
    viewer = ImageViewerOverlay(host)
    try:
        viewer.load_image(str(source))
        assert _wait_for(qapp, lambda: viewer._state == "ready")
        assert viewer._pixmap is not None
        assert viewer._pixmap.width() <= viewer_module.MAX_DIM
        assert viewer._pixmap.height() <= viewer_module.MAX_DIM
    finally:
        viewer.close()
        host.deleteLater()
        qapp.processEvents()


def test_viewer_refuses_media_formats_without_decoder(tmp_path, monkeypatch, qapp):
    source = tmp_path / "art.psd"
    source.write_bytes(b"undecodable without the extras")
    monkeypatch.setattr(viewer_module, "decoder_for", lambda ext: None)
    host = QWidget()
    viewer = ImageViewerOverlay(host)
    try:
        viewer.load_image(str(source))
        qapp.processEvents()
        # Pre-N-B behavior: not a viewable extension, state never leaves empty.
        assert viewer._state == "empty"
    finally:
        viewer.close()
        host.deleteLater()
        qapp.processEvents()


def test_decode_media_image_seam(tmp_path, qapp, registry_state):
    class _FakeDecoder:
        def extensions(self):
            return ()

        def decode(self, path, *, max_dim=None):
            return Image.new("RGB", (32, 16), (1, 2, 3))

    image = viewer_module._decode_media_image(str(tmp_path / "x.fake"), _FakeDecoder(), 2048)
    assert image is not None and not image.isNull()
    assert (image.width(), image.height()) == (32, 16)

    class _BoomDecoder:
        def decode(self, path, *, max_dim=None):
            raise RuntimeError("decoder exploded")

    assert viewer_module._decode_media_image(str(tmp_path / "x.fake"), _BoomDecoder(), 2048) is None


def test_pil_image_to_qimage_rgb_channel_order():
    # Red-dominant source must stay red: the BGRA raw order maps exactly onto
    # Qt's little-endian Format_ARGB32 (a swap would show blue).
    image = pil_image_to_qimage(Image.new("RGB", (3, 2), (240, 10, 10)))
    assert not image.isNull()
    color = image.pixelColor(1, 1)
    assert color.red() == 240 and color.green() == 10 and color.blue() == 10
