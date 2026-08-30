"""Media analysis processors (port batch N-B2).

Covers ``application/media/analysis.py``: palette extraction from synthetic
images, the dependency-free PCM-WAV waveform fast path (no ffmpeg/subprocess
on that path), the ffmpeg fallback contract (never raises), and the
compute-at-most-once orchestration helpers on top of the derivatives
recorder — including the params-only ``extracted_palette`` row and recorder
failure isolation.
"""

from __future__ import annotations

import json
import math
import shutil
import struct
import wave
from pathlib import Path

import pytest

from AssetsManager.application.media.analysis import (
    FFMPEG_TIMEOUT_SECONDS,
    ensure_audio_waveform,
    ensure_extracted_palette,
    extract_palette,
    generate_waveform,
    generate_waveform_from_bytes,
)


@pytest.fixture
def db(memory_db):
    """Migrated in-memory library database (v37 tables present)."""
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import CURRENT_SCHEMA_VERSION, migrate

    memory_db.executescript(database._SCHEMA)
    assert migrate(memory_db) == CURRENT_SCHEMA_VERSION
    return memory_db


@pytest.fixture
def recorder(db, tmp_path):
    from AssetsManager.application.media.derivatives import MediaDerivativesRecorder

    return MediaDerivativesRecorder(lambda: db, tmp_path / "data_dir")


def write_wav(
    path: Path,
    *,
    seconds: float = 0.5,
    rate: int = 8000,
    freq: float = 440.0,
) -> Path:
    """Write a real mono 16-bit PCM wav with a 440 Hz sine (wave module)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    total = int(rate * seconds)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        frames = bytearray()
        for i in range(total):
            frames += struct.pack(
                "<h", int(20000 * math.sin(2 * math.pi * freq * i / rate))
            )
        wav.writeframes(bytes(frames))
    return path


def _synthetic_two_tone(width: int = 64, height: int = 64):
    from PIL import Image

    image = Image.new("RGB", (width, height), (255, 0, 0))
    for x in range(3 * width // 4, width):  # 3/4 red, 1/4 blue
        for y in range(height):
            image.putpixel((x, y), (0, 0, 255))
    return image


# ── extract_palette ─────────────────────────────────────────────────


def test_extract_palette_synthetic_image_dominant_and_order():
    result = extract_palette(_synthetic_two_tone(), colors=6)

    assert result is not None
    assert result["dominant"] == "#ff0000"  # 3/4 of the pixels are red
    assert result["colors"][0] == "#ff0000"  # descending frequency
    assert "#0000ff" in result["colors"]
    assert 1 <= len(result["colors"]) <= 6
    import re

    for swatch in result["colors"]:
        assert re.fullmatch(r"#[0-9a-f]{6}", swatch)


def test_extract_palette_downsamples_large_image():
    # 300x200 exceeds the 64px palette cap; the verdict (dominant red, blue
    # present) must survive the downsample even though resampling ringing
    # may add intermediate swatches.
    large = extract_palette(_synthetic_two_tone(300, 200))

    assert large is not None
    assert large["dominant"] == "#ff0000"
    assert "#0000ff" in large["colors"]


def test_extract_palette_failure_returns_none(monkeypatch):
    monkeypatch.setattr(
        "AssetsManager.application.media.analysis.Image.Image.convert",
        lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert extract_palette(_synthetic_two_tone()) is None


# ── generate_waveform: pure-Python PCM fast path ────────────────────


def test_generate_waveform_pcm_wav_takes_dependency_free_path(
    tmp_path, monkeypatch
):
    import subprocess

    wav = write_wav(tmp_path / "tone.wav")
    out_png = tmp_path / "out" / "wave.png"

    def _no_ffmpeg(*args, **kwargs):
        raise AssertionError("subprocess must not be used for PCM wav input")

    monkeypatch.setattr(subprocess, "run", _no_ffmpeg)

    assert generate_waveform(wav, out_png) is True
    assert out_png.is_file() and out_png.stat().st_size > 0

    from PIL import Image

    with Image.open(out_png) as image:
        assert image.format == "PNG"
        assert image.size == (512, 96)  # defaults from the port contract


def test_generate_waveform_pcm_wav_custom_dimensions(tmp_path):
    wav = write_wav(tmp_path / "tone.wav")
    out_png = tmp_path / "wave.png"

    from PIL import Image

    assert generate_waveform(wav, out_png, width=256, height=64) is True
    with Image.open(out_png) as image:
        assert image.size == (256, 64)


def test_generate_waveform_from_bytes_matches_file_path(tmp_path):
    wav = write_wav(tmp_path / "tone.wav")
    body = wav.read_bytes()
    from_file = tmp_path / "from_file.png"
    from_bytes = tmp_path / "from_bytes.png"

    assert generate_waveform(wav, from_file) is True
    assert generate_waveform_from_bytes(body, ".wav", from_bytes) is True
    assert from_bytes.stat().st_size > 0


# ── generate_waveform: failure contract ─────────────────────────────


def test_generate_waveform_garbage_without_ffmpeg_returns_false(tmp_path):
    garbage = tmp_path / "noise.bin"
    garbage.write_bytes(b"definitely not audio")

    assert (
        generate_waveform(
            garbage, tmp_path / "wave.png", ffmpeg="missing-ffmpeg-xyz"
        )
        is False
    )
    assert not (tmp_path / "wave.png").exists()


def test_generate_waveform_failure_never_raises(tmp_path):
    # Missing source and unwritable output directory both degrade to False.
    assert (
        generate_waveform(
            tmp_path / "absent.wav", tmp_path / "wave.png", ffmpeg="missing-ffmpeg-xyz"
        )
        is False
    )
    assert (
        generate_waveform(
            write_wav(tmp_path / "tone.wav"),
            tmp_path / "no-such-dir" / "sub" / "wave.png",
        )
        is True  # output parents are created by the caller contract
    )


def test_generate_waveform_ffmpeg_timeout_mirrors_video_pipeline():
    # The subprocess budget matches the existing video-frame extraction (30s).
    assert FFMPEG_TIMEOUT_SECONDS == 30


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_generate_waveform_non_pcm_wav_walks_real_ffmpeg_path(tmp_path):
    """Optional real-ffmpeg run: float32 wav is not `wave`-module PCM, so the
    render must come from the ffmpeg showwavespic fallback."""
    pcm = write_wav(tmp_path / "tone.wav")
    import subprocess

    float_wav = tmp_path / "tone_float.wav"
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(pcm),
            "-c:a", "pcm_f32le", str(float_wav),
        ],
        capture_output=True,
        timeout=60,
    )
    if result.returncode != 0:  # pragma: no cover - encoder unavailable
        pytest.skip("ffmpeg cannot encode pcm_f32le here")
    import wave as wave_module

    with pytest.raises((wave_module.Error, EOFError)):
        with wave_module.open(str(float_wav), "rb"):
            pass  # the fast path cannot parse non-PCM wav

    out_png = tmp_path / "wave.png"
    assert generate_waveform(float_wav, out_png) is True
    assert out_png.stat().st_size > 0


# ── ensure_extracted_palette: params-only row ────────────────────────


def test_ensure_extracted_palette_records_params_only_row(recorder, db, tmp_path):
    source = tmp_path / "library" / "hero.png"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"image")
    calls: list[int] = []

    def factory():
        calls.append(1)
        return _synthetic_two_tone()

    ensure_extracted_palette(recorder, source, factory)

    rows = db.execute(
        "SELECT rel_path, params FROM asset_derivatives "
        "WHERE file_path=? AND kind='extracted_palette'",
        (str(source.resolve()),),
    ).fetchall()
    assert len(rows) == 1
    rel_path, params = rows[0]
    assert rel_path == ""  # params-only: no payload file on disk
    stored = json.loads(params)
    assert stored["dominant"] == "#ff0000"
    assert not (tmp_path / "data_dir" / "derivatives" / "extracted_palette").exists()


def test_ensure_extracted_palette_existing_row_skips_recompute(recorder, db, tmp_path):
    source = tmp_path / "library" / "hero.png"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"image")
    ensure_extracted_palette(recorder, source, _synthetic_two_tone)

    def _must_not_run():
        raise AssertionError("palette recomputed although the row exists")

    ensure_extracted_palette(recorder, source, _must_not_run)

    assert (
        db.execute(
            "SELECT count(*) FROM asset_derivatives "
            "WHERE file_path=? AND kind='extracted_palette'",
            (str(source.resolve()),),
        ).fetchone()[0]
        == 1
    )


def test_ensure_extracted_palette_without_recorder_is_noop(tmp_path):
    source = tmp_path / "hero.png"
    source.write_bytes(b"image")

    ensure_extracted_palette(None, source, _synthetic_two_tone)  # must not raise


def test_ensure_extracted_palette_failed_extraction_records_nothing(recorder, db, tmp_path):
    source = tmp_path / "library" / "hero.png"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"image")

    ensure_extracted_palette(recorder, source, lambda: None)

    assert (
        db.execute(
            "SELECT count(*) FROM asset_derivatives WHERE file_path=?",
            (str(source.resolve()),),
        ).fetchone()[0]
        == 0
    )


# ── ensure_audio_waveform: generate at most once ─────────────────────


def test_ensure_audio_waveform_records_payload_and_reuses_it(recorder, db, tmp_path, monkeypatch):
    source = tmp_path / "library" / "tone.wav"
    write_wav(source)

    first = ensure_audio_waveform(recorder, source)
    assert first is not None and first.startswith(b"\x89PNG")

    payload = recorder.payload_path(source, "audio_waveform")
    assert payload is not None and payload.read_bytes() == first
    rows = db.execute(
        "SELECT rel_path FROM asset_derivatives WHERE file_path=? "
        "AND kind='audio_waveform'",
        (str(source.resolve()),),
    ).fetchall()
    assert len(rows) == 1 and rows[0][0]

    def _must_not_run(*args, **kwargs):
        raise AssertionError("waveform regenerated although the row exists")

    monkeypatch.setattr(
        "AssetsManager.application.media.analysis.generate_waveform", _must_not_run
    )
    monkeypatch.setattr(
        "AssetsManager.application.media.analysis.generate_waveform_from_bytes",
        _must_not_run,
    )

    assert ensure_audio_waveform(recorder, source) == first


def test_ensure_audio_waveform_from_captured_body(recorder, tmp_path):
    source = tmp_path / "library" / "tone.wav"
    write_wav(source)

    data = ensure_audio_waveform(
        recorder, source, source_body=source.read_bytes(), source_suffix=".wav"
    )

    assert data is not None and data.startswith(b"\x89PNG")
    assert recorder.payload_path(source, "audio_waveform") is not None


def test_ensure_audio_waveform_failure_returns_none(recorder, tmp_path):
    source = tmp_path / "library" / "noise.bin"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"not audio")

    assert (
        ensure_audio_waveform(recorder, source, ffmpeg="missing-ffmpeg-xyz") is None
    )


# ── recorder failures must not break the analysis passes ────────────


class _BrokenRecorder:
    def lookup(self, file_path, kind):
        raise RuntimeError("db gone")

    def payload_path(self, file_path, kind):
        raise RuntimeError("db gone")

    def record(self, *args, **kwargs):
        raise RuntimeError("db gone")


def test_recorder_exceptions_do_not_break_palette_pass(tmp_path):
    source = tmp_path / "hero.png"
    source.write_bytes(b"image")

    ensure_extracted_palette(_BrokenRecorder(), source, _synthetic_two_tone)


def test_recorder_exceptions_do_not_break_waveform_pass(tmp_path):
    source = tmp_path / "tone.wav"
    write_wav(source)

    assert ensure_audio_waveform(_BrokenRecorder(), source) is None  # no raise
