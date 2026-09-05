"""Media analysis processors (port batch N-B2).

Two pure derived-artifact producers per
outputs/port-architecture-2026-08-30.md §一.1: ``extract_palette`` distills a
dominant-color palette from a PIL image, and ``generate_waveform`` renders an
audio file's amplitude envelope as a PNG via ffmpeg ``showwavespic`` (with a
dependency-free pure-Python fast path for plain PCM WAV — ``audioop`` was
removed in Python 3.13, so the down-mix/peak sampling is hand-rolled on
``array``/``struct``).

Both functions are pure, stateless, and never raise: failures return
``None``/``False`` and are logged, so a broken media file can never break the
thumbnail pipeline that triggered the analysis.

ffmpeg is resolved the same way the existing pipelines resolve it
(``ThumbnailService._extract_video_frame``): the bare ``"ffmpeg"`` command
name, resolved through ``PATH`` by ``subprocess`` — no settings override and
no custom locator, by design.

The ``ensure_*`` orchestration helpers implement the "compute at most once"
contract on top of :class:`~AssetsManager.application.media.derivatives.
MediaDerivativesRecorder`: an existing ``asset_derivatives`` row short-circuits
regeneration, a successful computation is recorded, and every failure is
swallowed. The recorder is injected (duck-typed), so this module stays free of
imports from the recorder module.
"""

from __future__ import annotations

import array
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, cast

from PIL import Image

_log = logging.getLogger(__name__)

#: ffmpeg executable name. The existing video-frame extraction runs the bare
#: ``"ffmpeg"`` through ``subprocess`` (PATH-resolved); analysis reuses that
#: exact convention instead of introducing a settings key or custom locator.
FFMPEG_EXECUTABLE = "ffmpeg"

#: Subprocess budget for one waveform render (mirrors the video frame
#: extraction timeout in ``thumbnail_service``).
FFMPEG_TIMEOUT_SECONDS = 30

#: Palette swatches are extracted from a thumbnail-scale copy of the image.
_PALETTE_MAX_DIM = 64

#: Neutral waveform ink on a transparent background: readable on both the
#: light and dark grid themes (ffmpeg ``showwavespic`` gets the same color).
WAVEFORM_COLOR = "#808080"


def _hex_color(red: int, green: int, blue: int) -> str:
    return f"#{red:02x}{green:02x}{blue:02x}"


def extract_palette(image: Image.Image, *, colors: int = 6) -> dict | None:
    """Return ``{"colors": ["#rrggbb", ...], "dominant": "#rrggbb"}``.

    The image is first copied down to at most 64px on the larger side, then
    quantized to *colors* palette entries with Pillow; swatches come back in
    descending frequency order so ``dominant`` is the most frequent color.
    The result is directly JSON-serializable (recorder ``params`` payload).
    Returns ``None`` (and logs) on any failure — never raises.
    """
    try:
        rgb = image.convert("RGB")
        width, height = rgb.size
        largest = max(width, height)
        if largest > _PALETTE_MAX_DIM:
            ratio = _PALETTE_MAX_DIM / largest
            rgb = rgb.resize(
                (max(1, int(width * ratio)), max(1, int(height * ratio))),
                Image.Resampling.LANCZOS,
            )
        quantized = rgb.quantize(colors=max(1, colors))
        palette = quantized.getpalette() or []
        # A "P"-mode image's getcolors() yields (count, palette-index) pairs;
        # Pillow's type hint also allows the RGB tuple variant, which cannot
        # occur for palette images — narrow it for the index arithmetic below.
        counts = cast(
            "list[tuple[int, int]]",
            quantized.getcolors(maxcolors=max(1, colors) * 16) or [],
        )
        # getcolors() yields (count, palette-index); sort by count descending
        # so the dominant swatch leads.
        counts.sort(key=lambda entry: entry[0], reverse=True)
        swatches: list[str] = []
        for _count, index in counts:
            offset = index * 3
            if offset + 2 >= len(palette):
                continue
            swatches.append(_hex_color(palette[offset], palette[offset + 1], palette[offset + 2]))
            if len(swatches) >= colors:
                break
        if not swatches:
            return None
        return {"colors": swatches, "dominant": swatches[0]}
    except Exception:
        _log.debug("Palette extraction failed", exc_info=True)
        return None


# ── Waveform: pure-Python PCM WAV fast path ───────────────────────

def _pcm_samples(raw: bytes, sampwidth: int):
    """Decode little-endian PCM sample bytes into one flat ``array``.

    Returns ``None`` for sample widths the fast path does not support
    (24-bit) — the caller falls back to ffmpeg. Multi-channel data stays
    interleaved; callers stride it down to one channel.
    """
    if sampwidth == 2:
        samples = array.array("h")
        usable = raw[: len(raw) - (len(raw) % 2)]
        samples.frombytes(usable)
    elif sampwidth == 4:
        samples = array.array("i")
        usable = raw[: len(raw) - (len(raw) % 4)]
        samples.frombytes(usable)
    elif sampwidth == 1:
        # 8-bit WAV is unsigned; peak-to-peak is shift-invariant, so the
        # unsigned values keep the exact envelope shape without a costly
        # per-sample re-bias.
        samples = array.array("B")
        samples.frombytes(raw)
    else:
        return None
    if sys.byteorder == "big":
        samples.byteswap()
    return samples


def _bucket_peaks(mono, width: int) -> list[tuple[float, float]]:
    """Down-sample one mono track into (min, max) per output column.

    ``array`` slicing keeps the per-bucket min/max at C speed; fewer samples
    than columns simply produce fewer (wider-stretched) buckets.
    """
    total = len(mono)
    columns = max(1, min(width, total))
    peaks: list[tuple[float, float]] = []
    for column in range(columns):
        start = column * total // columns
        end = max(start + 1, (column + 1) * total // columns)
        chunk = mono[start:end]
        if chunk:
            peaks.append((min(chunk), max(chunk)))
    return peaks


def _render_peaks_png(peaks, out_png: Path, width: int, height: int) -> bool:
    """Draw one min/max envelope column per bucket onto a transparent PNG."""
    from PIL import ImageDraw

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    low = min(low for low, _high in peaks)
    high = max(high for _low, high in peaks)
    span = max(high - low, 1)
    mid = height / 2
    scale = (height - 2) / span
    ink = tuple(int(WAVEFORM_COLOR[i : i + 2], 16) for i in (1, 3, 5)) + (255,)
    columns = len(peaks)
    for index, (low_peak, high_peak) in enumerate(peaks):
        top = mid - (high_peak - low) * scale
        bottom = mid - (low_peak - low) * scale
        if bottom - top < 1.0:
            center = (top + bottom) / 2
            top, bottom = center - 0.5, center + 0.5
        x = index * width // columns
        draw.line((x, top, x, bottom), fill=ink, width=1)
    image.save(out_png, "PNG")
    return True


def _generate_waveform_pcm_wav(audio_path: Path, out_png: Path, width: int, height: int) -> bool:
    """Render a PCM WAV waveform without ffmpeg; ``False`` = not applicable."""
    import wave

    try:
        with wave.open(str(audio_path), "rb") as wav:
            channels = wav.getnchannels()
            sampwidth = wav.getsampwidth()
            frames = wav.getnframes()
            if channels < 1 or frames <= 0:
                return False
            raw = wav.readframes(frames)
    except (wave.Error, EOFError, OSError):
        return False
    samples = _pcm_samples(raw, sampwidth)
    if samples is None or len(samples) < channels:
        return False
    mono = samples[::channels]
    peaks = _bucket_peaks(mono, width)
    if not peaks:
        return False
    try:
        return _render_peaks_png(peaks, out_png, width, height)
    except Exception:
        _log.debug("Waveform PNG render failed for %s", audio_path, exc_info=True)
        return False


# ── Waveform: ffmpeg path ─────────────────────────────────────────

def _generate_waveform_ffmpeg(
    audio_path: Path,
    out_png: Path,
    width: int,
    height: int,
    ffmpeg: str | None,
) -> bool:
    """Render the waveform via ffmpeg ``showwavespic``; ``False`` = failure."""
    try:
        result = subprocess.run(
            [
                ffmpeg or FFMPEG_EXECUTABLE,
                "-y",
                "-i", str(audio_path),
                "-filter_complex",
                f"showwavespic=s={width}x{height}:colors={WAVEFORM_COLOR}",
                "-frames:v", "1",
                str(out_png),
            ],
            capture_output=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
        )
        return (
            result.returncode == 0
            and out_png.is_file()
            and out_png.stat().st_size > 0
        )
    except (OSError, subprocess.SubprocessError):
        _log.debug("ffmpeg waveform render failed for %s", audio_path, exc_info=True)
        return False


def generate_waveform(
    audio_path: Path,
    out_png: Path,
    *,
    width: int = 512,
    height: int = 96,
    ffmpeg: str | None = None,
) -> bool:
    """Render one audio file's amplitude envelope to a PNG; never raises.

    Plain PCM WAV files take the dependency-free Python path (``wave`` +
    ``array`` peak sampling); every other format (and any WAV the fast path
    cannot parse) goes through ffmpeg ``showwavespic``, resolved exactly like
    the existing video-frame extraction (bare PATH-resolved ``"ffmpeg"``).
    ``ffmpeg`` overrides the executable name (tests). Returns ``False`` and
    logs on any failure.
    """
    audio_path = Path(audio_path)
    out_png = Path(out_png)
    width = max(16, min(int(width), 4096))
    height = max(16, min(int(height), 1024))
    try:
        out_png.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        _log.debug("Waveform output directory unavailable: %s", out_png.parent)
        return False
    if _generate_waveform_pcm_wav(audio_path, out_png, width, height):
        return True
    return _generate_waveform_ffmpeg(audio_path, out_png, width, height, ffmpeg)


def generate_waveform_from_bytes(
    body: bytes,
    suffix: str,
    out_png: Path,
    *,
    width: int = 512,
    height: int = 96,
    ffmpeg: str | None = None,
) -> bool:
    """Render a waveform from captured source bytes (LAN ``safe_open`` seam).

    The snapshot is spooled to one temp file with the source's suffix (same
    pattern as ``ThumbnailService._extract_video_frame_from_bytes``) because
    both the ``wave`` reader and ffmpeg need a seekable named input.
    """
    fd, temp_path = tempfile.mkstemp(suffix=suffix or ".bin")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        return generate_waveform(
            Path(temp_path), Path(out_png), width=width, height=height, ffmpeg=ffmpeg,
        )
    except Exception:
        _log.debug("Waveform render from captured bytes failed", exc_info=True)
        return False
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


# ── Compute-at-most-once orchestration (recorder duck-typed) ──────

def _safe_source_mtime(path: Path) -> float | None:
    """Return the source file's mtime, or ``None`` when it cannot be read.

    Mirrors the project-service admission check (``project_service.py``):
    derivatives record the source's mtime so a changed source can be
    detected. A missing/unreadable source must never raise here — the
    analysis passes never raise.
    """
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def _derivative_matches_source(derivative, path: Path) -> bool:
    """True when a registered derivative is still fresh for *path*.

    ``False`` when the row is missing, when no mtime was recorded (a legacy
    row written before mtime capture, or a remote/byte-fed pass), or when the
    recorded mtime differs from the source's current mtime — the source
    changed, so the derivative must be regenerated.
    """
    if derivative is None:
        return False
    recorded = derivative.source_mtime
    if recorded is None:
        return False
    current = _safe_source_mtime(path)
    return current is not None and current == recorded


def ensure_audio_waveform(
    recorder,
    audio_path: str | Path,
    *,
    source_body: bytes | None = None,
    source_suffix: str = "",
    width: int = 512,
    height: int = 96,
    ffmpeg: str | None = None,
) -> bytes | None:
    """Return the audio's waveform PNG bytes, generating them at most once.

    A registered ``audio_waveform`` derivative (payload present on disk and
    its recorded ``source_mtime`` still matching the source file) is returned
    directly; otherwise the waveform is rendered — from ``source_body`` when
    the caller holds a captured snapshot (LAN seam), from the file itself
    otherwise — and recorded under ``data_dir/derivatives/``. Without a
    recorder the computation still happens but nothing is registered. Returns
    ``None`` on any failure; never raises.

    Lifecycle wiring (migration v41): a row that exists but is no longer
    servable (stale ``source_mtime``, missing payload) is soft-invalidated —
    payload dropped, row kept with ``invalidated_at`` — before regeneration,
    and a failed regeneration marks the existing row ``failed`` so the read
    side stops serving stale state while the retry semantics stay unchanged.
    A failed attempt for an asset without a row stays rowless: failure rows
    must never pollute the ready-only queries.
    """
    path = Path(audio_path)
    fd, temp_png = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    temp_out = Path(temp_png)
    try:
        had_row = False
        if recorder is not None:
            found = recorder.lookup(path, "audio_waveform")
            payload = recorder.payload_path(path, "audio_waveform")
            if payload is not None and _derivative_matches_source(found, path):
                data = payload.read_bytes()
                if data:
                    return data
            had_row = found is not None
            if had_row:
                # The registered row is stale or its payload is gone: retire
                # it (keep the row, drop the stale payload) so no consumer can
                # serve it while this regeneration runs.
                recorder.invalidate(path, "audio_waveform")
        if source_body is not None:
            rendered = generate_waveform_from_bytes(
                source_body, source_suffix, temp_out,
                width=width, height=height, ffmpeg=ffmpeg,
            )
        else:
            rendered = generate_waveform(
                path, temp_out, width=width, height=height, ffmpeg=ffmpeg,
            )
        if not rendered:
            if recorder is not None and had_row:
                recorder.mark_failed(path, "audio_waveform", "waveform_render_failed")
            return None
        data = temp_out.read_bytes()
        if not data:
            if recorder is not None and had_row:
                recorder.mark_failed(path, "audio_waveform", "waveform_render_failed")
            return None
        if recorder is not None:
            recorder.record(path, "audio_waveform", data, ext=".png",
                            source_mtime=_safe_source_mtime(path))
        return data
    except Exception:
        _log.debug("Waveform derivative pass failed for %s", path, exc_info=True)
        return None
    finally:
        try:
            temp_out.unlink()
        except OSError:
            pass


def ensure_extracted_palette(
    recorder,
    file_path: str | Path,
    image: Image.Image | Callable[[], Image.Image | None],
    *,
    colors: int = 6,
) -> None:
    """Record the asset's color palette unless a fresh row already exists.

    *image* may be a PIL image or a zero-argument factory producing one (the
    factory runs only when the row is still missing, so callers can pass a
    cheap lazy decode). A registered row whose recorded ``source_mtime`` still
    matches the source file short-circuits recomputation; a row whose mtime
    does not match (source changed) is soft-invalidated (payload/row semantics
    of migration v41: row kept, ``invalidated_at`` stamped) and recomputed.
    The palette is stored as recorder ``params`` JSON — a params-only row
    without a payload file. Missing rows stay missing after a failed
    extraction — failures only mark rows that already exist (never insert
    failure rows, so the ready-only queries stay clean) — and every failure
    is swallowed.
    """
    path = Path(file_path)
    try:
        if recorder is None:
            return
        found = recorder.lookup(path, "extracted_palette")
        if found is not None and _derivative_matches_source(found, path):
            return
        had_row = found is not None
        if had_row:
            # The registered row is stale (source changed): retire it before
            # recomputing so the read side cannot serve the outdated palette.
            recorder.invalidate(path, "extracted_palette")
        source = image() if callable(image) else image
        if source is None:
            if had_row:
                recorder.mark_failed(path, "extracted_palette", "palette_source_unreadable")
            return
        palette = extract_palette(source, colors=colors)
        if palette is None:
            if had_row:
                recorder.mark_failed(path, "extracted_palette", "palette_extract_failed")
            return
        recorder.record(path, "extracted_palette", params=palette, payload=False,
                        source_mtime=_safe_source_mtime(path))
    except Exception:
        _log.debug("Palette derivative pass failed for %s", path, exc_info=True)
