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

from PySide6.QtCore import Qt, QSize, Signal, QObject, QRunnable, QThreadPool, QMutex
from PySide6.QtGui import QImage, QImageReader

from AssetsManager.application.thumbnail_service import thumbnail_cache_key
from AssetsManager.panels.file_list._common import IMAGE_EXTS

_log = logging.getLogger(__name__)

BAKE_SIZE = 512  # nominal default; use get_bake_size() for runtime value
_stderr_redirect_lock = threading.Lock()


@dataclass(frozen=True)
class _Runtime:
    generation: int
    cache_dir: str
    repo: object | None
    lib_root: str

# ── Thumbnail quality (read from AppSettings) ────────────────
QUALITY_PRESETS = {
    "fast": 256,
    "default": 512,
    "high": 1024,
    "original": -1,
}

CACHE_LIMITS = {"fast": 400, "default": 400, "high": 200, "original": 50}


def get_bake_size() -> int:
    try:
        from AssetsManager.core.settings import AppSettings
        key = AppSettings.instance().get("thumb_quality", "default")
        return QUALITY_PRESETS.get(key, 512)
    except Exception:
        return 512


def _cache_limit() -> int:
    try:
        from AssetsManager.core.settings import AppSettings
        key = AppSettings.instance().get("thumb_quality", "default")
        return CACHE_LIMITS.get(key, 400)
    except Exception:
        return 400


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
        try:
            pix = self._loader._load_image(self._path, self._runtime)
            if pix is not None:
                self._loader._on_image_loaded(
                    self._row, self._path, self._item_path, pix, self._runtime.generation)
            else:
                self._loader._mark_failed(self._path, self._runtime.generation)
        except Exception:
            _log.exception("Thumbnail load failed: %s", self._path)
            self._loader._mark_failed(self._path, self._runtime.generation)


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


class ThumbnailLoader(QObject):
    thumbnail_ready = Signal(int, str, QImage)  # (model_row, source_path, QImage)

    def __init__(self, size=96, parent=None):
        super().__init__(parent)
        self._size = size
        self._queued_keys: set[str] = set()
        self._pending_items: dict[str, list[tuple[int, str]]] = defaultdict(list)
        self._cache: OrderedDict[str, tuple[QImage, float]] = OrderedDict()
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
        from AssetsManager.repositories.thumbnail_repository import ThumbnailRepository
        self._repo: ThumbnailRepository | None = None

    def set_cache_dir(self, path: str):
        self._mutex.lock()
        self._cache_dir = path
        self._mutex.unlock()
        if path:
            os.makedirs(path, exist_ok=True)

    def set_cache_db(self, conn):
        self._mutex.lock()
        self._db_mutex.lock()
        self._db_conn = conn
        if conn:
            from AssetsManager.repositories.thumbnail_repository import ThumbnailRepository
            self._repo = ThumbnailRepository(conn)
        else:
            self._repo = None
        self._db_mutex.unlock()
        self._mutex.unlock()

    def set_lib_root(self, path: str):
        self._mutex.lock()
        self._regen_cancel = True
        self._lib_root = str(Path(path).resolve())
        self._mutex.unlock()

    @property
    def runtime_generation(self) -> int:
        self._mutex.lock()
        try:
            return self._runtime_generation
        finally:
            self._mutex.unlock()

    def invalidate_runtime(self):
        """Discard state and queued work from the previous library runtime."""
        self._mutex.lock()
        try:
            self._runtime_generation += 1
            self._cache.clear()
            self._failed_paths.clear()
            self._queued_keys.clear()
            self._pending_items.clear()
            self._regen_cancel = True
        finally:
            self._mutex.unlock()
        self._pool.clear()

    def invalidate_tasks(self):
        """Backward-compatible name for invalidating the current runtime."""
        self.invalidate_runtime()

    def wait_for_tasks(self, timeout_ms: int = 1000) -> None:
        """Wait for already-running tasks after their runtime was invalidated."""
        try:
            self._pool.waitForDone(timeout_ms)
        except Exception:
            pass

    def _runtime(self) -> _Runtime:
        return _Runtime(self._runtime_generation, self._cache_dir, self._repo, self._lib_root)

    def _is_current_generation(self, generation: int) -> bool:
        self._mutex.lock()
        try:
            return self._is_current_generation_locked(generation)
        finally:
            self._mutex.unlock()

    def _is_current_generation_locked(self, generation: int) -> bool:
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
        self._failed_paths.clear()
        self._queued_keys.clear()
        self._mutex.unlock()

    def request(self, row: int, file_path: str, priority: int = 0, item_path: str | None = None):
        self._stopped = False
        item_path = item_path or file_path
        self._mutex.lock()
        runtime = self._runtime()
        if file_path in self._cache:
            pix, mtime = self._cache[file_path]
            try:
                current_mtime = os.path.getmtime(file_path)
            except OSError:
                self._cache.pop(file_path, None)
                self._mutex.unlock()
                return
            if abs(mtime - current_mtime) < 0.001:
                self._cache.move_to_end(file_path)
                self._mutex.unlock()
                self.thumbnail_ready.emit(row, item_path, pix)
                return
            self._cache.pop(file_path, None)
        if file_path in self._failed_paths:
            self._mutex.unlock()
            return
        if file_path in self._queued_keys:
            self._pending_items[file_path].append((row, item_path))
            self._mutex.unlock()
            return
        if file_path not in self._queued_keys:
            self._queued_keys.add(file_path)
            self._pending_items[file_path].append((row, item_path))
            self._mutex.unlock()
            task = _LoadTask(self, row, file_path, item_path, runtime)
            try:
                self._pool.start(task, priority=1 if priority == 0 else 0)
            except TypeError:
                self._pool.start(task)
        else:
            self._mutex.unlock()

    def _on_image_loaded(self, row, path, item_path, img: QImage, generation=None):
        """Called from worker thread — emit QImage (safe for cross-thread marshalling).
        The main-thread receiver converts QImage → QPixmap."""
        self._mutex.lock()
        if self._stopped or (generation is not None and not self._is_current_generation_locked(generation)):
            self._mutex.unlock()
            return
        self._queued_keys.discard(path)
        pending = self._pending_items.pop(path, [])
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0.0
        self._cache[path] = (img, mtime)
        limit = _cache_limit()
        if len(self._cache) > limit:
            self._cache.popitem(last=False)
        self._mutex.unlock()
        if not pending:
            pending = [(row, item_path)]
        for pending_row, pending_item_path in pending:
            self.thumbnail_ready.emit(pending_row, pending_item_path, img)

    def _mark_failed(self, path, generation=None):
        self._mutex.lock()
        if self._stopped or (generation is not None and not self._is_current_generation_locked(generation)):
            self._mutex.unlock()
            return
        self._queued_keys.discard(path)
        self._pending_items.pop(path, None)
        if len(self._failed_paths) >= self._failed_paths_max:
            self._failed_paths.clear()
        self._failed_paths.add(path)
        self._mutex.unlock()

    def clear_queue(self):
        self._mutex.lock()
        self._queued_keys.clear()
        self._pending_items.clear()
        self._mutex.unlock()

    def clear_cache(self):
        self._mutex.lock()
        self._cache.clear()
        self._failed_paths.clear()
        self._queued_keys.clear()
        self._mutex.unlock()

    def stop(self):
        self._mutex.lock()
        self._stopped = True
        self._mutex.unlock()
        self.invalidate_tasks()
        self._pool.clear()
        try:
            self._pool.waitForDone(1000)
        except Exception:
            pass

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
                return cached
        return self._read_with_qimagereader(path, runtime)

    def _read_with_qimagereader(self, path: str, runtime: _Runtime | None = None) -> QImage | None:
        """Thread-safe image loading via QImageReader. Returns unscaled QImage."""
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
        self._mutex.lock()
        if not self._is_current_generation_locked(runtime.generation):
            self._mutex.unlock()
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
                        if self._is_current_generation_locked(runtime.generation):
                            runtime.repo.delete_entry(key)
                        return None
                    if self._is_current_generation_locked(runtime.generation):
                        runtime.repo.touch_access(key)
        except Exception:
            _log.exception("Cache DB query failed")
        finally:
            self._db_mutex.unlock()
            self._mutex.unlock()
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
            return
        task = _BakeTask(self, key, source_path, bs, runtime or self._runtime())
        self._pool.start(task)

    def _store_baked_image(self, key, source_path, bake_size, img, runtime: _Runtime):
        self._mutex.lock()
        try:
            if not self._is_current_generation_locked(runtime.generation):
                return
            tmp = os.path.join(runtime.cache_dir, f"{key}.webp.tmp")
            final = os.path.join(runtime.cache_dir, f"{key}.webp")
            os.makedirs(runtime.cache_dir, exist_ok=True)
            img.save(tmp, "WEBP", quality=85)
            os.replace(tmp, final)
            self._db_mutex.lock()
            try:
                if runtime.repo and self._is_current_generation_locked(runtime.generation):
                    runtime.repo.upsert_entry(
                        key, source_path, os.path.getmtime(source_path),
                        os.path.getsize(source_path), bake_size, os.path.getsize(final),
                    )
            finally:
                self._db_mutex.unlock()
        except Exception:
            _log.exception("Bake DB insert failed")
        finally:
            self._mutex.unlock()

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

    def regenerate_all(self, lib_root: str, on_progress=None):
        self._mutex.lock()
        self._regen_cancel = False
        runtime = self._runtime()
        self._mutex.unlock()
        loader = self
        class _RegenTask(QRunnable):
            def __init__(s):
                super().__init__()
                s.setAutoDelete(False)
            def run(s):
                images = []
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
                            loader._queue_bake_native(key, path, runtime)
                    except Exception:
                        pass
                    if on_progress and total > 0:
                        on_progress(i + 1, total)
        self._pool.start(_RegenTask())
