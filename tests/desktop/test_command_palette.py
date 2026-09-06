"""Tests for the native Command Palette (Ctrl+K)."""
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QEvent, QRect, QSize, Qt
from PySide6.QtGui import QImage, QKeyEvent, QPainter
from PySide6.QtWidgets import QDialog, QStyle, QStyleOptionViewItem, QWidget

from AssetsManager.core.ui_scale import scaled_px
from AssetsManager.widgets.command_palette import (
    CommandPalette,
    CommandPaletteDelegate,
    PaletteCommand,
)


@pytest.fixture
def parent_widget():
    w = QWidget()
    w.resize(1000, 700)
    w.show()
    yield w
    w.close()
    w.deleteLater()


def test_command_palette_init_and_properties(parent_widget):
    palette = CommandPalette(parent_widget)
    try:
        assert bool(palette.windowFlags() & Qt.WindowType.FramelessWindowHint)
        assert palette.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        assert palette.isModal()
        assert palette._card.width() == scaled_px(560)
        assert palette._input.placeholderText() != ""
        assert palette._list.count() > 0
    finally:
        palette.close()
        palette.deleteLater()


def test_command_palette_loads_builtin_commands(parent_widget):
    palette = CommandPalette(parent_widget)
    try:
        command_ids = [cmd.id for cmd in palette._commands]
        assert "cmd_toggle_theme" in command_ids
        assert "cmd_settings" in command_ids
        assert "cmd_batch_rename" in command_ids
        assert "cmd_open_library_dir" in command_ids
        assert "cmd_refresh" in command_ids
        assert "cmd_shortcuts" in command_ids
        assert "cmd_exit" in command_ids
    finally:
        palette.close()
        palette.deleteLater()


def test_command_palette_filtering_modes(parent_widget):
    palette = CommandPalette(parent_widget)
    try:
        # Add custom mock commands for exact test isolation
        tag_cb = Mock()
        fav_cb = Mock()
        palette.register_command(PaletteCommand(
            id="tag_character",
            title="#character",
            category="tag",
            description="Character tag",
            icon_name="tag",
            callback=tag_cb,
            keywords=("character", "tag"),
        ))
        palette.register_command(PaletteCommand(
            id="fav_renders",
            title="@Renders",
            category="favorite",
            description="/path/to/renders",
            icon_name="star",
            callback=fav_cb,
            keywords=("renders", "folder"),
        ))

        # 1. ">" mode: commands only
        palette._input.setText(">")
        for r in range(palette._list.count()):
            item = palette._list.item(r)
            if not item.data(CommandPaletteDelegate.IsHeaderRole):
                assert item.data(CommandPaletteDelegate.CategoryRole) == "command"

        # 2. "#" mode: tags only
        palette._input.setText("#")
        tag_items = [
            palette._list.item(r).data(CommandPaletteDelegate.TitleRole)
            for r in range(palette._list.count())
            if not palette._list.item(r).data(CommandPaletteDelegate.IsHeaderRole)
        ]
        assert any("character" in title for title in tag_items)
        for r in range(palette._list.count()):
            item = palette._list.item(r)
            if not item.data(CommandPaletteDelegate.IsHeaderRole):
                assert item.data(CommandPaletteDelegate.CategoryRole) == "tag"

        # 3. "@" mode: favorites only
        palette._input.setText("@")
        fav_items = [
            palette._list.item(r).data(CommandPaletteDelegate.TitleRole)
            for r in range(palette._list.count())
            if not palette._list.item(r).data(CommandPaletteDelegate.IsHeaderRole)
        ]
        assert any("Renders" in title for title in fav_items)
        for r in range(palette._list.count()):
            item = palette._list.item(r)
            if not item.data(CommandPaletteDelegate.IsHeaderRole):
                assert item.data(CommandPaletteDelegate.CategoryRole) in ("favorite", "folder")

        # 4. Plain text search: matches keyword
        palette._input.setText("character")
        matched_items = [
            palette._list.item(r).data(CommandPaletteDelegate.TitleRole)
            for r in range(palette._list.count())
            if not palette._list.item(r).data(CommandPaletteDelegate.IsHeaderRole)
        ]
        assert any("character" in title for title in matched_items)

        # 5. Non-matching query: shows empty state
        palette._input.setText("nonexistent_xyz_query_12345")
        assert palette._list.count() == 1
        item = palette._list.item(0)
        assert bool(item.data(CommandPaletteDelegate.IsHeaderRole))
    finally:
        palette.close()
        palette.deleteLater()


def test_command_palette_keyboard_navigation_wrap(parent_widget):
    palette = CommandPalette(parent_widget)
    try:
        palette._input.setText(">")
        selectable = [r for r in range(palette._list.count()) if not palette._is_header_row(r)]
        assert len(selectable) >= 2

        # Starts at first selectable item
        assert palette._list.currentRow() == selectable[0]

        # Down moves to next selectable item
        down_event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
        palette.eventFilter(palette._input, down_event)
        assert palette._list.currentRow() == selectable[1]

        # Navigate backwards (Up) returns to first item
        up_event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier)
        palette.eventFilter(palette._input, up_event)
        assert palette._list.currentRow() == selectable[0]

        # Pressing Up at the very top wraps around to the last selectable item!
        palette.eventFilter(palette._input, up_event)
        assert palette._list.currentRow() == selectable[-1]

        # Pressing Down at the very bottom wraps around to the first selectable item!
        palette.eventFilter(palette._input, down_event)
        assert palette._list.currentRow() == selectable[0]
    finally:
        palette.close()
        palette.deleteLater()


def test_command_palette_enter_executes_selected_command(parent_widget):
    palette = CommandPalette(parent_widget)
    try:
        mock_cb = Mock()
        palette.register_command(PaletteCommand(
            id="test_cmd_action",
            title="Execute Me Now",
            category="command",
            description="Test execution",
            callback=mock_cb,
            keywords=("execute", "test"),
        ))
        palette._input.setText("Execute Me Now")

        assert palette._list.count() >= 1
        first_row = [r for r in range(palette._list.count()) if not palette._is_header_row(r)][0]
        palette._list.setCurrentRow(first_row)

        enter_event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
        palette.eventFilter(palette._input, enter_event)

        assert palette.result() == QDialog.DialogCode.Accepted
        mock_cb.assert_called_once()
    finally:
        palette.close()
        palette.deleteLater()


def test_command_palette_escape_closes_dialog(parent_widget):
    palette = CommandPalette(parent_widget)
    try:
        esc_event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        palette.eventFilter(palette._input, esc_event)

        assert palette.result() == QDialog.DialogCode.Rejected
    finally:
        palette.close()
        palette.deleteLater()


def test_command_palette_item_clicked_triggers_callback(parent_widget):
    palette = CommandPalette(parent_widget)
    try:
        mock_cb = Mock()
        palette.register_command(PaletteCommand(
            id="test_click_cmd",
            title="Click Target",
            category="command",
            callback=mock_cb,
            keywords=("click",),
        ))
        palette._input.setText("Click Target")
        first_row = [r for r in range(palette._list.count()) if not palette._is_header_row(r)][0]
        item = palette._list.item(first_row)

        palette._on_item_clicked(item)

        assert palette.result() == QDialog.DialogCode.Accepted
        mock_cb.assert_called_once()
    finally:
        palette.close()
        palette.deleteLater()


def test_command_palette_empty_list_navigation_safe(parent_widget):
    palette = CommandPalette(parent_widget)
    try:
        # Clear list entirely
        palette._list.clear()

        # Up, Down, Enter should not raise exceptions
        palette._navigate(1)
        palette._navigate(-1)
        palette._execute_current()
    finally:
        palette.close()
        palette.deleteLater()


def test_command_palette_delegate_rendering(parent_widget):
    palette = CommandPalette(parent_widget)
    try:
        delegate = palette._delegate
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, scaled_px(560), scaled_px(40))

        # Test sizeHint
        header_index = palette._list.model().index(0, 0)
        size = delegate.sizeHint(option, header_index)
        assert size.height() > 0

        # Test paint on QImage canvas
        img = QImage(QSize(scaled_px(560), scaled_px(40)), QImage.Format.Format_ARGB32_Premultiplied)
        painter = QPainter(img)
        try:
            # Header paint
            delegate.paint(painter, option, header_index)

            # Regular item paint with selection
            if palette._list.count() > 1:
                item_index = palette._list.model().index(1, 0)
                option.state |= QStyle.StateFlag.State_Selected
                delegate.paint(painter, option, item_index)
        finally:
            painter.end()
    finally:
        palette.close()
        palette.deleteLater()


def test_command_palette_actions_wire_parent_methods(parent_widget):
    parent_widget._open_settings = Mock()
    parent_widget._refresh_all = Mock()
    parent_widget._show_shortcuts = Mock()
    parent_widget._on_sidebar_navigate = Mock()

    palette = CommandPalette(parent_widget)
    try:
        palette._invoke_parent("_open_settings")
        parent_widget._open_settings.assert_called_once()

        palette._action_jump_folder("/test/path")
        parent_widget._on_sidebar_navigate.assert_called_once_with("/test/path")
    finally:
        palette.close()
        palette.deleteLater()


def test_main_window_command_palette_action_and_shortcut():
    """Verify MainWindow registers the command palette action and Ctrl+K shortcut."""
    from PySide6.QtGui import QAction, QKeySequence
    from AssetsManager.widgets.shortcut_manager import ShortcutManager
    from AssetsManager.window import MainWindow

    class _Window:
        _register_window_shortcuts = MainWindow._register_window_shortcuts

    window = _Window()
    window._menu_act_exit = QAction("Exit")
    window._menu_act_settings = QAction("Settings")
    window._menu_act_shortcuts = QAction("Keyboard Shortcuts")
    window._menu_act_command_palette = QAction("Command Palette")

    manager = ShortcutManager.instance()
    window._register_window_shortcuts()

    assert window._menu_act_command_palette.shortcut() == QKeySequence("Ctrl+K")
    shortcuts = manager.get_shortcuts()
    cmd_entry = next((s for s in shortcuts if s["key"] == "Ctrl+K"), None)
    assert cmd_entry is not None
    assert cmd_entry["description"] == "menu.command_palette"
    assert cmd_entry["category"] == "application"


def test_command_palette_rebuilds_builtins_and_keeps_external_on_language_change(parent_widget):
    """Stage E (V05/V10): a language switch regenerates the built-in command
    table (titles AND category descriptions retranslate via the bus-driven
    rebuild) while external register_command contributions survive it."""
    from AssetsManager import i18n
    from AssetsManager.core.signal_bus import get as bus

    palette = CommandPalette(parent_widget)
    external_cb = Mock()
    palette.register_command(PaletteCommand(
        id="ext_retranslate_probe",
        title="External Probe",
        category="command",
        description="External",
        callback=external_cb,
        keywords=("external", "probe"),
    ))
    saved_lang = i18n._current_lang
    # Target language always differs from the current one so the assertion
    # "title changed" is meaningful regardless of suite ordering.
    target = "ja" if saved_lang != "ja" else "zh"
    try:
        builtin_before = next(c for c in palette._commands if c.id == "cmd_toggle_theme")

        # Runtime language switch without persisting settings: flip the
        # module language, then emit the same bus signal the OverlayShell
        # refresh contract listens to (set_language would also broadcast,
        # but it writes settings.json — kept disk-clean here).
        i18n._current_lang = target
        bus().language_changed.emit(target)

        builtin_after = next(c for c in palette._commands if c.id == "cmd_toggle_theme")
        assert builtin_after is not builtin_before  # regenerated, not mutated
        assert builtin_after.title == i18n.tr("command_palette.cmd_theme")
        assert builtin_after.title != builtin_before.title
        assert builtin_after.description == i18n.tr("command_palette.desc_ui_theme")

        # External registration survived the rebuild (same object, dict-kept).
        assert palette._external_commands["ext_retranslate_probe"].callback is external_cb
        assert any(c.id == "ext_retranslate_probe" for c in palette._commands)

        # The rendered list still shows the external command in ">" mode.
        palette._input.setText(">probe")
        rendered = [
            palette._list.item(r).data(CommandPaletteDelegate.TitleRole)
            for r in range(palette._list.count())
            if not palette._list.item(r).data(CommandPaletteDelegate.IsHeaderRole)
        ]
        assert "External Probe" in rendered
    finally:
        i18n._current_lang = saved_lang
        palette.close()
        palette.deleteLater()


def test_command_palette_mode_hint_is_translated(parent_widget):
    """V10: the footer mode hint ("> 命令   # 标签   @ 收藏") was a hardcoded
    zh literal bypassing tr(); it must follow the catalog language."""
    from AssetsManager import i18n

    saved_lang = i18n._current_lang
    palette = CommandPalette(parent_widget)
    try:
        expected = (
            f"{i18n.tr('command_palette.hint_mode_cmd')}   "
            f"{i18n.tr('command_palette.hint_mode_tags')}   "
            f"{i18n.tr('command_palette.hint_mode_favs')}"
        )
        assert palette._hint_mode.text() == expected
    finally:
        i18n._current_lang = saved_lang
        palette.close()
        palette.deleteLater()

