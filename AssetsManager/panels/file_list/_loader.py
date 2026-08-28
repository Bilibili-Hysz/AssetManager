"""ThumbnailLoader — parallel thumbnail loading via QThreadPool + QImageReader.

Performance: QImageReader in worker thread converts to QPixmap immediately,
eliminating main-thread format conversion. Bake depth limited by sidebar cfg.
"""
import logging
import os
import contextlib
import secrets
import threading
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from PySide6.QtCore import (
    Qt, Signal, QObject, QRunnable, QThreadPool, QMutex,
    QByteArray, QBuffer, QIODevice,
)
from PySide6.QtGui import QImage, QImageReader

from AssetsManager.application.thumbnail_service import (
    MAX_THUMBNAIL_SOURCE_BYTES,
    ThumbnailService,
    thumbnail_cache_key,
)
from AssetsManager.core.file_snapshot import FileIdentity, read_snapshot
from AssetsManager.core.thumbnail_key import (
    WEBP_RENDER_PROFILES,
    legacy_thumbnail_cache_key,
    profiled_thumbnail_cache_key_v3,
)
from AssetsManager.application.thumbnail_cache_lifecycle import (
    cache_owner_lock,
    remove_artifacts,
)
from AssetsManager.core.performance import PerformanceRecorder
from AssetsManager.panels.file_list._common import IMAGE_EXTS, VIDEO_EXTS

_log = logging.getLogger(__name__)

_stderr_redirect_lock = threading.Lock()

# ── Dedicated ffmpeg pool ─────────────────────────────────────────
# ffmpeg video-frame extraction can take from hundreds of milliseconds to
# seconds. Running those subprocesses on the loader's own worker threads would
# let a slow video starve concurrent image thumbnails, so all ffmpeg work is
# dispatched onto this dedicated, capacity-bounded pool instead.  It lives in
# the presentation layer on purpose: the architecture boundary forbids Qt
# imports from non-presentation packages (application/domain/repositories).
ffmpeg_pool = QThreadPool()
ffmpeg_pool.setMaxThreadCount(2)  # cap concurrent ffmpeg processes
_FFMPEG_POOL_DRAIN_TIMEOUT_MS = 10_000

# Sentinel returned by ``_load_video_frame`` when the frame extraction has been
# dispatched to the dedicated ``ffmpeg_pool``: the calling load task must not
# treat the request as failed — delivery arrives from the ffmpeg worker once
# the frame lands on disk.


class _VideoFramePending:
    """Marker returned when video frame extraction is running on the ffmpeg pool."""


_VIDEO_FRAME_DEFERRED = _VideoFramePending()


@dataclass(frozen=True)
class _Runtime:
    generation: int
    cache_dir: str
    lib_root: str
    thumbnail_service: Any | None
    cache_epoch: int
    session_token: str | None
    recorder: PerformanceRecorder | None


@dataclass(frozen=True)
class _MemoryCacheEntry:
    image: QImage
    source_mtime: float
    byte_size: int

# ── Thumbnail quality (read from AppSettings) ────────────────
QUALITY_PRESETS = {
    "fast": 256,
    "default": 512,
    "high": 1024,
    "original": -1,
}

DEFAULT_MAX_ADMITTED_TASKS = 96
DEFAULT_MEMORY_CACHE_BYTES = 64 * 1024 * 1024
_TOUCH_THROTTLE_SECONDS = 60.0


def get_bake_size() -> int:
    try:
        from AssetsManager.core.settings import AppSettings
        key = AppSettings.instance().get("thumb_quality", "default")
        return QUALITY_PRESETS.get(key, 512)
    except Exception:
        return 512


def _bake_max_depth(lib_root: str) -> int:
    try:
        from AssetsManager.core.settings import AppSettings
        cfg = AppSettings.instance().get("sidebar_depth_cfg", {})
        return cfg.get(lib_root, cfg.get("default", 2))
    except Exception:
        return 2


def _read_qimage_bytes(body: bytes, max_size: int) -> QImage | None:
    """Decode one captured image body without reopening its source path."""
    data = QByteArray(body)
    buffer = QBuffer()
    buffer.setData(data)
    if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
        return None
    try:
        reader = QImageReader(buffer)
        reader.setAutoTransform(True)
        size = reader.size()
        if not size.isValid():
            return None
        if max_size >= 0 and (size.width() > max_size or size.height() > max_size):
            reader.setScaledSize(size.scaled(
                max_size, max_size, Qt.AspectRatioMode.KeepAspectRatio
            ))
        with _suppress_libpng_warnings():
            image = reader.read()
        return None if image.isNull() else image
    finally:
        buffer.close()


@contextlib.contextmanager
def _suppress_libpng_warnings():
    # Process-wide stderr (fd 2) redirection: QImageReader's libpng warnings
    # are written by the C library directly to fd 2, so Python-level
    # contextlib.redirect_stderr (which only swaps sys.stderr) cannot capture
    # them.  While this is active, other threads' stderr output is lost, so it
    # must only be called from worker threads and kept as short as possible.
    _log.debug("Redirecting process stderr (fd 2) to suppress libpng warnings")
    with _stderr_redirect_lock:
        devnull = os.open(os.devnull, os.O_WRONLY)
        old_stderr = os.dup(2)
        os.dup2(devnull, 2)
        os.close(devnull)
        try:
            yield
        finally:
            os.dup2(old_stderr, 2)
            os.close(old_stderr)
    _log.debug("Restored process stderr (fd 2)")


class _LoadTask(QRunnable):
    def __init__(self, loader, row, path, item_path, runtime):
        super().__init__()
        self.setAutoDelete(False)
        self._loader = loader
        self._row = row
        self._path = path
        self._item_path = item_path
        self._runtime = runtime

    def run(self):
        started = perf_counter() if self._runtime.recorder is not None else None
        try:
            pix = self._loader._load_image(self._path, self._runtime)
            if pix is _VIDEO_FRAME_DEFERRED:
                # Video frame extraction is running on the dedicated ffmpeg
                # pool; the frame is delivered from that worker when ready.
                return
            if pix is not None:
                self._loader._on_image_loaded(
                    self._row, self._path, self._item_path, pix, self._runtime, started)
            else:
                self._loader._mark_failed(self._path, self._runtime, started)
        except Exception:
            _log.exception("Thumbnail load failed: %s", self._path)
            self._loader._mark_failed(self._path, self._runtime, started)


class _ExtractVideoFrameTask(QRunnable):
    """Runs ffmpeg first-frame extraction on the dedicated ffmpeg pool."""

    def __init__(self, loader, source_path: str, body: bytes, frame_path: str, runtime: _Runtime):
        super().__init__()
        self._loader = loader
        self._source_path = source_path
        self._body = body
        self._frame_path = frame_path
        self._runtime = runtime

    def run(self):
        frame = Path(self._frame_path)
        ok = False
        try:
            if not self._loader._is_current_cache_epoch(self._runtime):
                return
            with cache_owner_lock(frame.parent):
                if not self._loader._is_current_cache_epoch(self._runtime):
                    return
                ok = ThumbnailService._extract_video_frame_from_bytes(
                    self._body, Path(self._source_path).suffix, frame
                )
                if ok and not self._loader._is_current_cache_epoch(self._runtime):
                    try:
                        frame.unlink()
                    except OSError:
                        pass
                    return
        except Exception:
            _log.exception("Video frame extraction failed: %s", self._source_path)
            ok = False
        if ok and self._loader._is_current_cache_epoch(self._runtime):
            self._loader._on_video_frame_extracted(
                self._source_path, self._frame_path, self._runtime
            )
        elif ok:
            return
        else:
            self._loader._mark_failed(self._source_path, self._runtime)


class _BakeTask(QRunnable):
    def __init__(
        self, loader, key, source_path, bake_size, runtime, *,
        body: bytes | None = None, source_identity: FileIdentity | None = None,
    ):
        super().__init__()
        self._loader = loader
        self._key = key
        self._source_path = source_path
        self._body = body
        self._bake_size = bake_size
        self._runtime = runtime
        self._source_identity = source_identity

    def run(self):
        try:
            body = self._body
            identity = self._source_identity
            if body is None:
                snapshot = self._loader._snapshot_source(self._source_path, self._runtime)
                if snapshot is None:
                    return
                body, identity = snapshot
            img = _read_qimage_bytes(body, self._bake_size)
            if img is None:
                return
            key = self._loader._disk_key(self._source_path, identity)
            self._loader._store_baked_image(
                key, self._source_path, self._bake_size, img,
                self._runtime, source_identity=identity,
            )
        except Exception:
            _log.exception("Bake task failed: %s", self._source_path)


class _TrackedTask(QRunnable):
    def __init__(self, loader, task, generation):
        super().__init__()
        self._loader = loader
        self._task = task
        self._generation = generation

    def run(self):
        try:
            self._task.run()
        finally:
            self._loader._task_finished(self._generation)


class ThumbnailLoader(QObject):
    thumbnail_ready = Signal(int, str, QImage)  # (model_row, source_path, QImage)

    def __init__(
        self,
        size=96,
        parent=None,
        *,
        max_admitted_tasks: int = DEFAULT_MAX_ADMITTED_TASKS,
        max_cache_bytes: int = DEFAULT_MEMORY_CACHE_BYTES,
        max_deferred_loads: int | None = None,
    ):
        super().__init__(parent)
        max_deferred_loads = max_admitted_tasks if max_deferred_loads is None else max_deferred_loads
        if max_admitted_tasks < 1 or max_cache_bytes < 1 or max_deferred_loads < 1:
            raise ValueError("ThumbnailLoader budgets must be positive")
        self._size = size
        self._queued_keys: set[str] = set()
        self._queued_generations: dict[str, int] = {}
        self._deferred_loads: OrderedDict[str, tuple[_LoadTask, _Runtime, int]] = OrderedDict()
        self._pending_items: dict[str, list[tuple[int, str]]] = defaultdict(list)
        self._cache: OrderedDict[str, _MemoryCacheEntry | tuple[QImage, float]] = OrderedDict()
        self._source_identities: dict[str, FileIdentity] = {}
        self._cache_bytes = 0
        self._max_cache_bytes = max_cache_bytes
        self._max_admitted_tasks = max_admitted_tasks
        self._max_deferred_loads = max_deferred_loads
        self._mutex = QMutex()
        self._failed_paths: set[str] = set()
        self._failed_paths_max: int = 2000
        self._cache_dir: str = ""
        self._lib_root: str = ""
        self._cache_epoch = 0
        self._cache_io_lock = threading.Lock()
        self._last_touch: dict[str, float] = {}  # key -> monotonic timestamp (touch throttle)
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(3)
        self._regen_cancel = False
        self._stopped = False
        self._runtime_generation = 0
        self._task_condition = threading.Condition()
        self._active_tasks: dict[int, int] = defaultdict(int)
        self._invalidated_runtimes: dict[int, _Runtime] = {}
        self._thumbnail_service: Any | None = None
        self._performance_recorder: PerformanceRecorder | None = None
        self._session_token: str | None = None

    def set_performance_context(
        self,
        recorder: PerformanceRecorder | None,
        session_token: str | None,
    ) -> None:
        """Bind optional diagnostics to the currently scoped library session."""
        self._mutex.lock()
        try:
            try:
                self._performance_recorder = recorder if recorder is not None and recorder.enabled else None
            except Exception:
                self._performance_recorder = None
            self._session_token = session_token
        finally:
            self._mutex.unlock()

    def set_cache_dir(self, path: str):
        self._mutex.lock()
        self._cache_dir = path
        self._mutex.unlock()
        if path:
            os.makedirs(path, exist_ok=True)

    def _invalidate_runtime_locked(self) -> int:
        """Invalidate the current generation while ``_mutex`` is held."""
        with self._task_condition:
            old_generation = self._runtime_generation
            self._invalidated_runtimes[old_generation] = self._runtime_locked()
            self._runtime_generation += 1
            self._task_condition.notify_all()
        self._cache.clear()
        self._source_identities.clear()
        self._cache_bytes = 0
        self._failed_paths.clear()
        self._queued_keys.clear()
        self._queued_generations.clear()
        self._deferred_loads.clear()
        self._pending_items.clear()
        self._last_touch.clear()
        self._regen_cancel = True
        return old_generation

    def bind_runtime(
        self,
        thumbnail_service: Any | None,
        cache_dir: str,
        lib_root: str,
        recorder: PerformanceRecorder | None = None,
        session_token: str | None = None,
    ) -> None:
        """Atomically bind one service/filesystem runtime snapshot."""
        self._mutex.lock()
        try:
            old_generation = self._invalidate_runtime_locked()
            self._thumbnail_service = thumbnail_service
            self._cache_dir = str(cache_dir or "")
            self._lib_root = str(Path(lib_root).resolve()) if lib_root else ""
            try:
                self._performance_recorder = (
                    recorder if recorder is not None and recorder.enabled else None
                )
            except Exception:
                self._performance_recorder = None
            self._session_token = session_token
        finally:
            self._mutex.unlock()
        self.wait_for_runtime(old_generation)
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)

    def set_lib_root(self, path: str):
        self._mutex.lock()
        self._regen_cancel = True
        self._lib_root = str(Path(path).resolve())
        self._mutex.unlock()

    @property
    def runtime_generation(self) -> int:
        with self._task_condition:
            return self._runtime_generation

    def invalidate_runtime(self):
        """Discard state and queued work from the previous library runtime."""
        self._mutex.lock()
        try:
            old_generation = self._invalidate_runtime_locked()
        finally:
            self._mutex.unlock()
        return old_generation

    def invalidate_tasks(self):
        """Backward-compatible name for invalidating the current runtime."""
        return self.invalidate_runtime()

    def wait_for_runtime(self, generation: int, timeout: float | None = 5.0) -> None:
        """Wait (bounded by default) for exactly one invalidated runtime's tasks.

        A stuck task thread must not block the calling (main) thread forever;
        on timeout the pool is cleared (cancelling not-yet-started tasks) and
        a warning is logged.  Pass ``timeout=None`` for an explicit unbounded
        wait.
        """
        self._mutex.lock()
        try:
            telemetry = self._invalidated_runtimes.get(generation)
        finally:
            self._mutex.unlock()
        started = perf_counter() if telemetry is not None and telemetry.recorder is not None else None
        timed_out = False
        with self._task_condition:
            if not self._task_condition.wait_for(
                lambda: self._active_tasks.get(generation, 0) == 0,
                timeout=timeout,
            ):
                timed_out = True
        if timed_out:
            self._pool.clear()
            _log.warning(
                "Timed out after %ss waiting for thumbnail runtime %s drain; "
                "cleared not-yet-started pool tasks",
                timeout, generation,
            )
        self._mutex.lock()
        try:
            self._invalidated_runtimes.pop(generation, None)
        finally:
            self._mutex.unlock()
        if telemetry is not None and telemetry.recorder is not None:
            self._record("thumbnail.drain", runtime=telemetry, generation=generation, started=started, attributes={"outcome": "completed"})

    def _start_task(self, task, generation: int, priority: int = 0, runtime: _Runtime | None = None) -> bool:
        """Register and start work atomically against runtime invalidation."""
        runtime = runtime or self._telemetry_snapshot()
        with self._task_condition:
            if generation != self._runtime_generation:
                if runtime.recorder is not None:
                    self._record("thumbnail.queue", runtime=runtime, generation=generation, attributes={"outcome": "stale_rejected", "queue_depth": 0})
                return False
            admitted_tasks = sum(self._active_tasks.values())
            if admitted_tasks >= self._max_admitted_tasks:
                if runtime.recorder is not None:
                    self._record(
                        "thumbnail.queue", runtime=runtime, generation=generation,
                        attributes={
                            "outcome": "capacity_rejected",
                            "queue_depth": admitted_tasks,
                            "queue_capacity": self._max_admitted_tasks,
                        },
                    )
                return False
            self._active_tasks[generation] += 1
            queue_depth = sum(self._active_tasks.values())
        tracked = _TrackedTask(self, task, generation)
        try:
            try:
                self._pool.start(tracked, priority=priority)
            except TypeError:
                self._pool.start(tracked)
        except Exception:
            self._task_finished(generation)
            raise
        if runtime.recorder is not None:
            self._record("thumbnail.queue", runtime=runtime, generation=generation, attributes={"outcome": "queued", "queue_depth": queue_depth})
        return True

    def _task_finished(self, generation: int) -> None:
        with self._task_condition:
            remaining = self._active_tasks[generation] - 1
            if remaining:
                self._active_tasks[generation] = remaining
            else:
                self._active_tasks.pop(generation, None)
            self._task_condition.notify_all()
        self._drain_deferred_loads()

    def _drain_deferred_loads(self) -> None:
        """Submit retained visible requests as admitted capacity becomes free."""
        while True:
            self._mutex.lock()
            try:
                if not self._deferred_loads:
                    return
                path, (task, runtime, priority) = self._deferred_loads.popitem(last=False)
                current = self._is_current_generation_locked(runtime.generation)
                if not current:
                    if self._queued_generations.get(path) == runtime.generation:
                        self._queued_keys.discard(path)
                        self._queued_generations.pop(path, None)
                        self._pending_items.pop(path, None)
                    continue
            finally:
                self._mutex.unlock()

            try:
                started = self._start_task(task, runtime.generation, priority=priority, runtime=runtime)
            except Exception:
                _log.exception("Failed to start deferred thumbnail load: %s", path)
                self._mutex.lock()
                try:
                    self._queued_keys.discard(path)
                    self._queued_generations.pop(path, None)
                    self._pending_items.pop(path, None)
                finally:
                    self._mutex.unlock()
                return
            if started:
                continue

            self._mutex.lock()
            try:
                if self._is_current_generation_locked(runtime.generation):
                    self._deferred_loads.setdefault(path, (task, runtime, priority))
                elif self._queued_generations.get(path) == runtime.generation:
                    self._queued_keys.discard(path)
                    self._queued_generations.pop(path, None)
                    self._pending_items.pop(path, None)
            finally:
                self._mutex.unlock()
            return

    def _wait_for_task_capacity(self, runtime: _Runtime) -> bool:
        """Backpressure regeneration without creating a second work queue."""
        with self._task_condition:
            self._task_condition.wait_for(
                lambda: runtime.generation != self._runtime_generation
                or sum(self._active_tasks.values()) < max(2, self._max_admitted_tasks)
            )
            return runtime.generation == self._runtime_generation

    def _runtime(self) -> _Runtime:
        return self._telemetry_snapshot()

    def _telemetry_snapshot(self) -> _Runtime:
        self._mutex.lock()
        try:
            return self._runtime_locked()
        finally:
            self._mutex.unlock()

    def _runtime_locked(self) -> _Runtime:
        with self._task_condition:
            generation = self._runtime_generation
        return _Runtime(
            generation=generation,
            cache_dir=self._cache_dir,
            thumbnail_service=self._thumbnail_service,
            lib_root=self._lib_root,
            cache_epoch=self._cache_epoch,
            session_token=self._session_token,
            recorder=self._performance_recorder,
        )

    def _is_current_generation(self, generation: int) -> bool:
        self._mutex.lock()
        try:
            return self._is_current_generation_locked(generation)
        finally:
            self._mutex.unlock()

    def _is_current_generation_locked(self, generation: int) -> bool:
        with self._task_condition:
            return self._runtime_generation == generation

    def _is_current_cache_epoch(self, runtime: _Runtime) -> bool:
        self._mutex.lock()
        try:
            return (
                self._is_current_generation_locked(runtime.generation)
                and self._cache_epoch == runtime.cache_epoch
            )
        finally:
            self._mutex.unlock()

    def _is_active_runtime(self, runtime: _Runtime) -> bool:
        self._mutex.lock()
        try:
            return not self._regen_cancel and self._is_current_generation_locked(runtime.generation)
        finally:
            self._mutex.unlock()

    def set_size(self, size: int):
        self._mutex.lock()
        try:
            if size == self._size:
                return
            self._size = size
            self._cache.clear()
            self._cache_bytes = 0
            self._failed_paths.clear()
            self._queued_keys.clear()
            self._queued_generations.clear()
            self._deferred_loads.clear()
            self._pending_items.clear()
        finally:
            self._mutex.unlock()

    @staticmethod
    def _cache_entry(value: _MemoryCacheEntry | tuple[QImage, float]) -> _MemoryCacheEntry:
        if isinstance(value, _MemoryCacheEntry):
            return value
        image, source_mtime = value
        return _MemoryCacheEntry(image, source_mtime, max(0, int(image.sizeInBytes())))

    def _remove_cached_locked(self, path: str) -> _MemoryCacheEntry | None:
        value = self._cache.pop(path, None)
        self._source_identities.pop(path, None)
        if value is None:
            return None
        entry = self._cache_entry(value)
        self._cache_bytes = max(0, self._cache_bytes - entry.byte_size)
        return entry

    def _store_cached_locked(
        self, path: str, image: QImage, source_mtime: float,
        source_identity: FileIdentity | None = None,
    ) -> tuple[bool, int, int]:
        self._remove_cached_locked(path)
        image_bytes = max(0, int(image.sizeInBytes()))
        if image_bytes > self._max_cache_bytes:
            return False, 0, 0
        evicted_entries = 0
        evicted_bytes = 0
        while self._cache and self._cache_bytes + image_bytes > self._max_cache_bytes:
            _, value = self._cache.popitem(last=False)
            entry = self._cache_entry(value)
            self._cache_bytes = max(0, self._cache_bytes - entry.byte_size)
            evicted_entries += 1
            evicted_bytes += entry.byte_size
        self._cache[path] = _MemoryCacheEntry(image, source_mtime, image_bytes)
        if source_identity is not None:
            self._source_identities[path] = source_identity
        self._cache_bytes += image_bytes
        return True, evicted_entries, evicted_bytes

    def request(self, row: int, file_path: str, priority: int = 0, item_path: str | None = None):
        item_path = item_path or file_path
        self._mutex.lock()
        if self._stopped:
            # The loader is stopped (e.g. after stop()): do not re-admit
            # requests or restart the pool.  _stopped is only cleared on an
            # explicit future start path.
            self._mutex.unlock()
            return
        runtime = self._runtime_locked()
        if file_path in self._cache:
            entry = self._cache_entry(self._cache[file_path])
            pix, mtime = entry.image, entry.source_mtime
            try:
                current_mtime = os.path.getmtime(file_path)
            except OSError:
                self._remove_cached_locked(file_path)
                self._mutex.unlock()
                return
            source_identity = self._source_identities.get(file_path)
            current_identity = None
            if source_identity is not None:
                try:
                    current_stat = os.stat(file_path)
                    current_identity = FileIdentity.from_stat(current_stat)
                except OSError:
                    self._remove_cached_locked(file_path)
                    self._mutex.unlock()
                    return
            if (
                source_identity is not None
                and current_identity == source_identity
            ) or (
                source_identity is None
                and abs(mtime - current_mtime) < 0.001
            ):
                self._cache.move_to_end(file_path)
                self._mutex.unlock()
                if runtime.recorder is not None:
                    self._record("thumbnail.cache", runtime=runtime, path=file_path, attributes={"tier": "memory", "outcome": "hit"})
                self.thumbnail_ready.emit(row, item_path, pix)
                return
            self._remove_cached_locked(file_path)
        if file_path in self._failed_paths:
            self._mutex.unlock()
            if runtime.recorder is not None:
                self._record("thumbnail.queue", runtime=runtime, path=file_path, attributes={"outcome": "failed_suppressed", "queue_depth": 0})
            return
        if file_path in self._queued_keys:
            self._pending_items[file_path].append((row, item_path))
            if priority == 0 and file_path in self._deferred_loads:
                task, deferred_runtime, _ = self._deferred_loads[file_path]
                self._deferred_loads[file_path] = (task, deferred_runtime, 1)
                self._deferred_loads.move_to_end(file_path, last=False)
            queue_depth = len(self._queued_keys)
            self._mutex.unlock()
            if runtime.recorder is not None:
                self._record("thumbnail.queue", runtime=runtime, path=file_path, attributes={"outcome": "deduplicated", "queue_depth": queue_depth})
            return
        if file_path not in self._queued_keys:
            self._queued_keys.add(file_path)
            self._queued_generations[file_path] = runtime.generation
            self._pending_items[file_path].append((row, item_path))
            queue_depth = len(self._queued_keys)
            task = _LoadTask(self, row, file_path, item_path, runtime)
            qt_priority = 1 if priority == 0 else 0
            try:
                admitted = self._start_task(task, runtime.generation, priority=qt_priority, runtime=runtime)
            except Exception:
                self._queued_keys.discard(file_path)
                self._queued_generations.pop(file_path, None)
                self._pending_items.pop(file_path, None)
                self._mutex.unlock()
                raise
            if not admitted:
                if self._is_current_generation_locked(runtime.generation):
                    if len(self._deferred_loads) < self._max_deferred_loads:
                        self._deferred_loads[file_path] = (task, runtime, qt_priority)
                    elif priority == 0:
                        evicted_path = None
                        for candidate_path, (_, _, candidate_priority) in reversed(self._deferred_loads.items()):
                            if candidate_priority == 0:
                                evicted_path = candidate_path
                                break
                        if evicted_path is not None:
                            self._deferred_loads.pop(evicted_path)
                            if self._queued_generations.get(evicted_path) == runtime.generation:
                                self._queued_keys.discard(evicted_path)
                                self._queued_generations.pop(evicted_path, None)
                                self._pending_items.pop(evicted_path, None)
                            self._deferred_loads[file_path] = (task, runtime, qt_priority)
                            self._deferred_loads.move_to_end(file_path, last=False)
                        else:
                            self._queued_keys.discard(file_path)
                            self._queued_generations.pop(file_path, None)
                            self._pending_items.pop(file_path, None)
                    else:
                        self._queued_keys.discard(file_path)
                        self._queued_generations.pop(file_path, None)
                        self._pending_items.pop(file_path, None)
                else:
                    self._queued_keys.discard(file_path)
                    self._queued_generations.pop(file_path, None)
                    self._pending_items.pop(file_path, None)
            self._mutex.unlock()
            if runtime.recorder is not None:
                self._record("thumbnail.cache", runtime=runtime, path=file_path, attributes={"tier": "memory", "outcome": "miss"})
                self._record("thumbnail.queue", runtime=runtime, path=file_path, attributes={"outcome": "requested", "queue_depth": queue_depth})
        else:
            self._mutex.unlock()

    def _on_image_loaded(
        self,
        row,
        path,
        item_path,
        img: QImage,
        runtime: _Runtime | int | None = None,
        started: float | None = None,
    ):
        """Called from worker thread — emit QImage (safe for cross-thread marshalling).
        The main-thread receiver converts QImage → QPixmap."""
        self._mutex.lock()
        if isinstance(runtime, int):
            generation = runtime
            runtime = None
        else:
            generation = runtime.generation if runtime is not None else None
        if self._stopped or (generation is not None and not self._is_current_generation_locked(generation)):
            self._mutex.unlock()
            if runtime is not None and runtime.recorder is not None:
                self._record("thumbnail.load", runtime=runtime, path=path, started=started, attributes={"outcome": "stale_discard"})
            return
        self._mutex.unlock()
        self._mutex.lock()
        try:
            identity = self._source_identities.get(path)
        finally:
            self._mutex.unlock()
        mtime = identity.mtime_ns / 1_000_000_000 if identity is not None else 0.0
        if identity is None:
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                mtime = 0.0
        self._mutex.lock()
        if self._stopped or (generation is not None and not self._is_current_generation_locked(generation)):
            self._mutex.unlock()
            if runtime is not None and runtime.recorder is not None:
                self._record("thumbnail.load", runtime=runtime, path=path, started=started, attributes={"outcome": "stale_discard"})
            return
        self._queued_keys.discard(path)
        self._queued_generations.pop(path, None)
        pending = self._pending_items.pop(path, [])
        source_identity = self._source_identities.get(path)
        stored, evicted_entries, evicted_bytes = self._store_cached_locked(
            path, img, mtime, source_identity,
        )
        cache_bytes = self._cache_bytes
        self._mutex.unlock()
        if runtime is not None and runtime.recorder is not None:
            self._record("thumbnail.load", runtime=runtime, path=path, started=started, attributes={"outcome": "success", "fanout": len(pending)})
            self._record(
                "thumbnail.cache", runtime=runtime, path=path,
                attributes={
                    "tier": "memory",
                    "outcome": "stored" if stored else "oversize_bypassed",
                    "entry_bytes": max(0, int(img.sizeInBytes())),
                    "cache_bytes": cache_bytes,
                    "cache_capacity_bytes": self._max_cache_bytes,
                    "evicted_entries": evicted_entries,
                    "evicted_bytes": evicted_bytes,
                },
            )
        if not pending:
            pending = [(row, item_path)]
        for pending_row, pending_item_path in pending:
            self.thumbnail_ready.emit(pending_row, pending_item_path, img)

    def _mark_failed(
        self,
        path,
        runtime: _Runtime | int | None = None,
        started: float | None = None,
    ):
        self._mutex.lock()
        if isinstance(runtime, int):
            generation = runtime
            runtime = None
        else:
            generation = runtime.generation if runtime is not None else None
        if self._stopped or (generation is not None and not self._is_current_generation_locked(generation)):
            self._mutex.unlock()
            if runtime is not None and runtime.recorder is not None:
                self._record("thumbnail.load", runtime=runtime, path=path, started=started, attributes={"outcome": "stale_discard"})
            return
        self._queued_keys.discard(path)
        self._queued_generations.pop(path, None)
        self._pending_items.pop(path, None)
        if len(self._failed_paths) >= self._failed_paths_max:
            self._failed_paths.clear()
        self._failed_paths.add(path)
        self._mutex.unlock()
        if runtime is not None and runtime.recorder is not None:
            self._record("thumbnail.load", runtime=runtime, path=path, started=started, attributes={"outcome": "failed"})

    def clear_queue(self):
        self._mutex.lock()
        self._queued_keys.clear()
        self._queued_generations.clear()
        self._deferred_loads.clear()
        self._pending_items.clear()
        self._mutex.unlock()

    def retain_deferred(self, paths: set[str]) -> None:
        """Discard delayed work that has left the current viewport window."""
        self._mutex.lock()
        try:
            for path in [path for path in self._deferred_loads if path not in paths]:
                self._deferred_loads.pop(path)
                self._queued_keys.discard(path)
                self._queued_generations.pop(path, None)
                self._pending_items.pop(path, None)
        finally:
            self._mutex.unlock()

    def clear_cache(self):
        self._mutex.lock()
        self._cache.clear()
        self._source_identities.clear()
        self._cache_bytes = 0
        self._failed_paths.clear()
        self._queued_keys.clear()
        self._queued_generations.clear()
        self._deferred_loads.clear()
        self._pending_items.clear()
        self._mutex.unlock()

    def stop(self):
        self._mutex.lock()
        self._stopped = True
        self._mutex.unlock()
        generation = self.invalidate_tasks()
        self.wait_for_runtime(generation)
        # Drain the dedicated ffmpeg pool (bounded) so in-flight video frame
        # extraction cannot outlive the panel / process shutdown.
        ffmpeg_pool.waitForDone(int(_FFMPEG_POOL_DRAIN_TIMEOUT_MS))

    # ── Loading (worker thread) ──────────────────────────────────

    def _snapshot_source(
        self, path: str, runtime: _Runtime,
    ) -> tuple[bytes, FileIdentity] | None:
        """Capture one bounded source snapshot for desktop decoding."""
        source = Path(path)
        root = Path(runtime.lib_root) if runtime.lib_root else source.parent
        try:
            return read_snapshot(
                root,
                source,
                max_bytes=MAX_THUMBNAIL_SOURCE_BYTES,
            )
        except (OSError, ValueError):
            _log.debug("Desktop source snapshot failed: %s", path, exc_info=True)
            return None

    def _load_image(
        self, path: str, runtime: _Runtime | None = None
    ) -> QImage | _VideoFramePending | None:
        """Load one image from a bounded final-open source snapshot."""
        runtime = runtime or self._runtime()
        if not self._is_current_generation(runtime.generation):
            return None
        ext = Path(path).suffix.lower()
        if ext in VIDEO_EXTS:
            return self._load_video_frame(path, runtime)
        if ext not in IMAGE_EXTS:
            return None
        key = self._disk_key(path)
        bake_size = get_bake_size()
        if bake_size >= 0:
            cached = None
            for profile in self._webp_profiles_for_size(bake_size):
                v3_key = self._disk_profile_key(path, profile)
                cached = self._try_load_cached(
                    v3_key, path, runtime, bake_size=bake_size,
                    render_profile=profile,
                )
                if cached is not None:
                    break
            if cached is None:
                cached = self._try_load_cached(
                    key, path, runtime, bake_size=bake_size,
                )
            if cached is None:
                legacy_key = legacy_thumbnail_cache_key(path)
                if legacy_key != key:
                    cached = self._try_load_cached(
                        legacy_key, path, runtime, bake_size=bake_size,
                    )
            if cached is not None:
                if runtime.recorder is not None:
                    self._record("thumbnail.cache", runtime=runtime, path=path, attributes={"tier": "disk", "outcome": "hit"})
                return cached
            if runtime.recorder is not None:
                self._record("thumbnail.cache", runtime=runtime, path=path, attributes={"tier": "disk", "outcome": "miss"})
        snapshot = self._snapshot_source(path, runtime)
        if snapshot is None:
            return None
        body, identity = snapshot
        self._mutex.lock()
        try:
            if self._is_current_generation_locked(runtime.generation):
                self._source_identities[path] = identity
        finally:
            self._mutex.unlock()
        return self._read_with_qimagereader(
            path, runtime, body=body, source_identity=identity,
        )

    def _load_video_frame(
        self, path: str, runtime: _Runtime
    ) -> QImage | _VideoFramePending | None:
        """Load a video thumbnail from its cached first frame.

        If the frame already exists on disk it is read directly (matches the
        ``{cache_key}.jpg`` filename written by the thumbnail service).  When
        the frame is missing, extraction is dispatched to the dedicated
        ``ffmpeg_pool`` and ``_VIDEO_FRAME_DEFERRED`` is returned — the frame
        is delivered from the ffmpeg worker once it lands on disk, so ffmpeg
        duration never holds a loader worker thread.
        """
        service = runtime.thumbnail_service
        if service is None or not runtime.cache_dir:
            return None
        if not self._is_current_generation(runtime.generation):
            return None
        key = self._disk_key(path)
        frame = os.path.join(runtime.cache_dir, f"{key}.jpg")
        if os.path.isfile(frame):
            self._register_video_frame_metadata(
                path, frame, runtime, cache_key=key,
            )
            return self._read_with_qimagereader(frame, runtime, bake=False)
        legacy_key = legacy_thumbnail_cache_key(path)
        legacy_frame = os.path.join(runtime.cache_dir, f"{legacy_key}.jpg")
        if legacy_key != key and os.path.isfile(legacy_frame):
            self._register_video_frame_metadata(
                path, legacy_frame, runtime, cache_key=legacy_key,
            )
            return self._read_with_qimagereader(legacy_frame, runtime, bake=False)
        snapshot = self._snapshot_source(path, runtime)
        if snapshot is None:
            return None
        body, identity = snapshot
        self._mutex.lock()
        try:
            if self._is_current_generation_locked(runtime.generation):
                self._source_identities[path] = identity
        finally:
            self._mutex.unlock()
        key = self._disk_key(path, identity)
        frame = os.path.join(runtime.cache_dir, f"{key}.jpg")
        self._start_video_frame_extraction(path, body, frame, runtime)
        return _VIDEO_FRAME_DEFERRED

    def _start_video_frame_extraction(
        self, source_path: str, body: bytes, frame_path: str, runtime: _Runtime
    ) -> None:
        """Queue one ffmpeg extraction from a captured source body."""
        task = _ExtractVideoFrameTask(self, source_path, body, frame_path, runtime)
        ffmpeg_pool.start(task)

    def _on_video_frame_extracted(
        self, source_path: str, frame_path: str, runtime: _Runtime
    ) -> None:
        """Deliver a video thumbnail once its frame has been extracted.

        Runs on a dedicated ffmpeg pool worker thread; the normal
        cross-thread delivery path applies.
        """
        img = self._read_with_qimagereader(frame_path, runtime, bake=False)
        if img is None:
            self._mark_failed(source_path, runtime)
            return
        source_identity = self._source_identities.get(source_path)
        self._register_video_frame_metadata(
            source_path,
            frame_path,
            runtime,
            source_identity=source_identity,
            cache_key=self._disk_key(source_path, source_identity),
        )
        self._on_image_loaded(0, source_path, source_path, img, runtime)

    @staticmethod
    def _register_video_frame_metadata(
        source_path: str,
        frame_path: str,
        runtime: _Runtime,
        *,
        source_identity: FileIdentity | None = None,
        cache_key: str | None = None,
    ) -> None:
        service = runtime.thumbnail_service
        if service is None:
            return
        register = getattr(service, "register_video_frame_metadata", None)
        try:
            if callable(register):
                register(
                    runtime.lib_root,
                    source_path,
                    frame_path,
                    source_identity,
                    cache_key=cache_key,
                )
                return
            if source_identity is None:
                return
            frame_size = os.path.getsize(frame_path)
            service.upsert_cache_metadata(
                runtime.lib_root,
                cache_key or ThumbnailService._cache_key(source_path, source_identity),
                source_path,
                source_identity.mtime_ns / 1_000_000_000,
                source_identity.size,
                512,
                frame_size,
                source_mtime_ns=source_identity.mtime_ns,
                artifact_kind="jpg",
            )
        except Exception:
            _log.exception("Video frame metadata insert failed: %s", frame_path)

    def _record(
        self,
        name: str,
        *,
        runtime: _Runtime | None = None,
        generation: int | None = None,
        path: str | None = None,
        started: float | None = None,
        attributes: dict[str, str | int | float | bool] | None = None,
    ) -> None:
        recorder = runtime.recorder if runtime is not None else self._performance_recorder
        if recorder is None:
            return
        try:
            recorder.record(
                name,
                (perf_counter() - started) * 1000 if started is not None else 0.0,
                session_token=runtime.session_token if runtime is not None else self._session_token,
                generation=runtime.generation if runtime is not None else generation,
                path=path,
                attributes=attributes,
            )
        except Exception:
            # Diagnostics must not affect loader state or cross-thread delivery.
            pass

    def _read_with_qimagereader(
        self,
        path: str,
        runtime: _Runtime | None = None,
        bake: bool = True,
        *,
        body: bytes | None = None,
        source_identity: FileIdentity | None = None,
    ) -> QImage | None:
        """Decode a captured image body, retaining the legacy path seam."""
        runtime = runtime or self._runtime()
        try:
            if body is None:
                snapshot = self._snapshot_source(path, runtime)
                if snapshot is None:
                    return None
                body, source_identity = snapshot
            img = _read_qimage_bytes(body, self._size)
            if img is None or not self._is_current_generation(runtime.generation):
                return None
            if bake:
                key = self._disk_key(path)
                if runtime.cache_dir and get_bake_size() >= 0 and self._should_bake(path, runtime.lib_root):
                    profile = self._webp_profile(get_bake_size())
                    key = self._disk_profile_key(path, profile, source_identity)
                    self._queue_bake_native(
                        key, path, body, source_identity, runtime,
                    )
            return img
        except Exception:
            _log.exception("QImageReader failed: %s", path)
            return None

    def _should_bake(self, source_path: str, lib_root: str | None = None) -> bool:
        lib_root = self._lib_root if lib_root is None else lib_root
        if not lib_root:
            return True
        try:
            parent_dir = os.path.dirname(source_path)
            rel = os.path.relpath(parent_dir, lib_root)
            depth = 0 if rel == '.' else rel.count(os.sep) + 1
            max_depth = _bake_max_depth(lib_root)
            return depth <= max_depth
        except (ValueError, OSError):
            return True

    def _try_load_cached(
        self,
        key: str,
        source_path: str,
        runtime: _Runtime,
        *,
        bake_size: int | None = None,
        render_profile: str | None = None,
    ) -> QImage | None:
        """Try disk cache — returns QImage (thread-safe)."""
        if not runtime.cache_dir:
            return None
        cached_file = os.path.join(runtime.cache_dir, f"{key}.webp")
        if not os.path.isfile(cached_file) or not self._is_current_generation(runtime.generation):
            return None
        effective_bake_size = get_bake_size() if bake_size is None else bake_size
        required_size = max(self._size, effective_bake_size, 0)
        service = runtime.thumbnail_service
        metadata = None
        if service is not None:
            try:
                get_metadata = getattr(service, "get_cache_metadata", None)
                if callable(get_metadata):
                    metadata = get_metadata(runtime.lib_root, key)
                    source_mtime = getattr(metadata, "source_mtime", None)
                    if metadata is not None and not isinstance(source_mtime, (int, float)):
                        metadata = None
                if metadata is None:
                    cached_mtime = service.get_cached_source_mtime(runtime.lib_root, key)
                    if isinstance(cached_mtime, (int, float)):
                        metadata = type("LegacyMetadata", (), {
                            "source_mtime": cached_mtime,
                            "source_mtime_ns": None,
                            "source_size": 0,
                            "baked_size": 0,
                            "artifact_kind": "webp",
                        })()
                if metadata is not None:
                    if getattr(metadata, "artifact_kind", "webp") != "webp":
                        return None
                    if render_profile is not None:
                        stored_profile = getattr(metadata, "render_profile", None)
                        if stored_profile not in (None, render_profile):
                            return None
                    cached_mtime = getattr(metadata, "source_mtime", None)
                    if cached_mtime is not None:
                        try:
                            current_mtime = os.path.getmtime(source_path)
                        except OSError:
                            current_mtime = 0
                        if abs(cached_mtime - current_mtime) > 0.001:
                            try:
                                with cache_owner_lock(runtime.cache_dir):
                                    if os.path.isfile(cached_file):
                                        os.remove(cached_file)
                                    if self._is_current_generation(runtime.generation):
                                        service.delete_cache_metadata(runtime.lib_root, key)
                            except (OSError, TimeoutError):
                                _log.warning("Failed to invalidate stale thumbnail: %s", cached_file)
                            return None
                    baked_size = getattr(metadata, "baked_size", 0) or 0
                    if baked_size > 0 and baked_size < required_size:
                        return None
            except Exception:
                _log.exception("Cache metadata query failed")
                metadata = None
        if not os.path.isfile(cached_file):
            return None
        reader = QImageReader(cached_file)
        reader.setAutoTransform(True)
        image_size = reader.size()
        if not image_size.isValid():
            return None
        if (metadata is None or not (getattr(metadata, "baked_size", 0) or 0)) and required_size:
            if max(image_size.width(), image_size.height()) < required_size:
                return None
        if self._size > 0 and max(image_size.width(), image_size.height()) > self._size:
            reader.setScaledSize(image_size.scaled(
                self._size, self._size, Qt.AspectRatioMode.KeepAspectRatio))
        with _suppress_libpng_warnings():
            img = reader.read()
        if img is None or img.isNull():
            return None
        if service is not None and metadata is not None and self._is_current_generation(runtime.generation):
            self._touch_cache_metadata(service, runtime.lib_root, key)
        return img

    def _touch_cache_metadata(self, service, lib_root: str, key: str) -> None:
        """Throttled disk-cache metadata touch: at most one DB write per key
        per minute, so steady disk-cache hits do not write-amplify SQLite.

        ``_last_touch`` is protected by ``_mutex`` (not ``_cache_io_lock``):
        ``_cache_io_lock`` is acquired while holding ``_mutex`` in
        ``clear_thumb_cache``/``_store_baked_image``, so taking it here while
        ``_invalidate_runtime_locked`` holds ``_mutex`` could deadlock.
        """
        self._mutex.lock()
        try:
            now = perf_counter()
            last = self._last_touch.get(key)
            if last is not None and now - last < _TOUCH_THROTTLE_SECONDS:
                return
            self._last_touch[key] = now
        finally:
            self._mutex.unlock()
        service.touch_cache_metadata(lib_root, key)

    def _queue_bake_native(
        self, key, source_path, body: bytes | None = None,
        source_identity: FileIdentity | None = None,
        runtime: _Runtime | None = None,
    ):
        bs = get_bake_size()
        if bs < 0:
            return False
        runtime = runtime or self._runtime()
        task = _BakeTask(
            self, key, source_path, bs, runtime,
            body=body, source_identity=source_identity,
        )
        return self._start_task(task, task._runtime.generation, runtime=task._runtime)

    def _store_baked_image(
        self, key, source_path, bake_size, img, runtime: _Runtime,
        *, source_identity: FileIdentity | None = None,
    ):
        tmp = os.path.join(
            runtime.cache_dir,
            f"{key}.{runtime.generation}.{runtime.cache_epoch}."
            f"{os.getpid()}.{secrets.token_hex(8)}.webp.tmp",
        )
        final = os.path.join(runtime.cache_dir, f"{key}.webp")
        try:
            with self._cache_io_lock:
                with cache_owner_lock(runtime.cache_dir):
                    if not self._is_current_cache_epoch(runtime):
                        return
                    os.makedirs(runtime.cache_dir, exist_ok=True)
                    img.save(tmp, "WEBP", quality=85)
                    if not self._is_current_cache_epoch(runtime):
                        return
                    os.replace(tmp, final)
                    service = runtime.thumbnail_service
                    if service is not None and self._is_current_cache_epoch(runtime):
                        identity = source_identity
                        if identity is None:
                            snapshot = self._snapshot_source(source_path, runtime)
                            if snapshot is None:
                                return
                            _body, identity = snapshot
                        service.upsert_cache_metadata(
                            runtime.lib_root, key, source_path,
                            identity.mtime_ns / 1_000_000_000,
                            identity.size, bake_size, os.path.getsize(final),
                            source_mtime_ns=identity.mtime_ns,
                            artifact_kind="webp",
                            render_profile=self._webp_profile(bake_size),
                        )
        except Exception:
            _log.exception("Bake cache metadata insert failed")
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    # ── Utility ──────────────────────────────────────────────────

    @staticmethod
    def _webp_profiles_for_size(bake_size: int) -> list[str]:
        return [
            profile
            for profile, size in sorted(WEBP_RENDER_PROFILES.items(), key=lambda item: item[1])
            if size >= max(bake_size, 0)
        ]

    @staticmethod
    def _webp_profile(bake_size: int) -> str:
        candidates = sorted(WEBP_RENDER_PROFILES.items(), key=lambda item: item[1])
        for profile, size in candidates:
            if size >= bake_size:
                return profile
        return candidates[-1][0]

    @staticmethod
    def _disk_profile_key(
        path: str,
        profile: str,
        identity: FileIdentity | tuple[int, int, int, int] | None = None,
    ) -> str:
        return profiled_thumbnail_cache_key_v3(path, profile, identity)

    @staticmethod
    def _disk_key(
        path: str,
        identity: FileIdentity | tuple[int, int, int, int] | None = None,
    ) -> str:
        return thumbnail_cache_key(path, identity)

    def orphan_cleanup(self):
        runtime = self._runtime()
        service = runtime.thumbnail_service
        if not runtime.cache_dir or service is None:
            return
        try:
            entries = service.list_cache_metadata(runtime.lib_root)
            for cache_key, source_path, _source_mtime in entries:
                if not self._is_current_generation(runtime.generation):
                    return
                if not os.path.isfile(source_path):
                    try:
                        with cache_owner_lock(runtime.cache_dir):
                            remove_artifacts(runtime.cache_dir, cache_key)
                            if self._is_current_generation(runtime.generation):
                                service.delete_cache_metadata(runtime.lib_root, cache_key)
                    except TimeoutError:
                        _log.warning("Thumbnail cache owner busy during orphan cleanup")
        except Exception:
            _log.exception("Thumbnail orphan cleanup failed")

    def clear_thumb_cache(self) -> int:
        removed, _failed = self.clear_thumb_cache_detailed()
        return removed

    def clear_thumb_cache_detailed(self, on_progress=None) -> tuple[int, int]:
        """Remove every cached thumbnail artifact; return ``(removed, failed)``.

        Synchronous — callers that must not block the GUI thread should use
        :meth:`clear_thumb_cache_async`.  ``on_progress(done, total)`` is
        invoked after each removal attempt (from the calling thread).
        """
        removed = 0
        failed = 0
        files: list[str] = []
        runtime: _Runtime | None = None
        with self._cache_io_lock:
            self._mutex.lock()
            try:
                self._cache_epoch += 1
                runtime = self._runtime_locked()
            finally:
                self._mutex.unlock()
            try:
                with cache_owner_lock(runtime.cache_dir):
                    self._mutex.lock()
                    try:
                        if runtime.cache_dir and os.path.isdir(runtime.cache_dir):
                            try:
                                files = [
                                    f for f in os.listdir(runtime.cache_dir)
                                    if f.endswith(('.webp', '.jpg', '.webp.tmp', '.jpg.tmp'))
                                ]
                            except OSError:
                                pass
                        clear_metadata = (
                            runtime.thumbnail_service is not None
                            and self._is_current_generation_locked(runtime.generation)
                        )
                    finally:
                        self._mutex.unlock()
                    if clear_metadata:
                        try:
                            runtime.thumbnail_service.clear_cache_metadata(runtime.lib_root)
                        except Exception:
                            _log.exception("Thumbnail metadata clear failed")
                    total = len(files)
                    for f in files:
                        try:
                            os.remove(os.path.join(runtime.cache_dir, f))
                            removed += 1
                        except OSError:
                            failed += 1
                            _log.warning("Failed to remove stale thumbnail cache file: %s", f)
                        if on_progress is not None:
                            on_progress(removed + failed, total)
            except TimeoutError:
                _log.warning("Thumbnail cache owner busy during clear")
        return removed, failed

    def clear_thumb_cache_async(self, on_progress=None, on_complete=None) -> bool:
        """Run :meth:`clear_thumb_cache_detailed` on the loader's worker pool.

        Mirrors :meth:`regenerate_all`: ``on_progress`` / ``on_complete``
        run on the worker thread, so callers must marshal UI updates back
        to the GUI thread.  ``on_complete(removed, failed)`` always fires —
        including when the task is not admitted (reported as ``(0, 0)``) —
        so the caller's progress UI can always reset itself.
        """
        self._mutex.lock()
        runtime = self._runtime_locked()
        self._mutex.unlock()
        loader = self

        class _ClearTask(QRunnable):
            def __init__(self):
                super().__init__()
                self.setAutoDelete(False)

            def run(self):
                removed, failed = 0, 0
                try:
                    removed, failed = loader.clear_thumb_cache_detailed(
                        on_progress=on_progress)
                except Exception:
                    _log.exception("Thumbnail cache clear failed")
                finally:
                    # Fires exactly once, even when the clear failed or was
                    # not admitted, so the caller's progress UI resets.
                    if on_complete:
                        on_complete(removed, failed)

        admitted = self._start_task(_ClearTask(), runtime.generation, runtime=runtime)
        if not admitted and on_complete:
            on_complete(0, 0)
        return admitted

    def regenerate_all(self, lib_root: str, on_progress=None, on_complete=None) -> bool:
        self._mutex.lock()
        self._regen_cancel = False
        runtime = self._runtime_locked()
        self._mutex.unlock()
        loader = self
        class _RegenTask(QRunnable):
            def __init__(self):
                super().__init__()
                self.setAutoDelete(False)

            def run(self):
                images = []
                try:
                    for root, _dirs, files in os.walk(lib_root):
                        if not loader._is_active_runtime(runtime):
                            return
                        for f in files:
                            if f.startswith('.') or not loader._is_active_runtime(runtime):
                                if not loader._is_active_runtime(runtime):
                                    return
                                continue
                            ext = os.path.splitext(f)[1].lower()
                            if ext in IMAGE_EXTS:
                                images.append(os.path.join(root, f))
                    total = len(images)
                    for i, path in enumerate(images):
                        if not loader._is_active_runtime(runtime):
                            return
                        try:
                            key = loader._disk_key(path)
                            if loader._should_bake(path, runtime.lib_root):
                                bake_size = get_bake_size()
                                if bake_size < 0:
                                    continue
                                if loader._max_admitted_tasks == 1:
                                    _BakeTask(loader, key, path, bake_size, runtime).run()
                                    continue
                                while not loader._queue_bake_native(key, path, runtime=runtime):
                                    if not loader._wait_for_task_capacity(runtime):
                                        return
                        except Exception:
                            pass
                        if on_progress and total > 0:
                            on_progress(i + 1, total)
                finally:
                    # Always report completion — even when the run was
                    # cancelled by a library switch (_regen_cancel) — so the
                    # caller (e.g. settings dialog progress UI) can reset
                    # itself instead of waiting forever.
                    if on_complete:
                        if loader._is_active_runtime(runtime):
                            on_complete(len(images))
                        else:
                            on_complete(0)  # cancelled — caller resets its UI
        admitted = self._start_task(_RegenTask(), runtime.generation, runtime=runtime)
        if not admitted and on_complete:
            on_complete(0)
        return admitted
