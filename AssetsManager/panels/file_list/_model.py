# ═══════════════════════════════════════════════════════════════════
# FileSystemModel
# ═══════════════════════════════════════════════════════════════════
import logging
import os
from pathlib import Path
import weakref
from PySide6.QtCore import Qt, QAbstractListModel, QModelIndex, QFileInfo, QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QIcon
from shiboken6 import Shiboken
from AssetsManager.application.asset_filters import (
    extension_matches_category,
    is_hidden,
    matches_search,
    natural_key as _natural_key,
    normalize_filter_category,
    normalize_sort_key,
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
        self.signals.scan_done.emit(entries, stat_cache, error)

class FileSystemModel(QAbstractListModel):
    """Model backed by os.scandir. Supports sort, filter, and per-item roles."""

    dir_size_ready = Signal(str, str, int)  # (dir_path, formatted_size, generation)
    rename_requested = Signal(int, str)
    scan_started = Signal(int)  # scan generation; emitted before the loading reset
    scan_committed = Signal(int)  # populated scan generation; excludes the loading reset
    state_changed = Signal(str, int, object)  # (state, generation, OSError | None)

    STATE_LOADING = "loading"
    STATE_READY = "ready"
    STATE_EMPTY_FOLDER = "empty_folder"
    STATE_EMPTY_FILTERED = "empty_filtered"
    STATE_SCAN_ERROR = "scan_error"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: list[os.DirEntry] = []
        self._raw_entries: list[os.DirEntry] = []
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
        self._dir_size_gen = 0
        self._scan_gen = 0
        self._committing_scan_gen: int | None = None
        self._active_scan_task: _ScanTask | None = None  # prevent GC of running task + signals
        self._scan_error: OSError | None = None
        self._scan_loading = False
        self._path_index: dict[str, int] = {}
        self._is_shutdown = False
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

    def set_directory(self, path: str):
        self._dir_path = path
        self._scan_gen += 1
        gen = self._scan_gen
        self._scan_loading = True
        self._scan_error = None
        self.scan_started.emit(gen)
        self._active_scan_task = None  # release previous task
        self._icons.clear()
        self._raw_pixmaps.clear()
        self._dir_size_cache.clear()
        self._subtitle_cache.clear()
        self._stat_cache.clear()
        self._pending_dir_sizes.clear()
        self._dir_size_gen += 1
        self.beginResetModel()
        self._raw_entries = []
        self._entries = []
        self._path_index = {}
        self.endResetModel()
        self._emit_state()

        task = _ScanTask(path, gen)
        task.setAutoDelete(False)  # prevent QThreadPool from deleting before signal fires
        self._active_scan_task = task  # keep strong reference
        model_ref = weakref.ref(self)

        def complete(entries: list, stats: dict, error: OSError | None) -> None:
            model = model_ref()
            if model is not None and Shiboken.isValid(model):
                model._on_scan_done(entries, stats, error, gen)

        task.signals.scan_done.connect(complete)
        QThreadPool.globalInstance().start(task)

    def _on_scan_done(self, entries: list, stat_cache: dict, error: OSError | None, gen: int):
        if self._is_shutdown:
            return
        if gen != self._scan_gen:
            return
        self._active_scan_task = None  # release reference after processing
        self._scan_loading = False
        self._scan_error = error
        self._committing_scan_gen = gen
        try:
            self.beginResetModel()
            self._raw_entries = entries
            self._stat_cache = stat_cache
            self._apply_sort()
            self.endResetModel()
        finally:
            self._committing_scan_gen = None
        self.scan_committed.emit(gen)
        self._emit_state()

    def _on_dir_size_ready(self, dir_path: str, _size: str, _gen: int):
        self._pending_dir_sizes.discard(dir_path)

    def _wait_for_scan(self):
        """Block until the background scan completes. For testing only."""
        QThreadPool.globalInstance().waitForDone()
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            app.processEvents()

    def refresh(self):
        if self._dir_path:
            self.set_directory(self._dir_path)

    def set_sort(self, key: str, asc: bool = True):
        self._sort_key = self._normalize_sort_key(key)
        self._sort_asc = asc
        # Icons and pixmaps use path keys — survive sort changes
        if self._dir_path:
            self.beginResetModel()
            self._apply_sort()
            self.endResetModel()
            self._emit_state()

    def set_filter(self, text: str = "", category: str = "All"):
        self._filter_text = text
        self._filter_cat = self._normalize_filter_category(category)
        self._subtitle_cache.clear()
        # Icons and pixmaps use path keys — survive filter changes
        if self._dir_path:
            self.beginResetModel()
            self._apply_sort()
            self.endResetModel()
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
            return entry.is_dir()
        if role == FileSystemModel.DIR_SIZE_ROLE:
            if entry.is_dir():
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
            return self._subtitle_cache[path]
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
        """Queue directory size computation on a background thread.
        Deduplicates by path and discards stale results after library switch."""
        if self._is_shutdown:
            return
        if dir_path in self._pending_dir_sizes:
            return
        if self._size_pool is None:
            self._size_pool = QThreadPool()
            self._size_pool.setMaxThreadCount(2)
        self._pending_dir_sizes.add(dir_path)
        gen = self._dir_size_gen
        # All mutable scoped dependencies are captured before the task is queued.
        lib_root = self._lib_root
        session = self._session
        # Unscoped browsing has no session lease, so never touch DB-backed cache.
        metadata_service = self._metadata_service if session is not None else None
        model = self

        class _SizeTask(QRunnable):
            def run(self):
                self.setAutoDelete(False)  # prevent destruction before signal delivery
                if session is None:
                    if model._is_shutdown:
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
                        return
                if model._is_shutdown:
                    return
                result = FileSystemModel._fmt_size(total) if total > 0 else "Empty"
                model.dir_size_ready.emit(dir_path, result, gen)

        self._size_pool.start(_SizeTask())

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
            self._active_scan_task.signals.scan_done.disconnect()
            self._active_scan_task = None
        if self._size_pool is not None:
            self._size_pool.waitForDone()
            self._size_pool = None
        self._pending_dir_sizes.clear()

    def prepare_library_switch(self):
        """Drain session-bound directory-size work before its session closes."""
        self._dir_size_gen += 1
        if self._size_pool is not None:
            self._size_pool.waitForDone()
        self._pending_dir_sizes.clear()

    def clear_scoped_services(self) -> None:
        """Release closed-library references after all background work has drained."""
        self._session = None
        self._metadata_service = None
        self._lib_root = ""

    def filter_accepts(self, entry: os.DirEntry) -> bool:
        if not matches_search(entry.name, self._filter_text):
            return False
        cat = normalize_filter_category(self._filter_cat)
        if cat != "all" and not entry.is_dir():
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
            return (
                not e.is_dir(),
                (_natural_key(e.name) if k == "name" else
                 -(self._cached_stat(e).st_mtime) if k == "date" else
                 -(self._cached_stat(e).st_size) if k == "size" else
                 Path(e.name).suffix.lower() if "." in e.name else ""),
                _natural_key(e.name),
            )

        entries.sort(key=_sort_key)
        if not self._sort_asc:
            entries.reverse()
        self._entries = entries
        self._path_index = {e.path: i for i, e in enumerate(entries)}


