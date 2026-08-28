

from PySide6.QtWidgets import QApplication

from AssetsManager.panels.file_list._batch_rename_dialog import BatchRenameDialog


def test_batch_rename_dialog_previews_and_blocks_invalid_plan(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    app = QApplication.instance() or QApplication([])
    dialog = BatchRenameDialog([str(tmp_path / "a.txt"), str(tmp_path / "b.txt")])
    try:
        assert dialog.plan is not None and dialog.plan.is_valid
        assert dialog._apply.isEnabled()
        assert dialog._table.item(0, 1).text() == "a_1.txt"
        assert dialog._table.item(1, 1).text() == "b_2.txt"

        dialog._pattern.setText("same")

        assert dialog.plan is not None and not dialog.plan.is_valid
        assert dialog._apply.isEnabled() is False
        assert "Duplicate" in dialog._table.item(0, 2).text()
    finally:
        dialog.close()
        app.processEvents()
