

from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget

from AssetsManager import i18n
from AssetsManager.core.settings import AppSettings
from AssetsManager.core.signal_bus import get as bus
from AssetsManager.core.ui_scale import scaled_px
from AssetsManager.dialogs.tag_editor_dialog import TagEditorDialog


class _TagStore:
    def __init__(self):
        self.tags = {"asset.png": ["alpha"]}
        self.saved = 0

    def get_tags(self, path):
        return self.tags.get(path, [])

    def get_all_tags(self):
        return ["alpha", "beta"]

    def get_files_by_tag(self, tag):
        return ["asset.png"] if tag == "alpha" else []

    def add_tag(self, path, tag):
        self.tags.setdefault(path, []).append(tag)

    def remove_tag(self, path, tag):
        self.tags[path].remove(tag)

    def save(self):
        self.saved += 1


def test_clear_current_chips_ignores_layout_item_without_widget():
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    panel = type("_Panel", (), {})()
    panel._current_chips = []
    panel._current_flow_layout = QHBoxLayout(host)
    panel._current_flow_layout.addStretch()

    TagEditorDialog._clear_current_chips(panel)

    assert panel._current_flow_layout.count() == 0
    host.deleteLater()
    app.processEvents()


def test_tag_editor_language_refresh_keeps_draft_and_suggestion_selection():
    app = QApplication.instance() or QApplication([])
    dialog = TagEditorDialog(_TagStore(), "asset.png")
    original_language = i18n.current_language()
    try:
        dialog.show()
        app.processEvents()
        dialog._add_input.setText("draft")
        dialog._sug_filter.setText("beta")
        dialog._sug_list.setCurrentRow(0)
        selected = dialog._sug_list.currentItem()

        i18n.set_language("zh")
        app.processEvents()

        assert dialog._add_input.text() == "draft"
        assert dialog._sug_filter.text() == "beta"
        assert dialog._sug_list.currentItem() is selected
        assert dialog._add_btn.text() == i18n.tr("tageditor.add")
        assert dialog._maintenance_group.title() == i18n.tr("tageditor.maintenance")
    finally:
        i18n.set_language(original_language)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_tag_editor_scale_refresh_preserves_draft_and_updates_constraints():
    app = QApplication.instance() or QApplication([])
    dialog = TagEditorDialog(_TagStore(), "asset.png")
    settings = AppSettings.instance()
    original_scale = settings.get("ui_scale", 1.0)
    try:
        dialog.show()
        app.processEvents()
        dialog._add_input.setText("draft")
        initial_size = dialog.size()
        initial_chip = dialog._current_chips[0]

        settings.set("ui_scale", 1.5)
        bus().ui_scale_changed.emit(1.5)
        app.processEvents()

        assert dialog.size() == initial_size
        assert dialog._add_input.text() == "draft"
        assert dialog._root_layout.spacing() == scaled_px(10)
        assert dialog._sug_list.maximumHeight() == scaled_px(160)
        assert dialog._current_chips[0] is not initial_chip
    finally:
        settings.set("ui_scale", original_scale)
        bus().ui_scale_changed.emit(original_scale)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
