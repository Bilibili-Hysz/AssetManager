"""Native Global Command Palette (Ctrl+K) — Raycast / Linear style desktop action launcher.

Provides full keyboard navigation, mode switching (> commands, # tags, @ favorites),
fuzzy search, and Design System 2.0 compliance with zero hardcoded hex colors or
unscaled pixels.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, cast

from PySide6.QtCore import QEvent, QModelIndex, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QKeyEvent,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from AssetsManager import i18n
from AssetsManager.core import icons, themes
from AssetsManager.core.color_utils import alpha
from AssetsManager.core.ui_scale import scaled_pt, scaled_px
from AssetsManager.widgets.elevation import apply_elevation

_log = logging.getLogger(__name__)
tr = i18n.tr


@dataclass
class PaletteCommand:
    """Descriptor for an action, tag, or folder entry in the palette."""

    id: str
    title: str
    category: str  # "command" | "tag" | "favorite" | "folder"
    description: str = ""
    shortcut: str = ""
    icon_name: str = "chevron_right"
    callback: Callable[[], Any] | None = None
    keywords: tuple[str, ...] = field(default_factory=tuple)


class CommandPaletteDelegate(QStyledItemDelegate):
    """Delegate for rendering Raycast/Linear style command palette rows."""

    TitleRole = Qt.ItemDataRole.UserRole + 1
    DescRole = Qt.ItemDataRole.UserRole + 2
    ShortcutRole = Qt.ItemDataRole.UserRole + 3
    IconNameRole = Qt.ItemDataRole.UserRole + 4
    CategoryRole = Qt.ItemDataRole.UserRole + 5
    CallbackRole = Qt.ItemDataRole.UserRole + 6
    IsHeaderRole = Qt.ItemDataRole.UserRole + 7

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        is_header = bool(index.data(self.IsHeaderRole))
        if is_header:
            return QSize(option.rect.width(), scaled_px(28))
        return QSize(option.rect.width(), scaled_px(40))

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        is_header = bool(index.data(self.IsHeaderRole))
        if is_header:
            title = str(index.data(self.TitleRole) or "")
            font = painter.font()
            font.setPointSize(scaled_pt(int(themes.font_size("caption", 10))))
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor(themes.color("muted")))
            header_rect = option.rect.adjusted(scaled_px(14), scaled_px(4), -scaled_px(14), 0)
            painter.drawText(
                header_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                title,
            )
            painter.restore()
            return

        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        is_hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        row_rect = QRectF(
            option.rect.adjusted(scaled_px(6), scaled_px(2), -scaled_px(6), -scaled_px(2))
        )
        radius = scaled_px(int(themes.prop("border_radius", "sm") or 6))

        # Background state
        if is_selected:
            bg_color = QColor(alpha(themes.color("accent"), 0.22))
            border_color = QColor(alpha(themes.color("accent"), 0.45))
            painter.setBrush(bg_color)
            painter.setPen(QPen(border_color, scaled_px(1)))
            painter.drawRoundedRect(row_rect, radius, radius)
        elif is_hovered:
            hover_opacity = float(themes.prop("opacity", "hover") or 0.12)
            bg_color = QColor(alpha(themes.color("hover_overlay"), hover_opacity))
            painter.setBrush(bg_color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(row_rect, radius, radius)

        # Left Icon (16px)
        icon_name = str(index.data(self.IconNameRole) or "chevron_right")
        tint = "accent" if is_selected else "icon_secondary"
        icon_size = scaled_px(16)
        icon_x = row_rect.left() + scaled_px(10)
        icon_y = row_rect.top() + (row_rect.height() - icon_size) / 2
        px = icons.icon(icon_name, color=tint, size=icon_size).pixmap(QSize(icon_size, icon_size))
        painter.drawPixmap(int(icon_x), int(icon_y), px)

        right_edge = row_rect.right() - scaled_px(10)

        # Right shortcut badge (if present)
        shortcut = str(index.data(self.ShortcutRole) or "")
        if shortcut:
            badge_font = painter.font()
            badge_font.setPointSize(scaled_pt(int(themes.font_size("xxs", 9))))
            badge_font.setBold(True)
            painter.setFont(badge_font)
            fm = painter.fontMetrics()
            text_w = fm.horizontalAdvance(shortcut)
            badge_w = text_w + scaled_px(12)
            badge_h = scaled_px(20)
            badge_rect = QRectF(
                right_edge - badge_w,
                row_rect.top() + (row_rect.height() - badge_h) / 2,
                badge_w,
                badge_h,
            )

            badge_bg = QColor(alpha(themes.color("panel"), 0.85))
            badge_border = QColor(themes.color("border_subtle"))
            painter.setBrush(badge_bg)
            painter.setPen(QPen(badge_border, scaled_px(1)))
            painter.drawRoundedRect(badge_rect, scaled_px(4), scaled_px(4))

            badge_text_color = (
                QColor(themes.color("heading")) if is_selected else QColor(themes.color("muted"))
            )
            painter.setPen(badge_text_color)
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, shortcut)
            right_edge = badge_rect.left() - scaled_px(8)

        # Secondary description
        desc = str(index.data(self.DescRole) or "")
        if desc:
            desc_font = painter.font()
            desc_font.setPointSize(scaled_pt(int(themes.font_size("caption", 10))))
            desc_font.setBold(False)
            painter.setFont(desc_font)
            fm = painter.fontMetrics()
            desc_w = min(scaled_px(160), fm.horizontalAdvance(desc) + scaled_px(4))
            desc_rect = QRectF(right_edge - desc_w, row_rect.top(), desc_w, row_rect.height())
            elided_desc = fm.elidedText(desc, Qt.TextElideMode.ElideRight, int(desc_w))
            painter.setPen(QColor(themes.color("muted")))
            painter.drawText(
                desc_rect,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                elided_desc,
            )
            right_edge = desc_rect.left() - scaled_px(10)

        # Operation name / title
        title = str(index.data(self.TitleRole) or "")
        title_font = painter.font()
        title_font.setPointSize(scaled_pt(int(themes.font_size("sm", 12))))
        title_font.setBold(is_selected)
        painter.setFont(title_font)
        fm = painter.fontMetrics()
        title_x = icon_x + icon_size + scaled_px(10)
        title_w = max(0.0, right_edge - title_x)
        title_rect = QRectF(title_x, row_rect.top(), title_w, row_rect.height())
        elided_title = fm.elidedText(title, Qt.TextElideMode.ElideRight, int(title_w))
        title_color = (
            QColor(themes.color("heading")) if is_selected else QColor(themes.color("body"))
        )
        painter.setPen(title_color)
        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            elided_title,
        )

        painter.restore()


class CommandPalette(QDialog):
    """Global Command Palette floating modal window."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)

        self._commands: list[PaletteCommand] = []
        self._current_mode = "all"
        self._delegate = CommandPaletteDelegate(self)

        self._build_ui()
        self._apply_theme_style()
        self._load_available_commands()
        self._filter_items("")

    def _build_ui(self) -> None:
        shadow_margin = scaled_px(16)
        card_w = scaled_px(560)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(
            shadow_margin, shadow_margin, shadow_margin, shadow_margin
        )
        root_layout.setSpacing(0)

        self._card = QFrame(self)
        self._card.setObjectName("paletteCard")
        self._card.setFixedWidth(card_w)

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        # ── Search Input Row ───────────────────────────────────
        search_row = QWidget(self._card)
        search_layout = QHBoxLayout(search_row)
        search_layout.setContentsMargins(
            scaled_px(16), scaled_px(10), scaled_px(16), scaled_px(10)
        )
        search_layout.setSpacing(scaled_px(10))

        search_icon = QLabel(search_row)
        search_icon.setPixmap(
            icons.icon("search", color="icon_primary", size=scaled_px(16)).pixmap(
                QSize(scaled_px(16), scaled_px(16))
            )
        )
        search_icon.setFixedSize(scaled_px(20), scaled_px(20))
        search_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        search_layout.addWidget(search_icon)

        self._input = QLineEdit(search_row)
        self._input.setPlaceholderText(
            tr(
                "command_palette.placeholder",
                default="输入命令或搜索... (支持 > 命令, # 标签, @ 收藏)",
            )
        )
        input_font = self._input.font()
        input_font.setPointSize(scaled_pt(int(themes.font_size("lg"))))
        self._input.setFont(input_font)
        self._input.setFrame(False)
        self._input.textChanged.connect(self._on_search_changed)
        self._input.installEventFilter(self)
        search_layout.addWidget(self._input, 1)

        card_layout.addWidget(search_row)

        # ── Subtle Divider ────────────────────────────────────
        self._divider = QFrame(self._card)
        self._divider.setObjectName("paletteDivider")
        card_layout.addWidget(self._divider)

        # ── Results List ──────────────────────────────────────
        self._list = QListWidget(self._card)
        self._list.setObjectName("paletteList")
        self._list.setFrameShape(QFrame.Shape.NoFrame)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setItemDelegate(self._delegate)
        self._list.setMinimumHeight(scaled_px(240))
        self._list.setMaximumHeight(scaled_px(380))
        self._list.itemClicked.connect(self._on_item_clicked)
        card_layout.addWidget(self._list, 1)

        # ── Footer / Hint Bar ─────────────────────────────────
        self._footer = QFrame(self._card)
        self._footer.setObjectName("paletteFooter")
        footer_layout = QHBoxLayout(self._footer)
        footer_layout.setContentsMargins(
            scaled_px(14), scaled_px(6), scaled_px(14), scaled_px(6)
        )
        footer_layout.setSpacing(scaled_px(12))

        footer_font = self.font()
        footer_font.setPointSize(scaled_pt(int(themes.font_size("xxs", 9))))

        self._hint_nav = QLabel(
            f"{tr('command_palette.hint_nav', default='↑↓ 导航')}    "
            f"{tr('command_palette.hint_exec', default='↵ 执行')}    "
            f"{tr('command_palette.hint_close', default='Esc 退出')}",
            self._footer,
        )
        self._hint_nav.setFont(footer_font)
        self._hint_nav.setObjectName("paletteHint")
        footer_layout.addWidget(self._hint_nav)

        footer_layout.addStretch(1)

        self._hint_mode = QLabel("> 命令   # 标签   @ 收藏", self._footer)
        self._hint_mode.setFont(footer_font)
        self._hint_mode.setObjectName("paletteHint")
        footer_layout.addWidget(self._hint_mode)

        card_layout.addWidget(self._footer)
        root_layout.addWidget(self._card)

        apply_elevation(self._card, level=3)

    def _apply_theme_style(self) -> None:
        card_bg = themes.color("panel") or themes.color("base")
        border_color = themes.color("border_subtle") or themes.color("border")
        br_md = scaled_px(int(themes.prop("border_radius", "md") or 10))
        input_text = themes.color("input_text") or themes.color("heading")
        muted_color = themes.color("muted") or themes.color("body")

        self._card.setStyleSheet(
            f"QFrame#paletteCard {{ "
            f"background: {card_bg}; "
            f"border: {scaled_px(1)}px solid {border_color}; "
            f"border-radius: {br_md}px; "
            f"}} "
            f"QFrame#paletteDivider {{ "
            f"background: {border_color}; "
            f"min-height: {scaled_px(1)}px; "
            f"max-height: {scaled_px(1)}px; "
            f"}} "
            f"QLineEdit {{ "
            f"background: transparent; "
            f"border: none; "
            f"color: {input_text}; "
            f"selection-background-color: {themes.color('accent')}; "
            f"}} "
            f"QListWidget {{ "
            f"background: transparent; "
            f"border: none; "
            f"outline: none; "
            f"}} "
            f"QFrame#paletteFooter {{ "
            f"border-top: {scaled_px(1)}px solid {border_color}; "
            f"background: transparent; "
            f"}} "
            f"QLabel#paletteHint {{ "
            f"color: {muted_color}; "
            f"}}"
        )

    def register_command(self, command: PaletteCommand) -> None:
        """Register an executable command into the palette."""
        self._commands.append(command)

    def _load_available_commands(self) -> None:
        """Gather system actions, library tags, and favorites from the environment."""
        # 1. Built-in System Commands
        self._commands.extend([
            PaletteCommand(
                id="cmd_toggle_theme",
                title=tr("command_palette.cmd_theme", default="切换主题/暗黑模式"),
                category="command",
                description="UI Theme",
                icon_name="eye",
                shortcut="",
                callback=self._action_toggle_theme,
                keywords=("theme", "dark", "light", "模式", "暗黑", "主题", "切换"),
            ),
            PaletteCommand(
                id="cmd_settings",
                title=tr("command_palette.cmd_settings", default="外观设置"),
                category="command",
                description="Preferences",
                icon_name="settings",
                shortcut="Ctrl+,",
                callback=lambda: self._invoke_parent("_open_settings"),
                keywords=("setting", "config", "偏好", "设置", "外观"),
            ),
            PaletteCommand(
                id="cmd_batch_rename",
                title=tr("command_palette.cmd_batch_rename", default="批量重命名"),
                category="command",
                description="Files",
                icon_name="file",
                shortcut="",
                callback=self._action_batch_rename,
                keywords=("rename", "batch", "重命名", "批量"),
            ),
            PaletteCommand(
                id="cmd_open_library_dir",
                title=tr("command_palette.cmd_open_library_dir", default="打开库目录"),
                category="command",
                description="Explorer",
                icon_name="folder_open",
                shortcut="",
                callback=self._action_open_library_dir,
                keywords=("folder", "directory", "explorer", "打开", "目录", "资源管理器"),
            ),
            PaletteCommand(
                id="cmd_refresh",
                title=tr("command_palette.cmd_refresh", default="刷新"),
                category="command",
                description="View",
                icon_name="refresh",
                shortcut="F5",
                callback=lambda: self._invoke_parent("_refresh_all"),
                keywords=("refresh", "reload", "刷新", "重载"),
            ),
            PaletteCommand(
                id="cmd_shortcuts",
                title=tr("command_palette.cmd_shortcuts", default="键盘快捷键"),
                category="command",
                description="Help",
                icon_name="wrench",
                shortcut="F1",
                callback=lambda: self._invoke_parent("_show_shortcuts"),
                keywords=("shortcut", "hotkey", "快捷键", "帮助"),
            ),
            PaletteCommand(
                id="cmd_open_library",
                title=tr("command_palette.cmd_open_library", default="打开资源库"),
                category="command",
                description="Library",
                icon_name="folder",
                shortcut="",
                callback=lambda: self._invoke_parent("_open_library"),
                keywords=("open", "library", "打开", "库"),
            ),
            PaletteCommand(
                id="cmd_backup",
                title=tr("command_palette.cmd_backup", default="备份资源库"),
                category="command",
                description="Maintenance",
                icon_name="save",
                shortcut="",
                callback=lambda: self._invoke_parent("_backup_library"),
                keywords=("backup", "备份"),
            ),
            PaletteCommand(
                id="cmd_restore",
                title=tr("command_palette.cmd_restore", default="还原资源库"),
                category="command",
                description="Maintenance",
                icon_name="download",
                shortcut="",
                callback=lambda: self._invoke_parent("_restore_library"),
                keywords=("restore", "还原", "恢复"),
            ),
            PaletteCommand(
                id="cmd_import",
                title=tr("command_palette.cmd_import", default="导入素材"),
                category="command",
                description="Assets",
                icon_name="upload",
                shortcut="",
                callback=lambda: self._invoke_parent("_import_assets"),
                keywords=("import", "导入", "采集"),
            ),
            PaletteCommand(
                id="cmd_plugins",
                title=tr("command_palette.cmd_plugins", default="插件管理器"),
                category="command",
                description="Extensions",
                icon_name="puzzle",
                shortcut="",
                callback=lambda: self._invoke_parent("_open_plugin_manager"),
                keywords=("plugin", "extension", "插件", "扩展"),
            ),
            PaletteCommand(
                id="cmd_undo_history",
                title=tr("command_palette.cmd_undo_history", default="撤销历史"),
                category="command",
                description="History",
                icon_name="clock",
                shortcut="",
                callback=lambda: self._invoke_parent("_open_undo_history"),
                keywords=("undo", "history", "撤销", "历史"),
            ),
            PaletteCommand(
                id="cmd_activity_log",
                title=tr("command_palette.cmd_activity_log", default="活动日志"),
                category="command",
                description="Logs",
                icon_name="list",
                shortcut="",
                callback=lambda: self._invoke_parent("_open_activity_log"),
                keywords=("activity", "log", "活动", "日志"),
            ),
            PaletteCommand(
                id="cmd_about",
                title=tr("command_palette.cmd_about", default="关于"),
                category="command",
                description="System",
                icon_name="info",
                shortcut="",
                callback=lambda: self._invoke_parent("_show_about"),
                keywords=("about", "version", "关于", "版本"),
            ),
            PaletteCommand(
                id="cmd_exit",
                title=tr("command_palette.cmd_exit", default="退出应用"),
                category="command",
                description="Application",
                icon_name="close",
                shortcut="Ctrl+Q",
                callback=lambda: self._invoke_parent("request_exit"),
                keywords=("exit", "quit", "退出", "关闭"),
            ),
        ])

        # 2. Library Tags (#)
        lib_root = self._get_library_root()
        if lib_root:
            tags = self._get_library_tags(lib_root)
            for tag in tags:
                self._commands.append(
                    PaletteCommand(
                        id=f"tag_{tag}",
                        title=f"#{tag}",
                        category="tag",
                        description=tr("command_palette.tag_desc", default="回车过滤此标签"),
                        icon_name="tag",
                        callback=lambda t=tag: self._action_filter_tag(t),
                        keywords=("tag", "标签", tag),
                    )
                )

        # 3. Folders & Favorites (@)
        favorites = self._get_library_favorites(lib_root)
        for fav in favorites:
            fav_path = fav.get("path", "")
            fav_name = fav.get("name") or Path(fav_path).name or fav_path
            fav_icon = fav.get("icon") or "star"
            self._commands.append(
                PaletteCommand(
                    id=f"fav_{fav_path}",
                    title=f"@{fav_name}",
                    category="favorite",
                    description=fav_path,
                    icon_name=fav_icon,
                    callback=lambda p=fav_path: self._action_jump_folder(p),
                    keywords=("folder", "favorite", "收藏", "目录", fav_name, fav_path),
                )
            )

    def _get_library_root(self) -> str:
        parent = self.parent()
        if parent is None:
            return ""
        session = getattr(parent, "_library_session", None)
        if session is not None:
            return str(getattr(session, "root_str", ""))
        return str(getattr(parent, "_current_library_path", ""))

    def _get_library_tags(self, lib_root: str) -> list[str]:
        parent = self.parent()
        if not lib_root or parent is None:
            return []
        try:
            svc = None
            session = getattr(parent, "_library_session", None)
            scoped_factory = getattr(parent, "_scoped_services_for_session", None)
            if callable(scoped_factory) and session:
                scoped = scoped_factory(session)
                svc = getattr(scoped, "tag_service", None)
            bootstrap = getattr(parent, "_bootstrap", None)
            if svc is None and bootstrap is not None and session:
                runtime = bootstrap.runtime_for(session)
                svc = getattr(runtime.services, "tag_service", None)
            if svc is not None and hasattr(svc, "get_all_tags"):
                return list(svc.get_all_tags(lib_root))
        except Exception:
            _log.debug("Failed to query library tags for command palette", exc_info=True)
        return []

    def _get_library_favorites(self, lib_root: str) -> list[dict]:
        parent = self.parent()
        if parent is not None and hasattr(parent, "sidebar"):
            sidebar = getattr(parent, "sidebar")
            favs = getattr(sidebar, "_favs", None)
            if favs is not None and hasattr(favs, "list_all"):
                return favs.list_all()
        if lib_root:
            try:
                from AssetsManager.dialogs.sidebar_favorites import SidebarFavorites

                return SidebarFavorites(lib_root).list_all()
            except Exception:
                pass
        return []

    def _invoke_parent(self, method_name: str, *args: Any) -> None:
        parent = self.parent()
        if parent is not None and hasattr(parent, method_name):
            fn = getattr(parent, method_name)
            if callable(fn):
                fn(*args)

    def _action_toggle_theme(self) -> None:
        current = themes.is_dark()
        targets = themes.light_themes() if current else themes.dark_themes()
        if targets:
            themes.set_theme(targets[0])

    def _action_batch_rename(self) -> None:
        parent = self.parent()
        if parent is None:
            return
        fl = getattr(parent, "file_list", None)
        if fl is not None:
            paths = getattr(fl, "_selected_paths", list)()
            if paths and len(paths) > 1:
                batch_fn = getattr(fl, "_batch_rename", None)
                if callable(batch_fn):
                    batch_fn(paths)
                    return
            elif paths:
                inline_fn = getattr(fl, "_inline_rename", None)
                if callable(inline_fn):
                    inline_fn()
                    return
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.information(
            cast("QWidget", parent),
            tr("filelist.dialog.batch_rename", default="批量重命名"),
            tr("command_palette.no_files_selected", default="请在文件列表中先选中需要重命名的文件。"),
        )

    def _action_open_library_dir(self) -> None:
        lib_root = self._get_library_root()
        if lib_root and Path(lib_root).exists():
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices

            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(lib_root).resolve())))

    def _action_filter_tag(self, tag: str) -> None:
        parent = self.parent()
        if parent is None:
            return
        fl = getattr(parent, "file_list", None)
        if fl is not None:
            search_edit = getattr(fl, "_search", None)
            if search_edit is not None and hasattr(search_edit, "setText"):
                search_edit.setText(tag)
            apply_search = getattr(fl, "_apply_search", None)
            if callable(apply_search):
                apply_search()

    def _action_jump_folder(self, target_path: str) -> None:
        parent = self.parent()
        if parent is None or not target_path:
            return
        nav_fn = getattr(parent, "_on_sidebar_navigate", None)
        if callable(nav_fn):
            nav_fn(target_path)
            return
        fl = getattr(parent, "file_list", None)
        if fl is not None and hasattr(fl, "navigate_to"):
            fl.navigate_to(target_path)

    # ── Search & Filter Logic ─────────────────────────────────

    def _on_search_changed(self, raw_text: str) -> None:
        self._filter_items(raw_text)

    def _matches(self, cmd: PaletteCommand, query: str) -> bool:
        if not query:
            return True
        q = query.lower()
        if q in cmd.title.lower():
            return True
        if q in cmd.description.lower():
            return True
        if q in cmd.shortcut.lower():
            return True
        for kw in cmd.keywords:
            if q in kw.lower():
                return True
        # Subsequence match (e.g. "drk" matches "Dark Mode")
        it = iter(cmd.title.lower())
        if all(char in it for char in q):
            return True
        return False

    def _filter_items(self, raw_text: str) -> None:
        text = raw_text.strip()
        mode = "all"
        query = text

        if text.startswith(">"):
            mode = ">"
            query = text[1:].strip().lower()
        elif text.startswith("#"):
            mode = "#"
            query = text[1:].strip().lower()
        elif text.startswith("@"):
            mode = "@"
            query = text[1:].strip().lower()
        else:
            query = text.lower()

        self._current_mode = mode

        # Group candidates
        commands = [c for c in self._commands if c.category == "command"]
        tags = [c for c in self._commands if c.category == "tag"]
        favorites = [c for c in self._commands if c.category in ("favorite", "folder")]

        self._list.clear()

        groups: list[tuple[str, list[PaletteCommand]]] = []

        if mode == ">":
            matched = [c for c in commands if self._matches(c, query)]
            if matched:
                groups.append((
                    tr("command_palette.group_commands", default="系统命令"),
                    matched,
                ))
        elif mode == "#":
            matched = [c for c in tags if self._matches(c, query)]
            if matched:
                groups.append((
                    tr("command_palette.group_tags", default="库内标签"),
                    matched,
                ))
        elif mode == "@":
            matched = [c for c in favorites if self._matches(c, query)]
            if matched:
                groups.append((
                    tr("command_palette.group_favorites", default="常用文件夹与收藏"),
                    matched,
                ))
        else:
            m_commands = [c for c in commands if self._matches(c, query)]
            m_favorites = [c for c in favorites if self._matches(c, query)]
            m_tags = [c for c in tags if self._matches(c, query)]

            if m_commands:
                groups.append((
                    tr("command_palette.group_commands", default="系统命令"),
                    m_commands,
                ))
            if m_favorites:
                groups.append((
                    tr("command_palette.group_favorites", default="常用文件夹与收藏"),
                    m_favorites,
                ))
            if m_tags:
                groups.append((
                    tr("command_palette.group_tags", default="库内标签"),
                    m_tags,
                ))

        for title, items in groups:
            self._add_header_item(title)
            for cmd in items:
                self._add_command_item(cmd)

        if self._list.count() == 0:
            self._add_empty_item(tr("command_palette.empty", default="未找到匹配项"))
        else:
            self._select_first_actionable_item()

    def _add_header_item(self, title: str) -> None:
        item = QListWidgetItem(self._list)
        item.setData(CommandPaletteDelegate.IsHeaderRole, True)
        item.setData(CommandPaletteDelegate.TitleRole, title)
        item.setFlags(Qt.ItemFlag.NoItemFlags)

    def _add_command_item(self, cmd: PaletteCommand) -> None:
        item = QListWidgetItem(self._list)
        item.setData(CommandPaletteDelegate.IsHeaderRole, False)
        item.setData(CommandPaletteDelegate.TitleRole, cmd.title)
        item.setData(CommandPaletteDelegate.DescRole, cmd.description)
        item.setData(CommandPaletteDelegate.ShortcutRole, cmd.shortcut)
        item.setData(CommandPaletteDelegate.IconNameRole, cmd.icon_name)
        item.setData(CommandPaletteDelegate.CategoryRole, cmd.category)
        item.setData(CommandPaletteDelegate.CallbackRole, cmd.callback)
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
        )

    def _add_empty_item(self, text: str) -> None:
        item = QListWidgetItem(self._list)
        item.setData(CommandPaletteDelegate.IsHeaderRole, True)
        item.setData(CommandPaletteDelegate.TitleRole, text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)

    def _is_header_row(self, row: int) -> bool:
        item = self._list.item(row)
        if not item:
            return True
        return bool(item.data(CommandPaletteDelegate.IsHeaderRole))

    def _select_first_actionable_item(self) -> None:
        for r in range(self._list.count()):
            if not self._is_header_row(r):
                self._list.setCurrentRow(r)
                return

    # ── Keyboard Navigation ───────────────────────────────────

    def eventFilter(self, watched: QWidget, event: QEvent) -> bool:
        if watched is self._input and event.type() == QEvent.Type.KeyPress:
            key_event = cast(QKeyEvent, event)
            key = key_event.key()
            if key == Qt.Key.Key_Down:
                self._navigate(1)
                return True
            if key == Qt.Key.Key_Up:
                self._navigate(-1)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._execute_current()
                return True
            if key == Qt.Key.Key_Escape:
                self.reject()
                return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.reject()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._execute_current()
            return
        if key == Qt.Key.Key_Down:
            self._navigate(1)
            return
        if key == Qt.Key.Key_Up:
            self._navigate(-1)
            return
        super().keyPressEvent(event)

    def _navigate(self, direction: int) -> None:
        count = self._list.count()
        if count == 0:
            return
        selectable = [r for r in range(count) if not self._is_header_row(r)]
        if not selectable:
            return

        current_row = self._list.currentRow()
        if current_row not in selectable:
            target_idx = 0 if direction > 0 else len(selectable) - 1
        else:
            pos = selectable.index(current_row)
            target_idx = (pos + direction) % len(selectable)

        target_row = selectable[target_idx]
        self._list.setCurrentRow(target_row)
        item = self._list.item(target_row)
        if item:
            self._list.scrollToItem(item)

    def _execute_current(self) -> None:
        row = self._list.currentRow()
        if row < 0 or row >= self._list.count():
            return
        item = self._list.item(row)
        if not item or self._is_header_row(row):
            return
        callback = item.data(CommandPaletteDelegate.CallbackRole)
        self.accept()
        if callable(callback):
            try:
                callback()
            except Exception:
                _log.exception("Error executing command palette action")

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        row = self._list.row(item)
        if self._is_header_row(row):
            return
        callback = item.data(CommandPaletteDelegate.CallbackRole)
        self.accept()
        if callable(callback):
            try:
                callback()
            except Exception:
                _log.exception("Error executing command palette action")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._position_floating()
        self._input.setFocus()
        self._input.selectAll()

    def _position_floating(self) -> None:
        parent = self.parent()
        if isinstance(parent, QWidget) and parent.isVisible():
            geo = parent.geometry()
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + max(scaled_px(60), (geo.height() - self.height()) // 3)
        else:
            screen = QGuiApplication.primaryScreen()
            if screen:
                geo = screen.availableGeometry()
                x = geo.x() + (geo.width() - self.width()) // 2
                y = geo.y() + max(scaled_px(60), (geo.height() - self.height()) // 3)
            else:
                x, y = scaled_px(100), scaled_px(100)
        self.move(x, y)
