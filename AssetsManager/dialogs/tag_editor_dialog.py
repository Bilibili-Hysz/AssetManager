"""Tag editor dialog — manage tags for the current file with suggestions."""
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QThread, QSize
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLineEdit, QGroupBox, QListWidget, QListWidgetItem,
    QMessageBox, QWidget, QProgressBar,
)
from AssetsManager.core.protocols import TagStoreProtocol
from AssetsManager.core.tag_library import get_library
from AssetsManager.core.ui_scale import scaled_px
from AssetsManager.core import icons, themes
from AssetsManager.widgets.tag_chip import create_tag_chip, tag_color_from
from AssetsManager.dialogs.modal_dialog import StandardModalDialog
from AssetsManager import i18n
tr = i18n.tr


class TagEditorDialog(StandardModalDialog):
    supports_runtime_refresh = True

    def __init__(self, store: TagStoreProtocol, file_path: str, parent=None):
        self._store = store
        self._file_path = file_path
        self._modified = False
        self._del_worker = None  # set when the unused-tag worker starts
        self._file_name = Path(file_path).name if file_path else "Unknown"
        super().__init__(
            parent,
            title=tr("tageditor.title", name=self._file_name),
            min_size=(scaled_px(440), scaled_px(460)),
            ok_text=tr("tageditor.done"),
            show_cancel=False,
        )
        self._done_btn = self._ok_btn
        self._refresh_button_icons()
        self._refresh_current()
        self._refresh_suggestions()

    def closeEvent(self, event):
        # Never destroy a running worker thread ("QThread: Destroyed while
        # thread is still running" is fatal); give it a bounded grace period.
        worker = getattr(self, "_del_worker", None)
        if worker is not None and worker.isRunning():
            worker.wait(2000)
        super().closeEvent(event)

    def setup_content(self, layout: QVBoxLayout):
        self._root_layout.setContentsMargins(scaled_px(12), scaled_px(12), scaled_px(12), scaled_px(12))
        self._root_layout.setSpacing(scaled_px(10))

        # ── Current Tags ─────────────────────────────────────

        self._current_group = QGroupBox(tr("tageditor.current_tags"))
        current_grp = self._current_group
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
        self._add_input.setAccessibleName(tr("tageditor.placeholder"))
        self._add_input.returnPressed.connect(self._add_current_tag)
        add_row.addWidget(self._add_input)
        self._add_btn = self.make_secondary_btn(tr("tageditor.add"), self._add_current_tag)
        self._add_btn.setToolTip(tr("tageditor.add_tooltip"))
        add_row.addWidget(self._add_btn)
        current_layout.addLayout(add_row)

        layout.addWidget(current_grp)

        # ── Suggestions (all tags in library) ─────────────────

        self._suggestions_group = QGroupBox(tr("tageditor.all_tags"))
        sug_grp = self._suggestions_group
        sug_layout = QVBoxLayout(sug_grp)

        self._sug_filter = QLineEdit()
        self._sug_filter.setPlaceholderText(tr("tageditor.filter"))
        self._sug_filter.setAccessibleName(tr("tageditor.filter"))
        self._sug_filter.setClearButtonEnabled(True)
        self._sug_filter.setToolTip(tr("tageditor.filter_tooltip"))
        self._sug_filter.textChanged.connect(self._refresh_suggestions)
        sug_layout.addWidget(self._sug_filter)

        self._sug_list = QListWidget()
        self._sug_list.setAccessibleName(tr("tageditor.all_tags"))
        self._sug_list.setMaximumHeight(scaled_px(160))
        self._sug_list.itemDoubleClicked.connect(self._add_suggested_tag)
        sug_layout.addWidget(self._sug_list)

        layout.addWidget(sug_grp)

        # ── Danger zone ───────────────────────────────────────

        self._maintenance_group = QGroupBox(tr("tageditor.maintenance"))
        danger = self._maintenance_group
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

    def _refresh_button_icons(self):
        t = themes.get()
        buttons = (
            (self._add_btn, "tag", t["heading"], tr("tageditor.add")),
            (self._del_unused_btn, "trash", t["danger"], tr("tageditor.delete_unused")),
            (self._done_btn, "check", t["on_accent"], tr("tageditor.done")),
        )
        for button, icon_name, color, label in buttons:
            button.setIcon(icons.icon(icon_name, color=color, size=scaled_px(themes.metrics("icon_sm"))))
            button.setIconSize(QSize(scaled_px(themes.metrics("icon_sm")), scaled_px(themes.metrics("icon_sm"))))
            button.setAccessibleName(label)

    def _on_theme_changed(self, name):
        super()._on_theme_changed(name)
        self._refresh_button_icons()
        self._refresh_current()

    def retranslate_ui(self):
        file_name = Path(self._file_path).name if self._file_path else "Unknown"
        self.setWindowTitle(tr("tageditor.title", name=file_name))
        self._current_group.setTitle(tr("tageditor.current_tags"))
        self._add_input.setPlaceholderText(tr("tageditor.placeholder"))
        self._add_btn.setText(tr("tageditor.add"))
        self._add_btn.setToolTip(tr("tageditor.add_tooltip"))
        self._suggestions_group.setTitle(tr("tageditor.all_tags"))
        self._sug_filter.setPlaceholderText(tr("tageditor.filter"))
        self._sug_filter.setToolTip(tr("tageditor.filter_tooltip"))
        self._sug_filter.setAccessibleName(tr("tageditor.filter"))
        self._sug_list.setAccessibleName(tr("tageditor.all_tags"))
        self._maintenance_group.setTitle(tr("tageditor.maintenance"))
        self._del_unused_btn.setText(tr("tageditor.delete_unused"))
        self._del_unused_btn.setToolTip(tr("tageditor.delete_unused_tooltip"))
        self._done_btn.setText(tr("tageditor.done"))
        self._refresh_button_icons()

    def refresh_scaled_geometry(self, _scale: float | None = None):
        self._root_layout.setContentsMargins(scaled_px(12), scaled_px(12), scaled_px(12), scaled_px(12))
        self._root_layout.setSpacing(scaled_px(10))
        self._current_flow_layout.setSpacing(scaled_px(4))
        self._sug_list.setMaximumHeight(scaled_px(160))
        self._del_progress.setFixedHeight(scaled_px(4))
        self._refresh_button_icons()
        self._refresh_current()

    def was_modified(self) -> bool:
        return self._modified

    # ── Current tags ────────────────────────────────────

    def _clear_current_chips(self):
        for w in self._current_chips:
            w.deleteLater()
        self._current_chips.clear()
        while self._current_flow_layout.count():
            item = self._current_flow_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()

    def _refresh_current(self):
        self._clear_current_chips()
        tags = self._store.get_tags(self._file_path)
        for tag in tags:
            chip = create_tag_chip(
                tag, on_remove=self._remove_tag, color=tag_color_from(self._store, tag)
            )
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
        used_tags = set(self._store.get_all_tags())
        # Tags registered in the library that no file references are unused.
        # (file_tags only ever contains used tags, so querying the library
        # is what makes this feature reachable.)
        unused = [t for t in get_library().all_canonicals() if t not in used_tags]
        if not unused:
            QMessageBox.information(self, tr("tageditor.no_unused"), tr("tageditor.no_unused"))
            return
        names = "\n".join(f"  - {t}" for t in unused[:20])
        if len(unused) > 20:
            names += f"\n  ... {tr('tageditor.and_more', count=len(unused) - 20)}"
        reply = QMessageBox.question(
            self, tr("tageditor.delete_unused"),
            tr("tageditor.delete_unused_msg", count=len(unused), names=names),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
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
