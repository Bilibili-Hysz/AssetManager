"""Professional-format decoder registry (port batch N-B).

One place that maps media file extensions onto optional-dependency decoders
(outputs/port-architecture-2026-08-30.md §一.2). RAW images decode through
``rawpy`` and Photoshop documents through ``psd-tools``. Both optional
dependencies are probed lazily — at the first registry lookup, not at module
import — so importing this module (and anything that transitively imports it,
e.g. short-lived helper processes) never pays for the media extras. Without
them installed, ``decoder_for`` returns ``None`` for every extension and
``supported_extensions()`` is empty, and the consuming surfaces (desktop
thumbnail loader, desktop viewer, LAN thumbnail/image routes) fall through
to their existing decode or failure paths.

Contracts:

- ``MediaDecoder.decode`` returns an EXIF-oriented, RGB ``PIL.Image.Image``
  (alpha is flattened onto white). Callers pass ``max_dim`` to bound the
  worst-case decode memory: the result's larger side never exceeds it.
- ``register`` refuses extensions the existing pipelines already decode
  (core ``IMAGE_EXTS``); those must keep using the QImageReader/Pillow paths
  so one format never has two competing decode routes.
- EXR is deliberately not registered this round (OpenImageIO is a heavy
  dependency); ``.exr`` is only category-mapped as an image so badges and
  filters already agree (``MEDIA_IMAGE_EXTS`` below).

LAN security note: the LAN routes cannot hand out library paths to decoders
without re-opening them through ``safe_open``, so the concrete decoders also
accept bytes via ``decode_bytes``. The bytes seam is what the LAN content
gate uses — a successful decode is the format validation, failing closed
exactly like the Pillow ``Image.verify`` gate does for raster images.
"""

from __future__ import annotations

import importlib
import io
import logging
import threading
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from PIL import Image, ImageOps

from AssetsManager.core.constants import IMAGE_EXTS, MEDIA_IMAGE_EXTS

_log = logging.getLogger(__name__)

_UNSET = object()  # sentinel: "probe the optional dependency on first use"

#: RAW camera formats decoded by :class:`RawDecoder` (rawpy/LibRaw).
RAW_EXTS: tuple[str, ...] = (
    ".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".raf", ".rw2",
)

#: Photoshop document formats decoded by :class:`PsdDecoder` (psd-tools).
PSD_EXTS: tuple[str, ...] = (".psd", ".psb")

#: Extensions the category registries treat as images even though no decoder
#: is registered for them yet (derived from the category-level set in
#: ``core/constants.py`` so the two cannot drift). ``.exr`` stays there
#: (OpenImageIO is a future batch) so badges and filters do not flip again
#: when the decoder lands.
CATEGORY_ONLY_EXTS: frozenset[str] = MEDIA_IMAGE_EXTS - frozenset(RAW_EXTS) - frozenset(PSD_EXTS)

#: Bound applied when a caller does not pass ``max_dim``: decodes for display
#: never materialize more than this larger side (4K-class), independent of
#: the source's true pixel size.
DEFAULT_DECODE_MAX_DIM = 4096


def normalize_ext(ext: str) -> str:
    """Normalize a user/registry extension to the ``.psd`` spelling.

    Case-insensitive and dot-agnostic: ``PSD``, ``psd`` and ``.PSD`` all
    normalize to ``.psd``.
    """
    value = str(ext or "").strip().lower()
    if value and not value.startswith("."):
        value = f".{value}"
    return value


@runtime_checkable
class MediaDecoder(Protocol):
    """A decoder for one family of professional media formats."""

    def extensions(self) -> tuple[str, ...]:
        """Lowercase dotted extensions this decoder handles (empty if its
        optional dependency is missing)."""
        ...

    def decode(self, path: Path, *, max_dim: int | None = None) -> Image.Image:
        """Decode one source file into an EXIF-oriented RGB image."""
        ...

    def decode_bytes(self, body: bytes, *, max_dim: int | None = None) -> Image.Image | None:
        """Decode one captured source body (LAN ``safe_open`` seam).

        Returns ``None`` on any failure so the LAN content gate can fail
        closed; a successful decode is the format validation.
        """
        ...


def _flatten_rgb(image: Image.Image) -> Image.Image:
    """Collapse any PIL mode onto an RGB image (alpha composited on white)."""
    if image.mode == "RGB":
        return image
    if image.mode in ("RGBA", "LA", "PA") or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(background, rgba).convert("RGB")
    return image.convert("RGB")


def _fit_max_dim(image: Image.Image, max_dim: int | None) -> Image.Image:
    """Downscale so the larger side fits *max_dim* (never upscales)."""
    if max_dim is None or max_dim <= 0:
        return image
    width, height = image.size
    if width <= max_dim and height <= max_dim:
        return image
    ratio = min(max_dim / width, max_dim / height)
    resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
    return image.resize((max(1, int(width * ratio)), max(1, int(height * ratio))), resample)


def _finish(image: Image.Image, max_dim: int | None) -> Image.Image:
    """Shared decode tail: orient, bound, and force RGB."""
    image = ImageOps.exif_transpose(image) or image
    return _fit_max_dim(_flatten_rgb(image), max_dim)


def _import_optional(name: str):
    """Import an optional dependency, or ``None`` when not installed."""
    try:
        return importlib.import_module(name)
    except ImportError:
        _log.debug("Optional media dependency %s is not installed", name)
        return None


class RawDecoder:
    """Camera RAW decoder backed by optional ``rawpy`` (LibRaw).

    Prefers the embedded JPEG preview (``extract_thumb``) — cheap and already
    processed — falls back to ``BITMAP`` thumbnails, and only runs a full
    ``postprocess`` demosaic when the file carries no thumbnail at all.
    ``rawpy_module`` pins the dependency (``None`` = missing, a module = fake
    in tests); by default it is probed on first use.
    """

    def __init__(self, rawpy_module: Any = _UNSET) -> None:
        self._rawpy: Any = rawpy_module

    def _module(self) -> Any:
        if self._rawpy is _UNSET:
            self._rawpy = _import_optional("rawpy")
        return self._rawpy

    def extensions(self) -> tuple[str, ...]:
        return RAW_EXTS if self._module() is not None else ()

    def decode(self, path: Path, *, max_dim: int | None = None) -> Image.Image:
        rawpy_module = self._module()
        if rawpy_module is None:
            raise RuntimeError("rawpy is not installed; RAW decoding is unavailable")
        with rawpy_module.imread(str(path)) as raw:
            thumb = self._extract_thumbnail(raw)
            if thumb is not None:
                return self._finish_thumbnail(thumb, max_dim)
            processed = raw.postprocess(use_camera_wb=True)
        return _finish(Image.fromarray(processed), max_dim)

    def decode_bytes(self, body: bytes, *, max_dim: int | None = None) -> Image.Image | None:
        """Decode RAW bytes (LAN seam: ``safe_open`` snapshot instead of a path).

        Content gate contract: any decode failure returns ``None`` so the LAN
        route fails closed instead of raising mid-request.
        """
        rawpy_module = self._module()
        if rawpy_module is None:
            return None
        try:
            with rawpy_module.imread(io.BytesIO(body)) as raw:
                thumb = self._extract_thumbnail(raw)
                if thumb is not None:
                    return self._finish_thumbnail(thumb, max_dim)
                processed = raw.postprocess(use_camera_wb=True)
            return _finish(Image.fromarray(processed), max_dim)
        except Exception:
            _log.debug("RAW byte decode failed", exc_info=True)
            return None

    def _finish_thumbnail(self, thumb, max_dim: int | None) -> Image.Image:
        if thumb.format == self._module().ThumbFormat.JPEG:
            image = Image.open(io.BytesIO(thumb.data))
            image.load()
            return _finish(image, max_dim)
        # BITMAP thumbnails arrive as an (H, W, 3) uint8 array.
        return _finish(Image.fromarray(thumb.data), max_dim)

    def _extract_thumbnail(self, raw) -> object | None:
        """Return the embedded thumbnail, or ``None`` when unavailable.

        LibRaw raises for files without any embedded preview and for formats
        whose thumbnail extraction is not supported; both mean "fall back to
        postprocessing", not "the file is broken".
        """
        rawpy_module = self._module()
        try:
            return raw.extract_thumb()
        except (rawpy_module.LibRawUnsupportedThumbnailError, rawpy_module.LibRawNoThumbnailError):
            return None
        except Exception:
            _log.debug("RAW thumbnail extraction failed; falling back to postprocess", exc_info=True)
            return None


class PsdDecoder:
    """Photoshop document decoder backed by optional ``psd-tools``.

    ``PSDImage.composite()`` renders the flattened document; when a document
    uses a feature psd-tools cannot composite, the composite of the topmost
    layer group/layer is the fallback. ``psd_image`` pins the dependency
    (``None`` = missing, a class = fake in tests); by default it is probed on
    first use.
    """

    def __init__(self, psd_image: Any = _UNSET) -> None:
        self._psd_image: Any = psd_image

    def _module(self) -> Any:
        if self._psd_image is _UNSET:
            module = _import_optional("psd_tools")
            self._psd_image = getattr(module, "PSDImage", None) if module is not None else None
        return self._psd_image

    def extensions(self) -> tuple[str, ...]:
        return PSD_EXTS if self._module() is not None else ()

    def decode(self, path: Path, *, max_dim: int | None = None) -> Image.Image:
        psd_image = self._module()
        if psd_image is None:
            raise RuntimeError("psd-tools is not installed; PSD decoding is unavailable")
        return self._finish_document(psd_image.open(path), max_dim)

    def decode_bytes(self, body: bytes, *, max_dim: int | None = None) -> Image.Image | None:
        """Decode PSD bytes (LAN seam: ``safe_open`` snapshot instead of a path).

        Content gate contract: any decode failure returns ``None`` so the LAN
        route fails closed instead of raising mid-request.
        """
        psd_image = self._module()
        if psd_image is None:
            return None
        try:
            with io.BytesIO(body) as stream:
                return self._finish_document(psd_image.open(stream), max_dim)
        except Exception:
            _log.debug("PSD byte decode failed", exc_info=True)
            return None

    def _finish_document(self, psd, max_dim: int | None) -> Image.Image:
        image = self._composite(psd)
        if image is None:
            raise ValueError("psd-tools could not composite the document")
        return _finish(image, max_dim)

    def _composite(self, psd):
        try:
            image = psd.composite()
            if image is not None:
                return image
        except Exception:
            _log.debug("psd composite failed; falling back to the top layer", exc_info=True)
        # Fallback: composite of the topmost layer (groups render their
        # children). The flattened composite is unavailable, so the top of
        # the stack is the closest thing to what the author last saw.
        for layer in psd:
            try:
                image = layer.composite()
            except Exception:
                continue
            if image is not None:
                return image
        return None


# ── Module-level registry ─────────────────────────────────────────

#: Extensions the pre-registry pipelines already decode (QImageReader on
#: desktop, the Pillow verify gate on LAN). The registry never claims them.
_EXISTING_PIPELINE_EXTS: frozenset[str] = IMAGE_EXTS

_decoders: list[MediaDecoder] = []
_decoder_by_ext: dict[str, MediaDecoder] = {}
_registry_lock = threading.Lock()
# Lazy flag: the extension→decoder mapping (and therefore the optional
# dependency probe) is built on the first lookup, not at import time.
_registry_dirty = True


def register(decoder: MediaDecoder) -> None:
    """Add *decoder*'s extensions to the registry (test/injection seam).

    Extensions already served by the existing decode pipelines (core
    ``IMAGE_EXTS``: routed to QImageReader on desktop and the Pillow verify
    gate on LAN) are ignored so those paths stay the only decode route for
    them; extensions claimed by an already-registered decoder keep the first
    registration. Note Pillow nominally *claims* ``.psd`` via a stub plugin,
    but PSD was never routable through the existing pipelines (it is not in
    ``IMAGE_EXTS`` and QImageReader cannot open it), so psd-tools takes it.
    """
    global _registry_dirty
    with _registry_lock:
        if decoder not in _decoders:
            _decoders.append(decoder)
        _registry_dirty = True


def _rebuild_registry() -> None:
    global _registry_dirty
    _decoder_by_ext.clear()
    for decoder in _decoders:
        for ext in decoder.extensions():
            normalized = normalize_ext(ext)
            if not normalized:
                continue
            if normalized in _EXISTING_PIPELINE_EXTS:
                _log.debug("Not registering %s: served by the existing pipelines", normalized)
                continue
            if normalized in _decoder_by_ext:
                continue
            _decoder_by_ext[normalized] = decoder
    _registry_dirty = False


def decoder_for(ext: str) -> MediaDecoder | None:
    """Return the registered decoder for *ext*, or ``None``.

    Case-insensitive and dot-agnostic; unknown or unregistered extensions
    (including every extension when the media extras are not installed)
    route to ``None`` so callers fall through unchanged.
    """
    if _registry_dirty:
        with _registry_lock:
            if _registry_dirty:
                _rebuild_registry()
    return _decoder_by_ext.get(normalize_ext(ext))


def supported_extensions() -> frozenset[str]:
    """Extensions currently routed to a decoder (empty without the extras)."""
    if _registry_dirty:
        with _registry_lock:
            if _registry_dirty:
                _rebuild_registry()
    return frozenset(_decoder_by_ext)


# Built-in decoders register themselves at import. Probing their optional
# dependencies (and building the extension mapping) is deferred to the first
# decoder_for()/supported_extensions() call so importing this module — and
# anything that transitively imports it — stays cheap.
register(RawDecoder())
register(PsdDecoder())
