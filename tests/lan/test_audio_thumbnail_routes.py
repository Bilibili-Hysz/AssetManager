"""LAN thumbnail routes for audio waveforms and the palette pass (N-B2).

The audio request path mirrors the N-B decoder integration: the original
bytes are never served as a thumbnail, the on-demand waveform is generated
at most once (the ``asset_derivatives`` row is the marker) and the recorded
PNG payload feeds every later request. Image generations also record the
params-only ``extracted_palette`` row.
"""

from __future__ import annotations

import io
import math
import sqlite3
import struct
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from AssetsManager.application.media.derivatives import MediaDerivativesRecorder
from AssetsManager.lan.routes._helpers import LAN_APP_KEY
from tests.lan.support.api_helpers import _make_client, _make_lan_app


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _write_wav(path: Path, *, seconds: float = 0.4, rate: int = 8000) -> Path:
    total = int(rate * seconds)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        frames = bytearray()
        for i in range(total):
            frames += struct.pack(
                "<h", int(20000 * math.sin(2 * math.pi * 440.0 * i / rate))
            )
        wav.writeframes(bytes(frames))
    return path


def _attach_recorder(app, conn: sqlite3.Connection, tmp_path: Path):
    import dataclasses

    from AssetsManager.core.db_migrations import migrate

    recorder = MediaDerivativesRecorder(lambda: conn, tmp_path / "data_dir")
    # The LAN fixture DB starts from the baseline schema; migration v37 adds
    # the asset_derivatives registry the recorder writes through.
    migrate(conn)
    lan = app[LAN_APP_KEY]
    # LanScopedServices is frozen; republish the bundle with the runtime
    # snapshot the production server attaches (bootstrap LibraryScopedServices).
    lan.services = dataclasses.replace(
        lan.services,
        runtime_services=SimpleNamespace(media_derivatives_recorder=recorder),
    )
    return recorder


@pytest.mark.anyio
async def test_thumbnail_route_renders_audio_waveform_and_records(
    tmp_path,
):
    app, library, conn = _make_lan_app(tmp_path)
    recorder = _attach_recorder(app, conn, tmp_path)
    source = _write_wav(library / "tone.wav")
    client = await _make_client(app)
    try:
        response = await client.get("/api/thumbnails/tone.wav", params={"size": "512"})
        assert response.status == 200
        assert response.headers["Content-Type"] == "image/png"
        body = await response.read()
        assert body.startswith(b"\x89PNG")

        from PIL import Image

        with Image.open(io.BytesIO(body)) as image:
            image.verify()

        payload = recorder.payload_path(source, "audio_waveform")
        assert payload is not None
        assert payload.read_bytes() == body
    finally:
        await client.close()


@pytest.mark.anyio
async def test_thumbnail_route_second_request_hits_row_without_recompute(
    tmp_path, monkeypatch
):
    app, library, conn = _make_lan_app(tmp_path)
    _attach_recorder(app, conn, tmp_path)
    _write_wav(library / "tone.wav")
    client = await _make_client(app)
    try:
        first = await client.get("/api/thumbnails/tone.wav")
        assert first.status == 200
        body = await first.read()

        def _must_not_run(*args, **kwargs):
            raise AssertionError("waveform recomputed although the row exists")

        monkeypatch.setattr(
            "AssetsManager.application.media.analysis.generate_waveform",
            _must_not_run,
        )
        monkeypatch.setattr(
            "AssetsManager.application.media.analysis.generate_waveform_from_bytes",
            _must_not_run,
        )

        second = await client.get("/api/thumbnails/tone.wav")
        assert second.status == 200
        assert second.headers["Content-Type"] == "image/png"
        assert await second.read() == body
    finally:
        await client.close()


@pytest.mark.anyio
async def test_audio_thumbnail_never_serves_original_bytes(tmp_path):
    """size >= 1024 is the original-bytes request for images; audio must
    deliver the waveform PNG instead of the (non-image) source bytes."""
    app, library, _conn = _make_lan_app(tmp_path)
    _write_wav(library / "tone.wav")
    client = await _make_client(app)
    try:
        response = await client.get("/api/thumbnails/tone.wav", params={"size": "1024"})
        assert response.status == 200
        assert response.headers["Content-Type"] == "image/png"
        assert (await response.read()).startswith(b"\x89PNG")
    finally:
        await client.close()


@pytest.mark.anyio
async def test_thumbnail_route_records_palette_row_for_image(tmp_path):
    from PIL import Image

    app, library, conn = _make_lan_app(tmp_path)
    recorder = _attach_recorder(app, conn, tmp_path)
    source = library / "art.png"
    Image.new("RGB", (32, 32), (255, 0, 0)).save(source, format="PNG")
    client = await _make_client(app)
    try:
        response = await client.get("/api/thumbnails/art.png", params={"size": "64"})
        assert response.status == 200
        assert response.headers["Content-Type"] == "image/webp"

        row = recorder.lookup(source, "extracted_palette")
        assert row is not None
        assert row.rel_path == ""  # params-only row, no payload file
        # The palette is extracted from the generated (lossy WEBP) thumbnail,
        # so the dominant swatch is near-red rather than exact.
        red, green, blue = (
            int(row.params["dominant"][i : i + 2], 16) for i in (1, 3, 5)
        )
        assert red >= 0xF0 and green <= 0x0F and blue <= 0x0F
        assert len(row.params["colors"]) >= 1

        derivatives_root = tmp_path / "data_dir" / "derivatives"
        palette_files = (
            list(derivatives_root.glob("extracted_palette/*"))
            if derivatives_root.exists()
            else []
        )
        assert palette_files == []
    finally:
        await client.close()
