"""Media-stack application package (port batches N-A/N-B).

N-A ships the derivative write side (``derivatives.py``): the registry
recorder that persists regenerable media artifacts under the library data
directory and their ``asset_derivatives`` rows (migration v37). N-B ships the
professional-format decoder registry (``decoders.py``): extension-routed
RAW/PSD decoding through optional dependencies, with an empty registry when
the media extras are not installed (outputs/port-architecture-2026-08-30.md
§一.2). Sequence recognition lands in a later batch (§5).
"""

from AssetsManager.application.media.decoders import (
    MEDIA_IMAGE_EXTS,
    MediaDecoder,
    PsdDecoder,
    RAW_EXTS,
    PSD_EXTS,
    decoder_for,
    normalize_ext,
    register,
    supported_extensions,
)
from AssetsManager.application.media.derivatives import (
    DERIVATIVE_KINDS,
    DERIVATIVE_STATUSES,
    MediaDerivativesRecorder,
    derivatives_root,
)

__all__ = [
    "DERIVATIVE_KINDS",
    "DERIVATIVE_STATUSES",
    "MEDIA_IMAGE_EXTS",
    "MediaDecoder",
    "MediaDerivativesRecorder",
    "PSD_EXTS",
    "PsdDecoder",
    "RAW_EXTS",
    "decoder_for",
    "derivatives_root",
    "normalize_ext",
    "register",
    "supported_extensions",
]
