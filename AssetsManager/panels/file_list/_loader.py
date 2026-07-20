"""ThumbnailLoader — parallel thumbnail loading via QThreadPool + QImageReader.

Performance: QImageReader in worker thread converts to QPixmap immediately,
eliminating main-thread format conversion. Bake depth limited by sidebar cfg.
"""
import logging
import os
import sqlite3
import contextlib
import threading
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from PySide6.QtCore import Qt, QSize, Signal, QObject, QRunnable, QThreadPool, QMutex
from PySide6.QtGui import QImage, QImageReader

from AssetsManager.application.thumbnail_service import thumbnail_cache_key
from AssetsManager.core.performance import PerformanceRecorder
from AssetsManager.panels.file_list._common import IMAGE_EXTS

_log = logging.getLogger(__name__)

BAKE_SIZE = 512  # nominal default; use get_bake_size() for runtime value
_stderr_redirect_lock = threading.Lock()


@dataclass(frozen=True)
class _Runtime:
    generation: int
    cache_dir: str
    repo: Any | None
    lib_root: str
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


@contextlib.contextmanager
def _suppress_libpng_warnings():
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
            if pix is not None:
                self._loader._on_image_loaded(
                    self._row, self._path, self._item_path, pix, self._runtime, started)
            else:
                self._loader._mark_failed(self._path, self._runtime, started)
        except Exception:
            _log.exception("Thumbnail load failed: %s", self._path)
            self._loader._mark_failed(self._path, self._runtime, started)


class _BakeTask(QRunnable):
    def __init__(self, loader, key, source_path, bake_size, runtime):
        super().__init__()
        self._loader = loader
        self._key = key
        self._source_path = source_path
        self._bake_size = bake_size
        self._runtime = runtime

    def run(self):
        try:
            reader = QImageReader(self._source_path)
            reader.setAutoTransform(True)
            sz = reader.size()
            if sz.isValid() and (sz.width() > self._bake_size or sz.height() > self._bake_size):
                reader.setScaledSize(sz.scaled(QSize(self._bake_size, self._bake_size),
                                                Qt.AspectRatioMode.KeepAspectRatio))
            with _suppress_libpng_warnings():
                img = reader.read()
            if img.isNull():
                return
            self._loader._store_baked_image(
                self._key, self._source_path, self._bake_size, img, self._runtime)
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
        self._cache_bytes = 0
        self._max_cache_bytes = max_cache_bytes
        self._max_admitted_tasks = max_admitted_tasks
        self._max_deferred_loads = max_deferred_loads
        self._mutex = QMutex()
        self._failed_paths: set[str] = set()
        self._failed_paths_max: int = 2000
        self._cache_dir: str = ""
        self._db_conn: sqlite3.Connection | None = None
        self._db_mutex = QMutex()
        self._lib_root: str = ""
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(3)
        self._regen_cancel = False
        self._stopped = False
        self._runtime_generation = 0
        self._task_condition = threading.Condition()
        self._active_tasks: dict[int, int] = defaultdict(int)
        self._invalidated_runtimes: dict[int, _Runtime] = {}
        from AssetsManager.repositories.thumbnail_repository import ThumbnailRepository
        self._repo: ThumbnailRepository | None = None
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

    def set_cache_db(self, conn):
        self._db_mutex.lock()
        self._mutex.lock()
        try:
            self._db_conn = conn
            if conn:
                from AssetsManager.repositories.thumbnail_repository import ThumbnailRepository
                self._repo = ThumbnailRepository(conn)
            else:
                self._repo = None
        finally:
            self._mutex.unlock()
            self._db_mutex.unlock()

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
            with self._task_condition:
                old_generation = self._runtime_generation
                self._invalidated_runtimes[old_generation] = self._runtime_locked()
                self._runtime_generation += 1
                self._task_condition.notify_all()
            self._cache.clear()
            self._cache_bytes = 0
            self._failed_paths.clear()
            self._queued_keys.clear()
            self._queued_generations.clear()
            self._deferred_loads.clear()
            self._pending_items.clear()
            self._regen_cancel = True
        finally:
            self._mutex.unlock()
        return old_generation

    def invalidate_tasks(self):
        """Backward-compatible name for invalidating the current runtime."""
        return self.invalidate_runtime()

    def wait_for_runtime(self, generation: int) -> None:
        """Wait without timeout for exactly one invalidated runtime's tasks."""
        self._mutex.lock()
        try:
            telemetry = self._invalidated_runtimes.get(generation, self._runtime_locked())
        finally:
            self._mutex.unlock()
        started = perf_counter() if telemetry.recorder is not None else None
        with self._task_condition:
            self._task_condition.wait_for(
                lambda: self._active_tasks.get(generation, 0) == 0
            )
        if telemetry.recorder is not None:
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

            if self._start_task(task, runtime.generation, priority=priority, runtime=runtime):
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
            generation,
            self._cache_dir,
            self._repo,
            self._lib_root,
            self._session_token,
            self._performance_recorder,
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

    def _is_active_runtime(self, runtime: _Runtime) -> bool:
        self._mutex.lock()
        try:
            return not self._regen_cancel and self._is_current_generation_locked(runtime.generation)
        finally:
            self._mutex.unlock()

    def set_size(self, size: int):
        if size == self._size:
            return
        self._size = size
        self._mutex.lock()
        self._cache.clear()
        self._cache_bytes = 0
        self._failed_paths.clear()
        self._queued_keys.clear()
        self._queued_generations.clear()
        self._deferred_loads.clear()
        self._pending_items.clear()
        self._mutex.unlock()

    @staticmethod
    def _cache_entry(value: _MemoryCacheEntry | tuple[QImage, float]) -> _MemoryCacheEntry:
        if isinstance(value, _MemoryCacheEntry):
            return value
        image, source_mtime = value
        return _MemoryCacheEntry(image, source_mtime, max(0, int(image.sizeInBytes())))

    def _remove_cached_locked(self, path: str) -> _MemoryCacheEntry | None:
        value = self._cache.pop(path, None)
        if value is None:
            return None
        entry = self._cache_entry(value)
        self._cache_bytes = max(0, self._cache_bytes - entry.byte_size)
        return entry

    def _store_cached_locked(self, path: str, image: QImage, source_mtime: float) -> tuple[bool, int, int]:
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
        self._cache_bytes += image_bytes
        return True, evicted_entries, evicted_bytes

    def request(self, row: int, file_path: str, priority: int = 0, item_path: str | None = None):
        self._stopped = False
        item_path = item_path or file_path
        self._mutex.lock()
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
            if abs(mtime - current_mtime) < 0.001:
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
        stored, evicted_entries, evicted_bytes = self._store_cached_locked(path, img, mtime)
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
        self._cache_bytes = 0
        self._failed_paths.clear()
        self._queued_keys.clear()
        self._queued_generations.clear()
        self._deferred_loads.clear()
        self._mutex.unlock()

    def stop(self):
        self._mutex.lock()
        self._stopped = True
        self._mutex.unlock()
        generation = self.invalidate_tasks()
        self.wait_for_runtime(generation)

    # ── Loading (worker thread) ──────────────────────────────────

    def _load_image(self, path: str, runtime: _Runtime | None = None) -> QImage | None:
        """Load image in worker thread — returns QImage (thread-safe)."""
        if not os.path.isfile(path):
            return None
        ext = Path(path).suffix.lower()
        if ext not in IMAGE_EXTS:
            return None
        runtime = runtime or self._runtime()
        if not self._is_current_generation(runtime.generation):
            return None
        key = self._disk_key(path)
        if get_bake_size() >= 0:
            cached = self._try_load_cached(key, path, runtime)
            if cached is not None:
                if runtime.recorder is not None:
                    self._record("thumbnail.cache", runtime=runtime, path=path, attributes={"tier": "disk", "outcome": "hit"})
                return cached
            if runtime.recorder is not None:
                self._record("thumbnail.cache", runtime=runtime, path=path, attributes={"tier": "disk", "outcome": "miss"})
        return self._read_with_qimagereader(path, runtime)

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

    def _read_with_qimagereader(self, path: str, runtime: _Runtime | None = None) -> QImage | None:
        """Thread-safe image loading via QImageReader. Returns unscaled QImage."""
        runtime = runtime or self._runtime()
        try:
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            orig = reader.size()
            if not orig.isValid():
                return None
            if orig.width() > self._size or orig.height() > self._size:
                reader.setScaledSize(orig.scaled(self._size, self._size,
                                                  Qt.AspectRatioMode.KeepAspectRatio))
            with _suppress_libpng_warnings():
                img = reader.read()
            if img.isNull() or not self._is_current_generation(runtime.generation):
                return None
            key = self._disk_key(path)
            if runtime.cache_dir and get_bake_size() >= 0 and self._should_bake(path, runtime.lib_root):
                self._queue_bake_native(key, path, runtime)
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

    def _try_load_cached(self, key: str, source_path: str, runtime: _Runtime) -> QImage | None:
        """Try disk cache — returns QImage (thread-safe)."""
        if not runtime.cache_dir:
            return None
        cached_file = os.path.join(runtime.cache_dir, f"{key}.webp")
        if not os.path.isfile(cached_file):
            return None
        if not self._is_current_generation(runtime.generation):
            return None
        self._db_mutex.lock()
        try:
            if runtime.repo:
                cached_mtime = runtime.repo.get_source_mtime(key)
                if cached_mtime is not None:
                    try:
                        current_mtime = os.path.getmtime(source_path)
                    except OSError:
                        current_mtime = 0
                    if abs(cached_mtime - current_mtime) > 0.001:
                        try:
                            os.remove(cached_file)
                        except OSError:
                            pass
                        if self._is_current_generation(runtime.generation):
                            runtime.repo.delete_entry(key)
                        return None
                    if self._is_current_generation(runtime.generation):
                        runtime.repo.touch_access(key)
        except Exception:
            _log.exception("Cache DB query failed")
        finally:
            self._db_mutex.unlock()
        if not os.path.isfile(cached_file):
            return None
        reader = QImageReader(cached_file)
        reader.setAutoTransform(True)
        if self._size < reader.size().width():
            reader.setScaledSize(reader.size().scaled(
                self._size, self._size, Qt.AspectRatioMode.KeepAspectRatio))
        with _suppress_libpng_warnings():
            img = reader.read()
        if img is None or img.isNull():
            return None
        return img

    def _queue_bake_native(self, key, source_path, runtime: _Runtime | None = None):
        bs = get_bake_size()
        if bs < 0:
            return False
        task = _BakeTask(self, key, source_path, bs, runtime or self._runtime())
        return self._start_task(task, task._runtime.generation, runtime=task._runtime)

    def _store_baked_image(self, key, source_path, bake_size, img, runtime: _Runtime):
        try:
            if not self._is_current_generation(runtime.generation):
                return
            tmp = os.path.join(runtime.cache_dir, f"{key}.webp.tmp")
            final = os.path.join(runtime.cache_dir, f"{key}.webp")
            os.makedirs(runtime.cache_dir, exist_ok=True)
            img.save(tmp, "WEBP", quality=85)
            os.replace(tmp, final)
            self._db_mutex.lock()
            try:
                if runtime.repo and self._is_current_generation(runtime.generation):
                    runtime.repo.upsert_entry(
                        key, source_path, os.path.getmtime(source_path),
                        os.path.getsize(source_path), bake_size, os.path.getsize(final),
                    )
            finally:
                self._db_mutex.unlock()
        except Exception:
            _log.exception("Bake DB insert failed")

    # ── Utility ──────────────────────────────────────────────────

    @staticmethod
    def _disk_key(path: str) -> str:
        return thumbnail_cache_key(path)

    def orphan_cleanup(self):
        if not self._cache_dir or not self._repo:
            return
        self._db_mutex.lock()
        try:
            entries = self._repo.list_all()
            for cache_key, source_path in entries:
                if not os.path.isfile(source_path) and not os.path.isdir(
                        os.path.dirname(source_path)):
                    try:
                        os.remove(os.path.join(self._cache_dir, f"{cache_key}.webp"))
                    except OSError:
                        pass
                    self._repo.delete_by_key(cache_key)
            self._repo.commit()
        except Exception:
            pass
        finally:
            self._db_mutex.unlock()

    def clear_thumb_cache(self) -> int:
        count = 0
        if self._cache_dir and os.path.isdir(self._cache_dir):
            for f in os.listdir(self._cache_dir):
                if f.endswith('.webp') or f.endswith('.webp.tmp'):
                    try:
                        os.remove(os.path.join(self._cache_dir, f))
                        count += 1
                    except OSError:
                        pass
        if self._repo:
            self._db_mutex.lock()
            try:
                self._repo.clear_all()
            except Exception:
                pass
            finally:
                self._db_mutex.unlock()
        return count

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
                    for root, dirs, files in os.walk(lib_root):
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
                                while not loader._queue_bake_native(key, path, runtime):
                                    if not loader._wait_for_task_capacity(runtime):
                                        return
                        except Exception:
                            pass
                        if on_progress and total > 0:
                            on_progress(i + 1, total)
                finally:
                    if on_complete and loader._is_active_runtime(runtime):
                        on_complete(len(images))
        admitted = self._start_task(_RegenTask(), runtime.generation, runtime=runtime)
        if not admitted and on_complete:
            on_complete(0)
        return admitted
