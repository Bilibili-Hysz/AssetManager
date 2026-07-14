"""Tag editor dialog — manage tags for the current file with suggestions."""
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLineEdit, QGroupBox, QListWidget, QListWidgetItem,
    QMessageBox, QWidget, QProgressBar,
)
from AssetsManager.core.protocols import TagStoreProtocol
from AssetsManager.core.tag_library import get_library
from AssetsManager.core.ui_scale import scaled_px
from AssetsManager.widgets.tag_chip import create_tag_chip
from AssetsManager.dialogs.tabbed_dialog import TabbedDialog
from AssetsManager import i18n
tr = i18n.tr


class TagEditorDialog(TabbedDialog):
    def __init__(self, store: TagStoreProtocol, file_path: str, parent=None):
        self._store = store
        self._file_path = file_path
        self._modified = False
        file_name = Path(file_path).name if file_path else "Unknown"
        super().__init__(parent, title=tr("tageditor.title", name=file_name),
                         min_size=(scaled_px(420), scaled_px(400)))

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.setStyleSheet(self._dialog_qss())

        # ── Current Tags ─────────────────────────────────────

        current_grp = QGroupBox(tr("tageditor.current_tags"))
        current_layout = QVBoxLayout(current_grp)

        self._current_flow = QWidget()
        self._current_flow.setStyleSheet("background: transparent;")
        flow_layout = QHBoxLayout(self._current_flow)
        flow_layout.setContentsMargins(0, 0, 0, 0)
        flow_layout.setSpacing(scaled_px(4))
        self._current_flow_layout = flow_layout
        self._current_chips: list[QWidget] = []
        current_layout.addWidget(self._current_flow)

        add_row = QHBoxLayout()
        self._add_input = QLineEdit()
        self._add_input.setPlaceholderText(tr("tageditor.placeholder"))
        self._add_input.returnPressed.connect(self._add_current_tag)
        add_row.addWidget(self._add_input)
        add_btn = self.make_secondary_btn(tr("tageditor.add"), self._add_current_tag)
        add_btn.setToolTip(tr("tageditor.add_tooltip"))
        add_row.addWidget(add_btn)
        current_layout.addLayout(add_row)

        layout.addWidget(current_grp)

        # ── Suggestions (all tags in library) ─────────────────

        sug_grp = QGroupBox(tr("tageditor.all_tags"))
        sug_layout = QVBoxLayout(sug_grp)

        self._sug_filter = QLineEdit()
        self._sug_filter.setPlaceholderText(tr("tageditor.filter"))
        self._sug_filter.setClearButtonEnabled(True)
        self._sug_filter.setToolTip(tr("tageditor.filter_tooltip"))
        self._sug_filter.textChanged.connect(self._refresh_suggestions)
        sug_layout.addWidget(self._sug_filter)

        self._sug_list = QListWidget()
        self._sug_list.setMaximumHeight(scaled_px(160))
        self._sug_list.itemDoubleClicked.connect(self._add_suggested_tag)
        sug_layout.addWidget(self._sug_list)

        layout.addWidget(sug_grp)

        # ── Danger zone ───────────────────────────────────────

        danger = QGroupBox(tr("tageditor.maintenance"))
        danger_layout = QHBoxLayout(danger)
        self._del_unused_btn = self.make_secondary_btn(tr("tageditor.delete_unused"), self._delete_unused)
        self._del_unused_btn.setToolTip(tr("tageditor.delete_unused_tooltip"))
        danger_layout.addWidget(self._del_unused_btn)
        danger_layout.addStretch()
        self._del_progress = QProgressBar()
        self._del_progress.setVisible(False)
        self._del_progress.setTextVisible(False)
        self._del_progress.setFixedHeight(scaled_px(4))
        danger_layout.addWidget(self._del_progress)
        layout.addWidget(danger)

        # ── Bottom buttons ────────────────────────────────────

        bottom = QHBoxLayout()
        bottom.addStretch()
        close_btn = self.make_primary_btn(tr("tageditor.done"), self.accept)
        bottom.addWidget(close_btn)
        layout.addLayout(bottom)

        self._refresh_current()
        self._refresh_suggestions()

    def was_modified(self) -> bool:
        return self._modified

    # ── Current tags ────────────────────────────────────

    def _clear_current_chips(self):
        for w in self._current_chips:
            w.deleteLater()
        self._current_chips.clear()
        while self._current_flow_layout.count():
            item = self._current_flow_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

    def _refresh_current(self):
        self._clear_current_chips()
        tags = self._store.get_tags(self._file_path)
        for tag in tags:
            chip = create_tag_chip(tag, on_remove=self._remove_tag)
            self._current_flow_layout.addWidget(chip)
            self._current_chips.append(chip)
        self._current_flow_layout.addStretch()

    def _add_current_tag(self):
        tag = get_library().canonical(self._add_input.text())
        if not tag:
            return
        self._store.add_tag(self._file_path, tag)
        self._store.save()
        self._modified = True
        self._add_input.clear()
        self._refresh_current()
        self._refresh_suggestions()

    def _remove_tag(self, tag: str):
        self._store.remove_tag(self._file_path, tag)
        self._store.save()
        self._modified = True
        self._refresh_current()
        self._refresh_suggestions()

    # ── Suggestions ─────────────────────────────────────

    def _refresh_suggestions(self):
        self._sug_list.clear()
        filter_text = self._sug_filter.text().lower()
        all_tags = self._store.get_all_tags()
        current = set(self._store.get_tags(self._file_path))
        for tag in all_tags:
            if filter_text and filter_text not in tag.lower():
                continue
            if tag in current:
                continue
            files = self._store.get_files_by_tag(tag)
            count = len(files)
            item = QListWidgetItem(f"  {tag}  ({count})")
            item.setData(Qt.ItemDataRole.UserRole, tag)
            self._sug_list.addItem(item)

    def _add_suggested_tag(self, item: QListWidgetItem | None = None):
        if item is None:
            item = self._sug_list.currentItem()
        if not item:
            return
        tag = item.data(Qt.ItemDataRole.UserRole)
        self._store.add_tag(self._file_path, tag)
        self._store.save()
        self._modified = True
        self._refresh_current()
        self._refresh_suggestions()

    # ── Maintenance ──────────────────────────────────────

    def _delete_unused(self):
        all_tags = self._store.get_all_tags()
        unused = [t for t in all_tags if len(self._store.get_files_by_tag(t)) == 0]
        if not unused:
            QMessageBox.information(self, tr("tageditor.no_unused"), tr("tageditor.no_unused"))
            return
        names = "\n".join(f"  • {t}" for t in unused[:20])
        if len(unused) > 20:
            names += f"\n  ... {tr('tageditor.and_more', count=len(unused) - 20)}"
        reply = QMessageBox.question(
            self, tr("tageditor.delete_unused"),
            tr("tageditor.delete_unused_msg", count=len(unused), names=names),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._del_unused_btn.setEnabled(False)
        self._del_progress.setRange(0, len(unused))
        self._del_progress.setValue(0)
        self._del_progress.setVisible(True)
        self._del_worker = _DeleteUnusedWorker(unused)
        self._del_worker.progress.connect(self._on_delete_progress)
        self._del_worker.finished.connect(self._on_delete_finished)
        self._del_worker.start()

    def _on_delete_progress(self, current: int):
        self._del_progress.setValue(current)

    def _on_delete_finished(self):
        self._del_progress.setVisible(False)
        self._del_unused_btn.setEnabled(True)
        self._store.save()
        self._modified = True
        self._refresh_suggestions()


class _DeleteUnusedWorker(QThread):
    """Background thread for deleting unused tags."""

    progress = Signal(int)

    def __init__(self, tags: list[str]):
        super().__init__()
        self._tags = tags

    def run(self):
        lib = get_library()
        for i, tag in enumerate(self._tags):
            lib.remove_canonical(tag)
            self.progress.emit(i + 1)
