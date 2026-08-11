# ═══════════════════════════════════════════════════════════════════
# FileSystemModel
# ═══════════════════════════════════════════════════════════════════
from collections import deque
from contextlib import contextmanager
import logging
from time import perf_counter
import os
from pathlib import Path
from typing import cast
import weakref
from PySide6.QtCore import Qt, QAbstractListModel, QModelIndex, QFileInfo, QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QIcon
from shiboken6 import Shiboken
from AssetsManager.application.asset_filters import (
    extension_matches_category,
    is_hidden,
    matches_exclude,
    matches_search,
    normalize_filter_category,
    normalize_sort_key,
    sort_key_for_entry,
)
from AssetsManager.application.context import LibrarySession
from AssetsManager.core.cache import LRUCache

_log = logging.getLogger(__name__)

class _ScanSignals(QObject):
    scan_done = Signal(list, dict, object)  # (entries, stat_cache, error)

class _ScanTask(QRunnable):
    def __init__(self, path: str, gen: int):
        super().__init__()
        self._path = path
        self._gen = gen
        self.signals = _ScanSignals()

    def run(self):
        # Capture before any work: the Python wrapper may be released (and the
        # signal object with it) while the pool runs this task, but the
        # emission itself must always reach a live sender.
        signals = self.signals
        entries = []
        stat_cache: dict[str, os.stat_result] = {}
        error: OSError | None = None
        try:
            for entry in os.scandir(self._path):
                entries.append(entry)
                try:
                    stat_cache[entry.path] = entry.stat()
                except OSError:
                    pass
        except OSError as exc:
            error = exc
        signals.scan_done.emit(entries, stat_cache, error)

class FileSystemModel(QAbstractListModel):
    """Model backed by os.scandir. Supports sort, filter, and per-item roles."""

    # Keep the single worker responsive to the current viewport when a
    # thumbnail/detail prefetch touches many directories at once.  The active
    # task is not part of this budget and is always allowed to finish.
    _DIR_SIZE_QUEUE_LIMIT = 64

    dir_size_ready = Signal(str, str, int)  # (dir_path, formatted_size, generation)
    rename_requested = Signal(int, str)
    scan_started = Signal(int)  # scan generation; emitted before loading state
    scan_committed = Signal(int)  # populated scan generation; excludes the loading reset
    state_changed = Signal(str, int, object)  # (state, generation, OSError | None)

    STATE_LOADING = "loading"
    STATE_READY = "ready"
    STATE_EMPTY_FOLDER = "empty_folder"
    STATE_EMPTY_FILTERED = "empty_filtered"
    STATE_SCAN_ERROR = "scan_error"

    def __init__(self, parent=None, exclude_patterns: list[str] | None = None):
        super().__init__(parent)
        self._entries: list[os.DirEntry] = []
        self._raw_entries: list[os.DirEntry] = []
        self._exclude_patterns: list[str] = list(exclude_patterns or [])
        self._dir_path: str = ""
        self._sort_key: str = "name"
        self._sort_asc: bool = True
        self._filter_text: str = ""
        self._filter_cat: str = "all"
        self._show_hidden: bool = False
        self._icons: dict[str, QIcon] = {}  # path → icon
        self._raw_pixmaps = LRUCache(800)   # path → pixmap
        self._dir_size_cache: dict[str, str] = {}
        self._subtitle_cache: dict[str, str] = {}
        self._stat_cache: dict[str, os.stat_result] = {}
        self._failed_thumbs: set[str] = set()  # paths that failed to load thumbnails
        self._lib_root: str = ""
        self._metadata_service = None
        self._session: LibrarySession | None = None
        self._size_pool: QThreadPool | None = None
        self._pending_dir_sizes: set[str] = set()
        self._dir_size_queue: deque[str] = deque()
        self._dir_size_active: str | None = None
        self._dir_size_active_generation: int | None = None
        self._dir_size_gen = 0
        self._scan_gen = 0
        self._preserve_scan_generation: int | None = None
        self._preserve_scan_view_state: tuple | None = None
        self._last_scan_reused = False
        self._committing_scan_gen: int | None = None
        self._active_scan_task: _ScanTask | None = None  # prevent GC of running task + signals
        self._active_size_task: QRunnable | None = None  # held until its done signal delivers
        self._scan_error: OSError | None = None
        self._scan_loading = False
        self._path_index: dict[str, int] = {}
        self._is_shutdown = False
        self._performance_recorder = None
        self._performance_session_token: str | None = None
        self.dir_size_ready.connect(self._on_dir_size_ready)

    SUBTITLE_ROLE = Qt.ItemDataRole.UserRole + 1
    RAW_PIXMAP_ROLE = Qt.ItemDataRole.UserRole + 2
    IS_DIR_ROLE = Qt.ItemDataRole.UserRole + 3
    DIR_SIZE_ROLE = Qt.ItemDataRole.UserRole + 4

    @property
    def scan_generation(self) -> int:
        """Current presentation generation for stale-scan-safe consumers."""
        return self._scan_gen

    @property
    def is_committing_scan(self) -> bool:
        """Whether the current model reset applies an asynchronous scan result."""
        return self._committing_scan_gen == self._scan_gen

    @property
    def list_state(self) -> str:
        if self._scan_loading:
            return self.STATE_LOADING
        if self._scan_error is not None:
            return self.STATE_SCAN_ERROR
        if not self._raw_entries:
            return self.STATE_EMPTY_FOLDER
        if not self._entries:
            return self.STATE_EMPTY_FILTERED
        return self.STATE_READY

    def _emit_state(self) -> None:
        self.state_changed.emit(self.list_state, self._scan_gen, self._scan_error)

    def set_library_root(self, path: str, session: LibrarySession | None = None):
        self._lib_root = str(Path(path).resolve())
        self._session = session

    def set_metadata_service(self, metadata_service):
        self._metadata_service = metadata_service

    def set_performance_context(self, recorder, session_token: str | None) -> None:
        """Bind optional scoped diagnostics without changing model behavior."""
        try:
            enabled = bool(getattr(recorder, "enabled", False)) and callable(
                getattr(recorder, "record", None)
            )
        except Exception:
            enabled = False
        self._performance_recorder = recorder if enabled else None
        self._performance_session_token = session_token if enabled else None

    @contextmanager
    def _reset_model(self, reason: str):
        recorder = self._performance_recorder
        started = perf_counter() if recorder is not None else None
        previous_row_count = len(self._entries)
        self.beginResetModel()
        try:
            yield
        finally:
            self.endResetModel()
            if recorder is not None and started is not None:
                try:
                    recorder.record(
                        "model.reset",
                        (perf_counter() - started) * 1000,
                        session_token=self._performance_session_token,
                        generation=self._scan_gen,
                        attributes={
                            "reason": reason,
                            "previous_row_count": previous_row_count,
                            "row_count": len(self._entries),
                            "scan_loading": self._scan_loading,
                        },
                    )
                except Exception:
                    # Diagnostics must never change model reset behavior.
                    pass

    def _invalidate_dir_size_work(self) -> None:
        active = self._dir_size_active
        self._dir_size_queue.clear()
        self._pending_dir_sizes.clear()
        if active is not None:
            self._pending_dir_sizes.add(active)
        self._dir_size_gen += 1

    def set_directory(self, path: str, *, preserve_existing: bool = False):
        preserve_existing = bool(preserve_existing and self._dir_path and self._dir_path == path)
        self._dir_path = path
        self._scan_gen += 1
        gen = self._scan_gen
        self._preserve_scan_generation = gen if preserve_existing else None
        self._preserve_scan_view_state = (
            self._sort_key,
            self._sort_asc,
            self._filter_text,
            self._filter_cat,
            self._show_hidden,
        ) if preserve_existing else None
        self._last_scan_reused = False
        self._scan_loading = True
        self._scan_error = None
        self.scan_started.emit(gen)
        self._active_scan_task = None  # release previous task
        if not preserve_existing:
            self._icons.clear()
            self._raw_pixmaps.clear()
            self._dir_size_cache.clear()
            self._subtitle_cache.clear()
            self._stat_cache.clear()
            self._invalidate_dir_size_work()
            with self._reset_model("directory_loading"):
                self._raw_entries = []
                self._entries = []
                self._path_index = {}
        self._emit_state()

        task = _ScanTask(path, gen)
        self._active_scan_task = task  # keep strong reference until scan_done delivery
        model_ref = weakref.ref(self)

        def complete(entries: list, stats: dict, error: OSError | None) -> None:
            model = model_ref()
            if model is not None and Shiboken.isValid(model):
                model._on_scan_done(entries, stats, error, gen)

        task.signals.scan_done.connect(complete)
        QThreadPool.globalInstance().start(task)

    @staticmethod
    def _scan_signature(entries: list[os.DirEntry], stat_cache: dict[str, os.stat_result]):
        signature = {}
        for entry in entries:
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                is_dir = False
            stat = stat_cache.get(entry.path)
            if stat is None:
                try:
                    stat = entry.stat(follow_symlinks=False)
                except OSError:
                    stat = os.stat_result((0,) * 10)
            signature[entry.path] = (
                entry.path,
                is_dir,
                stat.st_size,
                getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)),
                getattr(stat, "st_ctime_ns", int(stat.st_ctime * 1_000_000_000)),
                getattr(stat, "st_ino", 0),
            )
        return signature

    def _on_scan_done(self, entries: list, stat_cache: dict, error: OSError | None, gen: int):
        if self._is_shutdown:
            return
        if gen != self._scan_gen:
            return
        self._active_scan_task = None  # release reference after processing
        self._scan_loading = False
        self._scan_error = error
        self._last_scan_reused = False
        preserve_scan = self._preserve_scan_generation == gen
        if preserve_scan and error is None:
            previous_signature = self._scan_signature(self._raw_entries, self._stat_cache)
            next_signature = self._scan_signature(entries, stat_cache)
            if previous_signature == next_signature:
                self._raw_entries = entries
                self._stat_cache = stat_cache
                current_view_state = (
                    self._sort_key, self._sort_asc, self._filter_text,
                    self._filter_cat, self._show_hidden,
                )
                if current_view_state != self._preserve_scan_view_state:
                    self._apply_sort()
                self._preserve_scan_generation = None
                self._preserve_scan_view_state = None
                self._last_scan_reused = True
                self.scan_committed.emit(gen)
                self._emit_state()
                return
        if preserve_scan:
            self._icons.clear()
            self._raw_pixmaps.clear()
            self._dir_size_cache.clear()
            self._subtitle_cache.clear()
            self._invalidate_dir_size_work()
        self._preserve_scan_generation = None
        self._committing_scan_gen = gen
        try:
            with self._reset_model("scan_commit"):
                self._raw_entries = entries
                self._stat_cache = stat_cache
                self._apply_sort()
        finally:
            self._committing_scan_gen = None
        self.scan_committed.emit(gen)
        self._emit_state()

    def _on_dir_size_ready(self, dir_path: str, _size: str, _gen: int):
        if _gen != self._dir_size_gen:
            if (
                self._dir_size_active == dir_path
                and self._dir_size_active_generation == _gen
            ):
                self._dir_size_active = None
                self._dir_size_active_generation = None
                if dir_path not in self._dir_size_queue:
                    self._pending_dir_sizes.discard(dir_path)
                self._dispatch_next_dir_size()
            return
        self._pending_dir_sizes.discard(dir_path)
        if self._dir_size_active == dir_path and self._dir_size_active_generation == _gen:
            self._dir_size_active = None
            self._dir_size_active_generation = None
            self._dispatch_next_dir_size()

    def _wait_for_scan(self):
        """Block until the background scan completes. For testing only."""
        QThreadPool.globalInstance().waitForDone()
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            app.processEvents()

    def refresh(self):
        if self._dir_path:
            self.set_directory(self._dir_path, preserve_existing=True)

    def set_sort(self, key: str, asc: bool = True):
        self._sort_key = self._normalize_sort_key(key)
        self._sort_asc = asc
        # Icons and pixmaps use path keys — survive sort changes
        if self._dir_path:
            with self._reset_model("sort"):
                self._apply_sort()
            self._emit_state()

    def set_filter(self, text: str = "", category: str = "All"):
        self._filter_text = text
        self._filter_cat = self._normalize_filter_category(category)
        self._subtitle_cache.clear()
        # Icons and pixmaps use path keys — survive filter changes
        if self._dir_path:
            with self._reset_model("filter"):
                self._apply_sort()
            self._emit_state()

    def rowCount(self, parent=QModelIndex()):
        return len(self._entries)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        entry = self._entries[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return entry.name
        if role == Qt.ItemDataRole.EditRole:
            return entry.name
        if role == Qt.ItemDataRole.UserRole:
            return entry.path
        if role == Qt.ItemDataRole.DecorationRole:
            return self._icons.get(entry.path)
        if role == Qt.ItemDataRole.ToolTipRole:
            st = self._cached_stat(entry)
            return f"{entry.path}\n{st.st_size:,} bytes\nModified: {QFileInfo(entry.path).lastModified().toString('yyyy-MM-dd HH:mm')}"
        if role == FileSystemModel.SUBTITLE_ROLE:
            return self._subtitle(entry)
        if role == FileSystemModel.RAW_PIXMAP_ROLE:
            return self._raw_pixmaps.get(entry.path)
        if role == FileSystemModel.IS_DIR_ROLE:
            return self._safe_is_dir(entry)
        if role == FileSystemModel.DIR_SIZE_ROLE:
            if self._safe_is_dir(entry):
                return self._dir_size_cache.get(entry.path) or None
            return None

    @staticmethod
    def _fmt_size(sz: float) -> str:
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if sz < 1024:
                return f"{sz:.1f} {unit}"
            sz /= 1024
        return f"{sz:.1f} PB"

    def _subtitle(self, entry: os.DirEntry) -> str:
        path = entry.path
        if path in self._subtitle_cache:
            result = self._subtitle_cache[path]
            # A queued prefetch may have been evicted to keep the queue bounded.
            # Retain the placeholder, but make the next visible read eligible
            # to enqueue the work again.
            if result == "..." and path not in self._pending_dir_sizes:
                self._start_async_dir_size(path)
            return result
        try:
            if entry.is_dir():
                # Return placeholder immediately, compute size in background
                self._subtitle_cache[path] = "..."
                self._start_async_dir_size(path)
                return "..."
            else:
                sz = self._cached_stat(entry).st_size
                result = self._fmt_size(sz)
        except OSError:
            result = ""
        self._subtitle_cache[path] = result
        return result

    def _start_async_dir_size(self, dir_path: str):
        """Queue one directory-size task without flooding the thread pool."""
        if self._is_shutdown:
            return
        if (
            self._dir_size_active is not None
            and self._dir_size_active not in self._pending_dir_sizes
            and self._dir_size_active_generation == self._dir_size_gen
        ):
            # A direct task runner used by tests can execute the QRunnable
            # without delivering its queued Qt signal first.
            self._dir_size_active = None
            self._dir_size_active_generation = None
        if dir_path in self._pending_dir_sizes:
            if (
                dir_path == self._dir_size_active
                and self._dir_size_active_generation != self._dir_size_gen
                and dir_path not in self._dir_size_queue
            ):
                self._dir_size_queue.append(dir_path)
            return
        if self._size_pool is None:
            self._size_pool = QThreadPool()
            self._size_pool.setMaxThreadCount(1)
        self._pending_dir_sizes.add(dir_path)
        self._dir_size_queue.append(dir_path)
        self._trim_dir_size_queue()
        self._dispatch_next_dir_size()

    def prioritize_dir_sizes(self, paths) -> None:
        """Move currently visible directory paths ahead of queued work."""
        if not self._dir_size_queue:
            return
        queued = set(self._dir_size_queue)
        wanted = []
        seen = set()
        for path in paths:
            path = str(path)
            if path in seen or path not in queued:
                continue
            seen.add(path)
            wanted.append(path)
        if not wanted:
            self._trim_dir_size_queue()
            return
        self._dir_size_queue = deque(
            [*wanted, *(path for path in self._dir_size_queue if path not in seen)]
        )
        self._trim_dir_size_queue(seen)

    def _trim_dir_size_queue(self, keep_paths=()) -> None:
        """Bound queued work while retaining the active task and visible work."""
        if len(self._dir_size_queue) <= self._DIR_SIZE_QUEUE_LIMIT:
            return
        keep = set(keep_paths)
        retained = deque()
        evicted = []
        for path in self._dir_size_queue:
            if path in keep or len(retained) < self._DIR_SIZE_QUEUE_LIMIT:
                retained.append(path)
            else:
                evicted.append(path)
        self._dir_size_queue = retained
        for path in evicted:
            self._pending_dir_sizes.discard(path)

    def _dispatch_next_dir_size(self) -> None:
        if self._is_shutdown or self._dir_size_active is not None:
            return
        while self._dir_size_queue:
            dir_path = self._dir_size_queue.popleft()
            if dir_path not in self._pending_dir_sizes:
                continue
            self._dir_size_active = dir_path
            self._dir_size_active_generation = self._dir_size_gen
            self._submit_dir_size_task(dir_path)
            return

    def _submit_dir_size_task(self, dir_path: str) -> None:
        gen = self._dir_size_gen
        # All mutable scoped dependencies are captured before the task is queued.
        lib_root = self._lib_root
        session = self._session
        # Unscoped browsing has no session lease, so never touch DB-backed cache.
        metadata_service = self._metadata_service if session is not None else None
        model = self

        def abort_task() -> None:
            if model._dir_size_active == dir_path and model._dir_size_active_generation == gen:
                model._dir_size_active = None
                model._dir_size_active_generation = None
                model._pending_dir_sizes.discard(dir_path)

        class _SizeTaskDone(QObject):
            # Carries the wrapper itself so the delivery keeps the runnable
            # (and its captured session closure) alive until it is released.
            done = Signal(object)

        class _SizeTask(QRunnable):
            def __init__(s, done):
                super().__init__()
                s._done = done

            def run(s):
                try:
                    if session is None:
                        if model._is_shutdown:
                            abort_task()
                            return
                        total = FileSystemModel._cached_dir_size(dir_path, lib_root, metadata_service)
                    else:
                        # A queued task refuses after close; a running task keeps its
                        # original session alive through cache read, scan, and write.
                        try:
                            with session.operation():
                                total = FileSystemModel._cached_dir_size(dir_path, lib_root, metadata_service)
                        except RuntimeError:
                            # A caller that closes before a queued task starts must not
                            # leak an exception from the Qt worker thread.
                            abort_task()
                            return
                    if model._is_shutdown:
                        abort_task()
                        return
                    result = FileSystemModel._fmt_size(total) if total > 0 else "Empty"
                    model.dir_size_ready.emit(dir_path, result, gen)
                finally:
                    # Emitted on every exit path so the model can drop its
                    # reference once the pool has finished (auto-delete).
                    s._done.done.emit(s)

        done = _SizeTaskDone()
        task = _SizeTask(done)
        done.done.connect(self._on_size_task_done)
        self._active_size_task = task  # keep the wrapper alive while the pool runs it
        try:
            cast(QThreadPool, self._size_pool).start(task)
        except Exception:
            self._active_size_task = None
            self._dir_size_active = None
            self._dir_size_active_generation = None
            self._pending_dir_sizes.discard(dir_path)
            self._dispatch_next_dir_size()

    def _on_size_task_done(self, task) -> None:
        """Release the finished size task's Python wrapper after delivery."""
        if self._active_size_task is task:
            self._active_size_task = None

    @staticmethod
    def _cached_dir_size(dir_path: str, lib_root: str, metadata_svc=None) -> int:
        MAX_BYTES = 10_737_418_240  # 10 GB
        if lib_root:
            try:
                if metadata_svc is not None:
                    size, _ = metadata_svc.get_dir_size(lib_root, dir_path, force=False)
                    if size > 0:
                        return size
            except Exception:
                pass
        byte_total = 0
        try:
            for root, _dirs, files in os.walk(dir_path):
                for f in files:
                    try:
                        byte_total += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
                    if byte_total >= MAX_BYTES:
                        break
                if byte_total >= MAX_BYTES:
                    break
        except OSError:
            pass
        if lib_root and byte_total > 0:
            try:
                if metadata_svc is not None:
                    metadata_svc.set_dir_size(lib_root, dir_path, byte_total)
            except Exception:
                pass
        return byte_total

    @staticmethod
    def _safe_stat(entry) -> os.stat_result:
        try:
            return entry.stat()
        except OSError:
            return os.stat_result((0,) * 10)

    @staticmethod
    def _safe_is_dir(entry) -> bool:
        """is_dir() raises OSError for broken symlinks / permission-denied entries."""
        try:
            return entry.is_dir()
        except OSError:
            return False

    def _cached_stat(self, entry):
        """Return stat result from cache, or call stat() and cache it."""
        path = entry.path
        if path in self._stat_cache:
            return self._stat_cache[path]
        result = self._safe_stat(entry)
        self._stat_cache[path] = result
        return result

    def setData(self, index, value, role=Qt.ItemDataRole.DecorationRole):
        if role == Qt.ItemDataRole.DecorationRole and index.isValid():
            entry = self._entries[index.row()]
            self._icons[entry.path] = QIcon(value)
            return True
        if role == Qt.ItemDataRole.EditRole and index.isValid():
            entry = self._entries[index.row()]
            new_name = str(value).strip()
            if new_name and new_name != entry.name:
                self.rename_requested.emit(index.row(), new_name)
                return True
            return False
        return False

    def entry_at(self, row: int) -> os.DirEntry | None:
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def path_at(self, row: int) -> str | None:
        e = self.entry_at(row)
        return e.path if e else None

    def shutdown(self):
        """Wait for background directory-size tasks before stores are closed."""
        self._is_shutdown = True
        self._scan_gen += 1
        if self._active_scan_task is not None:
            task = self._active_scan_task
            if Shiboken.isValid(task):
                task.signals.scan_done.disconnect()
            self._active_scan_task = None
        if self._size_pool is not None:
            self._size_pool.waitForDone()
            self._size_pool = None
        self._active_size_task = None
        self._dir_size_active = None
        self._dir_size_active_generation = None
        self._dir_size_queue.clear()
        self._pending_dir_sizes.clear()

    def prepare_library_switch(self):
        """Drain session-bound directory-size work before its session closes."""
        self._dir_size_gen += 1
        if self._size_pool is not None:
            self._size_pool.waitForDone()
        self._active_size_task = None
        self._dir_size_active = None
        self._dir_size_active_generation = None
        self._dir_size_queue.clear()
        self._pending_dir_sizes.clear()

    def clear_scoped_services(self) -> None:
        """Release closed-library references after all background work has drained."""
        self._session = None
        self._metadata_service = None
        self._lib_root = ""

    def filter_accepts(self, entry: os.DirEntry) -> bool:
        if self._exclude_patterns and matches_exclude(entry.name, self._exclude_patterns):
            return False
        if not matches_search(entry.name, self._filter_text):
            return False
        cat = normalize_filter_category(self._filter_cat)
        if cat != "all" and not self._safe_is_dir(entry):
            ext = Path(entry.name).suffix.lower()
            if not extension_matches_category(ext, self._filter_cat):
                return False
        return True

    @staticmethod
    def _normalize_sort_key(key: str) -> str:
        return normalize_sort_key(key)

    @staticmethod
    def _normalize_filter_category(category: str) -> str:
        return normalize_filter_category(category)

    def _apply_sort(self):
        entries = [e for e in self._raw_entries if self.filter_accepts(e)]
        if not self._show_hidden:
            entries = [e for e in entries if not is_hidden(e.name)]
        k = normalize_sort_key(self._sort_key)

        def _sort_key(e):
            # Shared with the LAN AssetService (application/asset_filters.py)
            # so both surfaces sort identically: directories first, then the
            # chosen key, then natural name; desc reverses the whole list.
            stat = self._cached_stat(e)
            return sort_key_for_entry(
                name=e.name,
                is_dir=self._safe_is_dir(e),
                modified=stat.st_mtime,
                size=stat.st_size,
                ext=os.path.splitext(e.name)[1].lower(),
                sort_by=k,
            )

        entries.sort(key=_sort_key)
        if not self._sort_asc:
            entries.reverse()
        self._entries = entries
        self._path_index = {e.path: i for i, e in enumerate(entries)}


