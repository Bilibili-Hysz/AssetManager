"""Media-stack application package (port batch N-A).

N-A ships only the derivative write side (``derivatives.py``): the registry
recorder that persists regenerable media artifacts under the library data
directory and their ``asset_derivatives`` rows (migration v37). Decoder
registration and sequence recognition land in later batches
(outputs/port-architecture-2026-08-30.md §5).
"""

from AssetsManager.application.media.derivatives import (
    DERIVATIVE_KINDS,
    MediaDerivativesRecorder,
    derivatives_root,
)

__all__ = [
    "DERIVATIVE_KINDS",
    "MediaDerivativesRecorder",
    "derivatives_root",
]
