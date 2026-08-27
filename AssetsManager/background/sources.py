"""Frame producers for the background pipeline.

* ``ImageSource``  — static image frames (CPU-friendly, default).
* ``VideoSource``  — QMediaPlayer + QVideoSink frames (feeds the GL backend;
  falls back to the latest decoded frame as a QImage when GL is absent).
* ``ShaderSource`` — procedural: no frames at all; the GL backend renders the
  selected Shadertoy-style preset directly.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage, QImageReader

try:  # QtMultimedia is an optional module in some slim installs
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoFrame, QVideoSink
except Exception:  # pragma: no cover - environment without multimedia
    QMediaPlayer = None  # type: ignore[assignment,misc]
    QAudioOutput = None  # type: ignore[assignment,misc]
    QVideoSink = None  # type: ignore[assignment,misc]
    QVideoFrame = None  # type: ignore[assignment,misc]


class ImageSource:
    """Static image source: decodes once, serves cached QImage frames."""

    def __init__(self, path: str):
        self.path = path
        self._frame: QImage | None = None
        self._failed = False

    def key(self) -> str:
        return f"image:{self.path}"

    def frame(self) -> QImage | None:
        if self._frame is not None or self._failed:
            return self._frame
        reader = QImageReader(self.path)
        image = reader.read()
        if image.isNull():
            self._failed = True
            return None
        self._frame = image
        return self._frame


class VideoSource(QObject):
    """Playback-backed video frames, looped and muted.

    Emits :attr:`frame_ready` for each decoded frame (as QImage) and retains
    the latest one for CPU-side fallback rendering.
    """

    frame_ready = Signal(object)  # QImage
    state_changed = Signal(str)  # "playing" | "paused" | "stopped" | "error"

    def __init__(self, path: str, parent: QObject | None = None):
        super().__init__(parent)
        self.path = path
        self._latest: QImage | None = None
        self._player = None
        self._sink = None
        self._errors: list[str] = []

    def _ensure_player(self) -> bool:
        if self._player is not None:
            return True
        if QMediaPlayer is None:  # pragma: no cover - env without QtMultimedia
            self._errors.append("QtMultimedia unavailable")
            return False
        self._player = QMediaPlayer(self)
        self._sink = QVideoSink(self)
        self._player.setVideoOutput(self._sink)
        self._sink.videoFrameChanged.connect(self._on_frame)
        self._player.errorOccurred.connect(self._on_error)
        self._player.setLoops(QMediaPlayer.Loops.Infinite)
        audio = QAudioOutput(self)
        audio.setMuted(True)
        self._player.setAudioOutput(audio)
        self._player.setSource(self.path)
        return True

    def _on_frame(self, frame) -> None:
        image = VideoSource.frame_to_image(frame)
        if image is not None:
            self._latest = image
            self.frame_ready.emit(image)

    def _on_error(self, error, message: str) -> None:
        if error and error.name != "NoError":
            self._errors.append(message)
            self.state_changed.emit("error")

    @staticmethod
    def frame_to_image(frame) -> QImage | None:
        """Best-effort QVideoFrame -> QImage; GPU-resident frames may fail."""
        try:
            image = frame.toImage()
            return image if not image.isNull() else None
        except Exception:
            return None

    def start(self) -> bool:
        if not self._ensure_player():
            return False
        self._player.play()
        self.state_changed.emit("playing")
        return True

    def pause(self) -> None:
        if self._player is not None:
            self._player.pause()
            self.state_changed.emit("paused")

    def stop(self) -> None:
        if self._player is not None:
            self._player.stop()
            self.state_changed.emit("stopped")

    def current_frame(self) -> QImage | None:
        return self._latest

    def errors(self) -> list[str]:
        return list(self._errors)


class ShaderSource:
    """Procedural shader background — descriptor only; rendering is GL work.

    The preset name is the source "content"; effect intensity maps onto the
    preset's ``u_strength`` uniform (0..1 when Shadertoy-style presets use
    iTime/iResolution only, presets may ignore it).
    """

    def __init__(self, preset_key: str):
        self.preset_key = preset_key

    def key(self) -> str:
        return f"shader:{self.preset_key}"

    def frame(self) -> QImage | None:
        return None  # procedural — no frames