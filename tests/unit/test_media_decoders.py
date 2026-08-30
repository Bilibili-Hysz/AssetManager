"""Media decoder registry tests (port batch N-B).

psd-tools decodes run against a real generated document (psd-tools can
write, so the fixture is built in-process). rawpy has no shippable minimal
RAW fixture — LibRaw rejects hand-built linear DNGs — so the RawDecoder
adapter is validated with a fake rawpy module injected through the same seam
the decoder reads at construction (``RawDecoder(rawpy_module=...)``), covering call
order, JPEG/BITMAP-thumbnail vs postprocess fallback, EXIF orientation,
max_dim bounding, and the bytes seam used by the LAN routes.
"""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path

import pytest
from PIL import Image

from AssetsManager.application.media import decoders
from AssetsManager.application.media.decoders import (
    CATEGORY_ONLY_EXTS,
    MEDIA_IMAGE_EXTS,
    PSD_EXTS,
    PsdDecoder,
    RAW_EXTS,
    RawDecoder,
    decoder_for,
    normalize_ext,
    register,
    supported_extensions,
)

_RAWPY_SPEC = importlib.util.find_spec("rawpy")
_PSD_SPEC = importlib.util.find_spec("psd_tools")


@pytest.fixture
def registry_state():
    """Snapshot/restore the module-level registry around injections.

    All mutations hold ``_registry_lock``: consumer tests spawn real loader
    worker threads that call ``decoder_for`` concurrently, and an unlocked
    restore could interleave with a worker rebuild (leaving a cleared mapping
    with ``_registry_dirty=False``).
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


def _reset_registry():
    """Drop every registered decoder (call under ``_registry_lock``)."""
    decoders._decoders.clear()
    decoders._decoder_by_ext.clear()


class _FakeDecoder:
    def __init__(self, exts):
        self._exts = tuple(exts)

    def extensions(self):
        return self._exts

    def decode(self, path, *, max_dim=None):  # pragma: no cover - routing only
        raise AssertionError("decode must not be called in registry tests")


# ── Extension normalization ───────────────────────────────────────


def test_normalize_ext_is_case_and_dot_insensitive():
    assert normalize_ext("PSD") == ".psd"
    assert normalize_ext("psd") == ".psd"
    assert normalize_ext(".PSD") == ".psd"
    assert normalize_ext(" .Psd ") == ".psd"
    assert normalize_ext("") == ""
    assert normalize_ext(None) == ""


# ── Registry routing ──────────────────────────────────────────────


def test_decoder_for_routes_raw_and_psd_case_and_dot_insensitive():
    if _RAWPY_SPEC is None or _PSD_SPEC is None:
        pytest.skip("media extras not installed in this environment")
    assert isinstance(decoder_for(".cr2"), RawDecoder)
    assert isinstance(decoder_for("CR3"), RawDecoder)
    assert isinstance(decoder_for("Nef"), RawDecoder)
    assert isinstance(decoder_for(".dng"), RawDecoder)
    assert isinstance(decoder_for(".psd"), PsdDecoder)
    assert isinstance(decoder_for("PSB"), PsdDecoder)


def test_decoder_for_unknown_and_pillow_native_extensions_return_none():
    assert decoder_for(".xyz") is None
    assert decoder_for("") is None
    # Pillow opens PNG natively; the registry must never claim it so the
    # existing QImageReader path stays the only decode route.
    assert decoder_for(".png") is None
    assert decoder_for(".jpg") is None


def test_supported_extensions_matches_decoder_families():
    if _RAWPY_SPEC is None or _PSD_SPEC is None:
        pytest.skip("media extras not installed in this environment")
    assert supported_extensions() == frozenset(RAW_EXTS) | frozenset(PSD_EXTS)


def test_register_skips_existing_pipeline_extensions(registry_state):
    with decoders._registry_lock:
        _reset_registry()  # built-ins claim .cr2
    fake = _FakeDecoder([".png", ".cr2"])
    register(fake)
    # Existing pipelines (QImageReader / Pillow verify gate) keep .png.
    assert supported_extensions() & {".png"} == set()
    assert isinstance(decoder_for(".cr2"), _FakeDecoder)


def test_register_keeps_first_decoder_for_an_extension(registry_state):
    with decoders._registry_lock:
        _reset_registry()  # built-ins claim .cr2
    first = _FakeDecoder([".cr2"])
    second = _FakeDecoder([".cr2", ".raf"])
    register(first)
    register(second)
    assert decoder_for(".cr2") is first
    assert decoder_for(".raf") is second


def test_missing_media_extras_leave_registry_empty(registry_state):
    """find_spec/import failure equivalent: no decoders, no routing."""
    with decoders._registry_lock:
        _reset_registry()
    register(RawDecoder(rawpy_module=None))
    register(PsdDecoder(psd_image=None))
    assert supported_extensions() == frozenset()
    for ext in RAW_EXTS + PSD_EXTS:
        assert decoder_for(ext) is None
    assert decoder_for(".png") is None


def test_media_image_exts_stay_consistent_with_category_constant():
    assert frozenset(RAW_EXTS) | frozenset(PSD_EXTS) | CATEGORY_ONLY_EXTS == MEDIA_IMAGE_EXTS
    assert CATEGORY_ONLY_EXTS == {".exr"}


def test_category_mapping_treats_media_formats_as_images():
    from AssetsManager.application.asset_filters import extension_matches_category
    from AssetsManager.domain.asset import category_for_extension

    for ext in sorted(MEDIA_IMAGE_EXTS):
        assert category_for_extension(ext) == "images", ext
        assert extension_matches_category(ext, "images"), ext
    assert extension_matches_category(".cr2", "images")
    assert not extension_matches_category(".cr2", "videos")


# ── PSD: real psd-tools decode ────────────────────────────────────


def _write_psd(path, size=(8, 6), color=(200, 60, 30)):
    psd_tools = pytest.importorskip("psd_tools")
    document = psd_tools.PSDImage.new(mode="RGB", size=size, color=color)
    document.save(path)
    return path


@pytest.mark.skipif(_PSD_SPEC is None, reason="psd-tools not installed")
def test_psd_decoder_real_document_roundtrip(tmp_path):
    source = _write_psd(tmp_path / "art.psd")
    image = PsdDecoder().decode(source)
    assert image.mode == "RGB"
    assert image.size == (8, 6)
    assert image.getpixel((4, 3)) == (200, 60, 30)

    body = Path(source).read_bytes()
    from_bytes = PsdDecoder().decode_bytes(body)
    assert from_bytes is not None
    assert from_bytes.size == (8, 6)


@pytest.mark.skipif(_PSD_SPEC is None, reason="psd-tools not installed")
def test_psd_decoder_respects_max_dim(tmp_path):
    source = _write_psd(tmp_path / "big.psd", size=(64, 48))
    image = PsdDecoder().decode(source, max_dim=24)
    assert max(image.size) == 24
    assert image.size[0] > image.size[1]  # aspect preserved (64:48)


def test_psd_decoder_falls_back_to_topmost_layer_when_composite_fails():
    top = Image.new("RGB", (3, 2), (10, 20, 30))

    class _FakeLayer:
        def composite(self):
            return top.copy()

    class _FakeDocument:
        def composite(self):
            raise RuntimeError("unsupported composite feature")

        def __iter__(self):
            return iter([_FakeLayer()])

    class _FakePSDImage:
        @staticmethod
        def open(_source):
            return _FakeDocument()

    image = PsdDecoder(psd_image=_FakePSDImage).decode(Path("fake.psd"))
    assert image.mode == "RGB"
    assert image.size == (3, 2)
    assert image.getpixel((0, 0)) == (10, 20, 30)


def test_psd_decoder_raises_when_composite_and_layers_all_fail():
    class _FakeDocument:
        def composite(self):
            return None

        def __iter__(self):
            return iter([])

    class _FakePSDImage:
        @staticmethod
        def open(_source):
            return _FakeDocument()

    with pytest.raises(ValueError):
        PsdDecoder(psd_image=_FakePSDImage).decode(Path("fake.psd"))


# ── RAW: rawpy adapter via a fake rawpy module ────────────────────


class _FakeThumbFormat:
    JPEG = "jpeg"
    BITMAP = "bitmap"


class _FakeNoThumbnailError(Exception):
    pass


class _FakeUnsupportedThumbnailError(Exception):
    pass


class _FakeRawHandle:
    def __init__(self, fake):
        self._fake = fake

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def extract_thumb(self):
        self._fake.calls.append("extract_thumb")
        if self._fake.extract_error is not None:
            raise self._fake.extract_error
        return self._fake.thumb

    def postprocess(self, use_camera_wb=False):
        self._fake.calls.append(f"postprocess:{use_camera_wb}")
        return self._fake.postprocess_result


class _FakeRawpy:
    """Stand-in for the rawpy module surface RawDecoder relies on."""

    ThumbFormat = _FakeThumbFormat
    LibRawNoThumbnailError = _FakeNoThumbnailError
    LibRawUnsupportedThumbnailError = _FakeUnsupportedThumbnailError

    def __init__(self, *, thumb=None, extract_error=None, postprocess_result=None):
        self.thumb = thumb
        self.extract_error = extract_error
        self.postprocess_result = postprocess_result
        self.calls: list[str] = []
        self.sources: list[str] = []

    def imread(self, source):
        self.sources.append(type(source).__name__)
        self.calls.append("imread")
        return _FakeRawHandle(self)


def _jpeg_thumb_bytes(size=(100, 50), color=(90, 120, 200), orientation=None):
    image = Image.new("RGB", size, color)
    exif = Image.Exif()
    if orientation is not None:
        exif[274] = orientation
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def _jpeg_thumb(thumb_bytes):
    from types import SimpleNamespace

    return SimpleNamespace(format=_FakeThumbFormat.JPEG, data=thumb_bytes)


def _make_raw_decoder(fake_rawpy):
    decoder = RawDecoder()
    decoder._rawpy = fake_rawpy
    return decoder


def test_raw_decoder_prefers_embedded_jpeg_thumbnail_and_applies_exif():
    pytest.importorskip("numpy")  # rawpy always requires numpy
    fake = _FakeRawpy(thumb=_jpeg_thumb(_jpeg_thumb_bytes()))
    image = _make_raw_decoder(fake).decode(Path("shot.cr2"))
    assert fake.calls == ["imread", "extract_thumb"]
    assert image.mode == "RGB"
    assert image.size == (100, 50)


def test_raw_decoder_applies_exif_orientation_from_thumbnail():
    pytest.importorskip("numpy")
    fake = _FakeRawpy(
        thumb=_jpeg_thumb(_jpeg_thumb_bytes(size=(100, 50), orientation=6)),
    )
    image = _make_raw_decoder(fake).decode(Path("shot.cr2"))
    # Orientation 6 = 90° CW: the 100x50 preview decodes transposed to 50x100.
    assert image.size == (50, 100)


def test_raw_decoder_uses_bitmap_thumbnail_without_reencode():
    numpy = pytest.importorskip("numpy")
    bitmap = numpy.zeros((6, 8, 3), dtype=numpy.uint8)
    bitmap[:, :, 0] = 200
    fake = _FakeRawpy(thumb=type("T", (), {"format": _FakeThumbFormat.BITMAP, "data": bitmap})())
    image = _make_raw_decoder(fake).decode(Path("shot.nef"))
    assert fake.calls == ["imread", "extract_thumb"]
    assert image.size == (8, 6)
    assert image.getpixel((0, 0)) == (200, 0, 0)


def test_raw_decoder_falls_back_to_postprocess_without_thumbnail():
    numpy = pytest.importorskip("numpy")
    frame = numpy.full((6, 8, 3), 77, dtype=numpy.uint8)
    fake = _FakeRawpy(
        extract_error=_FakeNoThumbnailError("no thumbnail in file"),
        postprocess_result=frame,
    )
    image = _make_raw_decoder(fake).decode(Path("shot.arw"))
    assert fake.calls == ["imread", "extract_thumb", "postprocess:True"]
    assert image.size == (8, 6)
    assert image.getpixel((4, 3)) == (77, 77, 77)


def test_raw_decoder_unsupported_thumbnail_error_also_falls_back():
    numpy = pytest.importorskip("numpy")
    frame = numpy.zeros((4, 4, 3), dtype=numpy.uint8)
    fake = _FakeRawpy(
        extract_error=_FakeUnsupportedThumbnailError("format unsupported"),
        postprocess_result=frame,
    )
    image = _make_raw_decoder(fake).decode(Path("shot.raf"))
    assert image.size == (4, 4)


def test_raw_decoder_max_dim_bounds_decoded_output():
    pytest.importorskip("numpy")
    fake = _FakeRawpy(thumb=_jpeg_thumb(_jpeg_thumb_bytes(size=(100, 50))))
    image = _make_raw_decoder(fake).decode(Path("shot.cr2"), max_dim=25)
    assert max(image.size) == 25
    assert image.size == (25, 12)  # 100x50 aspect preserved


def test_raw_decoder_decode_bytes_hands_a_stream_to_rawpy():
    pytest.importorskip("numpy")
    fake = _FakeRawpy(thumb=_jpeg_thumb(_jpeg_thumb_bytes(size=(10, 4))))
    image = _make_raw_decoder(fake).decode_bytes(b"raw-bytes")
    assert fake.sources == ["BytesIO"]
    assert image.size == (10, 4)


def test_raw_decoder_without_dependency_is_inert():
    decoder = RawDecoder()
    decoder._rawpy = None
    assert decoder.extensions() == ()
    with pytest.raises(RuntimeError):
        decoder.decode(Path("shot.cr2"))
    assert decoder.decode_bytes(b"raw-bytes") is None


def test_media_decoders_fail_closed_on_non_media_bytes():
    """decode_bytes is the LAN content gate: junk bytes decode to None."""
    if _PSD_SPEC is None:
        pytest.skip("psd-tools not installed")
    assert PsdDecoder().decode_bytes(b"this is not a Photoshop document") is None
    if _RAWPY_SPEC is None:
        pytest.skip("rawpy not installed")
    assert RawDecoder().decode_bytes(b"this is not a RAW file") is None


def test_psd_decoder_without_dependency_is_inert():
    decoder = PsdDecoder()
    decoder._psd_image = None
    assert decoder.extensions() == ()
    with pytest.raises(RuntimeError):
        decoder.decode(Path("art.psd"))
    assert decoder.decode_bytes(b"psd-bytes") is None
