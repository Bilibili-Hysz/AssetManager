"""DetailModel — virtual QAbstractItemModel for Details view.

Only creates data on demand via data() — no QTreeWidgetItem objects.
Enables efficient display of large directories (10000+ files).
"""
import logging
import os
import re
import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QAbstractItemModel, QFileInfo, QModelIndex, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFileIconProvider

from AssetsManager.panels.file_list._model import FileSystemModel
from AssetsManager import i18n
tr = i18n.tr

_log = logging.getLogger(__name__)

_natural_split = re.compile(r'(\d+)')

def _natural_key(s: str):
    """Natural sort: 'file2' < 'file10'."""
    return [(int(x) if x.isdigit() else x.lower()) for x in _natural_split.split(s)]


class DetailModel(QAbstractItemModel):
    """Virtual model that reads from FileSystemModel entries."""

    rename_requested = Signal(int, str)

    HEADER_KEYS = ("detail.name", "detail.type", "detail.size", "detail.date", "detail.tags")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fs_model: FileSystemModel | None = None
        self._entries: list = []
        self._store = None
        self._lib_root: str | None = None
        self._sort_column: int = 0
        self._sort_order: Qt.SortOrder = Qt.SortOrder.AscendingOrder
        self._tags_cache: dict[str, str] = {}
        self._icon_provider = QFileIconProvider()

    def set_source(self, fs_model: FileSystemModel, store=None, lib_root: str | None = None):
        """Set the source FileSystemModel and optional tag store."""
        self.beginResetModel()
        self._fs_model = fs_model
        self._entries = list(fs_model._entries) if fs_model else []
        self._store = store
        self._lib_root = lib_root
        self._rebuild_tags_cache()
        if self._entries and self._sort_column >= 0:
            self._do_sort(self._sort_column, self._sort_order)
        self.endResetModel()

    def refresh(self):
        """Re-read entries from source model."""
        if self._fs_model:
            self.beginResetModel()
            self._entries = list(self._fs_model._entries)
            self._rebuild_tags_cache()
            if self._entries and self._sort_column >= 0:
                self._do_sort(self._sort_column, self._sort_order)
            self.endResetModel()

    def _rebuild_tags_cache(self):
        """Batch-fetch tags for all entries to avoid per-item SQLite queries."""
        # A1: the whole body is guarded so no exception can escape between
        # beginResetModel()/endResetModel() — an uncaught raise there would
        # leave the view permanently mid-reset.
        try:
            self._tags_cache.clear()
            if not self._store or not self._entries:
                return
            file_entries = [entry for entry in self._entries if not entry.is_dir()]
            try:
                tags_by_path = self._store.get_tags_for_files([entry.path for entry in file_entries])
                for entry in file_entries:
                    # A3: the store (TagStore._resolve) normalizes keys with
                    # Path.resolve(), so the lookup key must match exactly —
                    # os.path.abspath() would silently miss symlinked paths.
                    # Per-file resolve() is a syscall on the main thread and
                    # is the dominant cost for 10k+ file refreshes; kept for
                    # key consistency with the store.
                    tags = tags_by_path.get(str(Path(entry.path).resolve()), [])[:3]
                    if tags:
                        self._tags_cache[entry.path] = ", ".join(tags)
                return
            except AttributeError:
                # Store without the batch API — fall back to per-entry calls.
                pass
            for entry in self._entries:
                if not entry.is_dir():
                    try:
                        tags = self._store.get_tags(entry.path)[:3]
                        if tags:
                            self._tags_cache[entry.path] = ", ".join(tags)
                    except Exception as exc:
                        # A4: don't swallow silently — record the failed tag
                        # lookup (with the entry path) so a broken store is
                        # diagnosable without spamming logs.
                        _log.debug("tag fetch failed for %s: %s", entry.path, exc)
        except Exception:
            _log.exception("Failed to rebuild tags cache")

    # ── QAbstractItemModel interface ────────────────────────────

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0  # Flat list, no children
        return len(self._entries)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADER_KEYS)

    def index(self, row, column, parent=QModelIndex()):
        if parent.isValid() or row < 0 or row >= len(self._entries) or column < 0 or column >= len(self.HEADER_KEYS):
            return QModelIndex()
        return self.createIndex(row, column)

    def parent(self, index):
        return QModelIndex()  # Flat list

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == 0:
            base |= Qt.ItemFlag.ItemIsEditable
        return base

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not self._fs_model:
            return None
        row = index.row()
        col = index.column()
        if row < 0 or row >= len(self._entries):
            return None
        entry = self._entries[row]

        if role == Qt.ItemDataRole.DisplayRole:
            return self._display_data(entry, col)
        if role == Qt.ItemDataRole.DecorationRole and col == 0:
            return self._icon_for(entry)
        if role == Qt.ItemDataRole.EditRole and col == 0:
            return entry.name
        if role == Qt.ItemDataRole.UserRole:
            return entry.path
        if role == Qt.ItemDataRole.ToolTipRole:
            return entry.path
        return None

    def _icon_for(self, entry) -> QIcon:
        icon = self._fs_model._icons.get(entry.path) if self._fs_model else None
        if icon and not icon.isNull():
            return icon
        return self._icon_provider.icon(QFileInfo(entry.path))

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or role != Qt.ItemDataRole.EditRole or index.column() != 0:
            return False
        row = index.row()
        if row < 0 or row >= len(self._entries):
            return False
        entry = self._entries[row]
        new_name = str(value).strip()
        if not new_name or new_name == entry.name:
            return False
        # A5: the rename is async — rename_requested only hands off to the
        # controller (FileListPanel._rename_detail_row → _rename_path), which
        # reports OSError via feedback/MessageBox and re-reads the model
        # (_post_refresh → refresh()), reverting the display to the old name
        # on failure. Returning True here is required by Qt's editor protocol
        # (the view closes the editor); there is no rollback dataChanged from
        # the model itself.
        self.rename_requested.emit(row, new_name)
        return True

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if 0 <= section < len(self.HEADER_KEYS):
                return tr(self.HEADER_KEYS[section])
        return None

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder):
        """Sort entries by column — called by QTreeView on header click."""
        if not self._entries or column < 0 or column >= len(self.HEADER_KEYS):
            return
        self._sort_column = column
        self._sort_order = order
        # A2: remap persistent indexes across the layout change, otherwise
        # selection/highlight jumps to a different file after sorting.
        # _do_sort reorders self._entries in place (list.sort), so each entry
        # object is the same object before and after — id() stays stable.
        ordered_before = list(enumerate(self._entries))
        self.layoutAboutToBeChanged.emit()
        self._do_sort(column, order)
        old_to_new = {id(entry): i for i, entry in enumerate(self._entries)}
        old_indexes = [self.index(row, 0) for row, _entry in ordered_before]
        new_indexes = [self.index(old_to_new[id(entry)], 0) for _row, entry in ordered_before]
        self.changePersistentIndexList(old_indexes, new_indexes)
        self.layoutChanged.emit()

    def _do_sort(self, column: int, order: Qt.SortOrder):
        """Internal sort — callable inside beginResetModel/endResetModel block.

        Two-pass stable sort: the business key decides order within each
        group, then a second non-reversed pass pins directories to the top.
        ``reverse=not ascending`` on the business-key pass would otherwise
        sink directories to the bottom when sorting descending (the old
        ``(not is_dir, ...)`` prefix got inverted too); keeping the second
        pass unreversed guarantees dirs stay first in both orders.
        """
        ascending = order == Qt.SortOrder.AscendingOrder
        fs = self._fs_model

        def _sort_key(entry):
            is_dir = entry.is_dir()
            if column == 0:
                return _natural_key(entry.name)
            elif column == 1:
                # Same ext semantics as the shared sort_key_for_entry
                # (application/asset_filters.py): os.path.splitext.
                ext = os.path.splitext(entry.name)[1].lower() if not is_dir else ""
                return (ext, _natural_key(entry.name))
            elif column == 2:
                return self._size_sort_value(entry, is_dir, fs)
            elif column == 3:
                return self._date_sort_value(entry, fs)
            elif column == 4:
                tags = self._tags_cache.get(entry.path, "")
                return (tags.lower(), _natural_key(entry.name))
            return _natural_key(entry.name)

        self._entries.sort(key=_sort_key, reverse=not ascending)
        # Stable — only reorders the dir/file boundary; order inside each
        # group set by the first pass is preserved.
        self._entries.sort(key=lambda entry: 0 if entry.is_dir() else 1)

    @staticmethod
    def _size_sort_value(entry, is_dir: bool, fs) -> int:
        """Return raw byte size for sorting; avoids parsing display strings."""
        if is_dir:
            if not fs:
                return 0
            cached = fs._dir_size_cache.get(entry.path) or fs._subtitle_cache.get(entry.path)
            return DetailModel._parse_size_text(cached)
        try:
            return fs._cached_stat(entry).st_size if fs else 0
        except (OSError, AttributeError):
            return 0

    @staticmethod
    def _parse_size_text(text: str | None) -> int:
        if not text or text in ("...", "—", ""):
            return 0
        if text == "Empty":
            return 0
        parts = text.replace(",", "").split()
        if not parts:
            return 0
        units = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4, "PB": 1024 ** 5}
        try:
            value = float(parts[0])
        except ValueError:
            return 0
        unit = parts[1].upper() if len(parts) > 1 else "B"
        return int(value * units.get(unit, 1))

    @staticmethod
    def _date_sort_value(entry, fs) -> float:
        """Return mtime for sorting."""
        try:
            st = fs._cached_stat(entry) if fs else None
            return st.st_mtime if st and st.st_mtime > 0 else 0.0
        except (OSError, AttributeError):
            return 0.0

    def _display_data(self, entry, col: int) -> str:
        fs_model = self._fs_model
        if fs_model is None or fs_model._is_shutdown:
            return ""
        if col == 0:
            return entry.name
        if col == 1:
            if entry.is_dir():
                return tr("filelist.prop_folder")
            return Path(entry.name).suffix.upper() or tr("filelist.prop_file")
        if col == 2:
            if entry.is_dir():
                return self._dir_size_display(entry)
            try:
                return FileSystemModel._fmt_size(fs_model._cached_stat(entry).st_size)
            except (OSError, AttributeError):
                return "—"
        if col == 3:
            try:
                st = fs_model._cached_stat(entry)
                if st.st_mtime > 0:
                    return datetime.datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d')
            except (OSError, AttributeError, ValueError, OverflowError):
                pass
            return "—"
        if col == 4:
            return self._tags_cache.get(entry.path, "")
        return ""

    def _dir_size_display(self, entry) -> str:
        fs_model = self._fs_model
        if fs_model is None or fs_model._is_shutdown:
            return "..."
        for cache in (fs_model._subtitle_cache, fs_model._dir_size_cache):
            sz = cache.get(entry.path)
            if sz and sz not in ("...", ""):
                return sz
        row = fs_model._path_index.get(entry.path, -1)
        if row >= 0:
            idx = fs_model.index(row, 0)
            dsz = fs_model.data(idx, Qt.ItemDataRole(FileSystemModel.DIR_SIZE_ROLE))
            if isinstance(dsz, str) and dsz not in ("...", ""):
                return dsz
            subtitle = fs_model.data(idx, Qt.ItemDataRole(FileSystemModel.SUBTITLE_ROLE))
            return subtitle if isinstance(subtitle, str) and subtitle else "..."
        return "..."
