"""GPU-free custom QWidget canvas for file list grid rendering.

Matches GridDelegate layout exactly: CARD_PAD=6, PREVIEW_MARGIN=4,
_TEXT_TOP_GAP=5, _TEXT_LINE_GAP=1, font 9pt bold + 8pt sub.
"""
from collections import OrderedDict
from PySide6.QtCore import Qt, QSize, QRect, QPoint, QTimer, Signal
from PySide6.QtGui import QPainter, QPixmap, QColor, QPen, QFont, QFontMetrics
from PySide6.QtWidgets import QWidget, QScrollBar, QSizePolicy
from AssetsManager.core import themes
from AssetsManager.core.color_utils import _hex_to_rgb
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager import i18n
from AssetsManager.panels.file_list._common import (
    EXT_TO_CATEGORY, badge_color_for_extension, badge_label_for_extension,
)
from AssetsManager.panels.file_list._model import FileSystemModel

tr = i18n.tr

# Layout constants — matching GridDelegate exactly (scaled for DPI)
_CARD_PAD = scaled_px(6)
_PREVIEW_MARGIN = scaled_px(4)
_CORNER_R = scaled_px(8)
_PREVIEW_R = scaled_px(6)
_TEXT_TOP_GAP = scaled_px(5)
_TEXT_LINE_GAP = scaled_px(1)
_BADGE_H = scaled_px(14)
_BADGE_R = scaled_px(4)


def _make_folder_highlight(t: dict) -> QColor:
    r, g, b = _hex_to_rgb(t["hover_overlay"])
    return QColor(r, g, b, 80)
_BADGE_PAD_H = scaled_px(5)


class FileListGridWidget(QWidget):
    """Batch-rendering grid that replaces QListView for local panel use."""

    clicked = Signal(int)
    double_clicked = Signal(int)
    context_menu = Signal(QPoint)
    selection_changed = Signal()
    rename_requested = Signal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        t = themes.get()

        self._model = None
        self._model_rows = 0
        self._layout = None
        self._thumb_size = scaled_px(96)

        self._scroll_y = 0
        self._textures: OrderedDict[int, QPixmap] = OrderedDict()
        self._texture_dpr = max(1.0, float(self.devicePixelRatioF() or 1.0))
        self._dirty: set[int] = set()
        self._hover_row: int = -1
        self._selection: set[int] = set()
        self._last_click_row: int = -1
        self._last_click_pos: QPoint | None = None
        self._rubber_band_active = False
        self._rubber_band_origin: QPoint | None = None
        self._rubber_band_rect: QRect = QRect()
        self._click_pending_row: int = -1

        self._clr_accent = QColor(t["accent"])
        self._clr_heading = QColor(t["heading"])
        self._clr_body = QColor(t["body"])
        self._clr_muted = QColor(t["muted"])
        self._clr_base = QColor(t["base"])
        self._clr_panel = QColor(t["panel"])
        self._clr_border = QColor(t["border"])
        self._clr_folder_highlight = _make_folder_highlight(t)
        self._font_name = QFont()
        self._font_name.setPointSize(scaled_pt(9))
        self._font_name.setBold(True)
        self._fm_name = QFontMetrics(self._font_name)
        self._font_sub = QFont()
        self._font_sub.setPointSize(scaled_pt(8))
        self._fm_sub = QFontMetrics(self._font_sub)
        self._font_badge = QFont()
        self._font_badge.setPointSize(scaled_pt(6))
        self._font_badge.setBold(True)
        self._fm_badge = QFontMetrics(self._font_badge)

        # Computed item hint matching delegate sizeHint
        self._t_h = _TEXT_TOP_GAP + self._fm_name.height() + _TEXT_LINE_GAP + self._fm_sub.height()
        self._update_item_hint()

        self._scrollbar = QScrollBar(Qt.Orientation.Vertical, self)
        self._scrollbar.valueChanged.connect(self._on_scroll)
        self._scrollbar.setSingleStep(30)
        self._scrollbar.setPageStep(300)
        self._apply_scrollbar_theme()

        # ── Animation state ────────────────────────────────────
        self._thumb_opacity: dict[int, float] = {}
        self._hover_progress: dict[int, float] = {}
        self._selection_progress: dict[int, float] = {}
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._anim_tick)
        self._entrance_queue: list[int] = []
        self._entrance_visible: set[int] = set()
        self._reduce_motion = self._detect_reduce_motion()

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(100, 100)

    def _update_item_hint(self):
        """Item size matching GridDelegate.sizeHint."""
        self._item_w = _CARD_PAD * 2 + _PREVIEW_MARGIN * 2 + self._thumb_size + 2
        self._item_h = _CARD_PAD * 2 + _PREVIEW_MARGIN * 2 + self._thumb_size + self._t_h + 2
        self._item_hint = QSize(self._item_w, self._item_h)

    # ── Public API ──────────────────────────────────────────

    def set_model(self, model):
        self._model = model
        model.modelReset.connect(self._on_model_reset)
        model.dataChanged.connect(self._on_data_changed)

    def set_layout_ref(self, layout):
        self._layout = layout

    def set_thumb_size(self, size: int):
        self._thumb_size = size
        self._update_item_hint()

    def invalidate_textures(self):
        self._textures.clear()
        self._dirty = set(range(self._model_rows))

    def mark_loaded(self, row: int):
        self._dirty.add(row)
        if not self._reduce_motion and row not in self._textures:
            self._thumb_opacity[row] = 0.0
            if not self._anim_timer.isActive():
                self._anim_timer.start()

    def set_scrolling(self, active: bool = True):
        pass

    def on_thumb_batch(self, rows: list[int]):
        for r in rows:
            self._dirty.add(r)

    def _on_model_reset(self):
        self._textures.clear()
        self._dirty.clear()
        self._selection.clear()
        self._thumb_opacity.clear()
        self._hover_progress.clear()
        self._selection_progress.clear()
        self._entrance_queue.clear()
        self._entrance_visible.clear()

    def _on_data_changed(self, top_left, bottom_right, _roles):
        for r in range(top_left.row(), bottom_right.row() + 1):
            self._dirty.add(r)
            self._textures.pop(r, None)
            self._thumb_opacity.pop(r, None)
            self._hover_progress.pop(r, None)
            self._selection_progress.pop(r, None)

    def selection_model_rows(self) -> set[int]:
        return self._selection.copy()

    def select_all(self):
        old = self._selection.copy()
        self._selection = set(range(self._model_rows))
        self._apply_selection_progress(old)
        if old != self._selection:
            self.selection_changed.emit()
        self.update()

    def clear_selection(self):
        old = self._selection.copy()
        self._selection.clear()
        self._apply_selection_progress(old)
        if old:
            self.selection_changed.emit()
        self.update()

    # ── Layout update ───────────────────────────────────────

    def update_layout(self, item_count: int, widget_width: int):
        self._model_rows = item_count
        if item_count > 0:
            self._has_been_populated = True
        if self._layout:
            prev_cols = self._layout._cols if hasattr(self._layout, '_cols') else 0
            self._layout.compute(item_count, max(widget_width - 20, 100),
                                 self._thumb_size, item_hint=self._item_hint)
            th = self._layout.total_height
            self._scrollbar.setRange(0, max(0, th - self.height()))
            to_del = [r for r in self._textures if r >= item_count]
            for r in to_del:
                del self._textures[r]
            cur_cols = getattr(self._layout, '_cols', 0)
            if cur_cols != prev_cols or not hasattr(self, '_dirty_except_resize'):
                self._dirty |= set(range(item_count))
            self.update()

    # ── Card rect helper ─────────────────────────────────────

    def _card_rect_in_item(self, item_rect: QRect) -> QRect:
        """Card within item: inset by CARD_PAD on all sides (matches delegate)."""
        return QRect(
            item_rect.x() + _CARD_PAD, item_rect.y() + _CARD_PAD,
            item_rect.width() - _CARD_PAD * 2, item_rect.height() - _CARD_PAD * 2,
        )

    # ── Painting ────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        # Ensure entrance animation plays on first visible layout
        if self._model and self._model_rows > 0 and not self._entrance_visible:
            QTimer.singleShot(0, self._start_entrance_stagger)

    def paintEvent(self, _evt):
        if not self._model or not self._layout or not self.isVisible():
            return
        if self.width() == 0 or self.height() == 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        dpr = max(1.0, float(self.devicePixelRatioF() or 1.0))
        if dpr != self._texture_dpr:
            self._texture_dpr = dpr
            self._textures.clear()
            self._dirty = set(range(self._model_rows))
        if not themes.bg_enabled():
            p.fillRect(self.rect(), self._clr_panel)

        if self._model_rows == 0:
            # Empty or loading — don't show message during async scan
            # Only show "empty" if model has been populated at least once
            if hasattr(self, '_has_been_populated') and self._has_been_populated:
                p.setPen(self._clr_muted)
                p.setFont(self._font_name)
                p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Folder is empty")
            p.end()
            return

        sy = self._scroll_y
        vh = self.height()
        visible = self._layout.visible_rows(sy, vh)
        if not visible:
            p.end()
            return

        p.translate(0, -sy)

        for row in visible:
            rect = self._layout.rect_at(row)
            if rect is None:
                continue
            dirty = row in self._dirty
            tex = None if dirty else self._textures.get(row)
            if not tex:
                tex = self._render_item(row, rect)
                if tex is not None:
                    self._textures[row] = tex
                self._dirty.discard(row)
            if tex:
                op = self._thumb_opacity.get(row, 1.0)
                lift_scale = 1.075
                lift_dy = -5
                if row == self._hover_row:
                    sw = int(rect.width() * lift_scale)
                    sh = int(rect.height() * lift_scale)
                    dx = (rect.width() - sw) // 2
                    target = QRect(rect.x() + dx, rect.y() + lift_dy, sw, sh)
                    if op < 1.0:
                        p.save()
                        p.setOpacity(op)
                        p.drawPixmap(target, tex)
                        p.restore()
                    else:
                        p.drawPixmap(target, tex)
                elif row in self._hover_progress:
                    pv = self._hover_progress[row]
                    if pv > 0.01:
                        s = 1.0 + 0.075 * pv
                        sw = int(rect.width() * s)
                        sh = int(rect.height() * s)
                        dx = (rect.width() - sw) // 2
                        dy = int(lift_dy * pv)
                        target = QRect(rect.x() + dx, rect.y() + dy, sw, sh)
                        if op < 1.0:
                            p.save()
                            p.setOpacity(op)
                            p.drawPixmap(target, tex)
                            p.restore()
                        else:
                            p.drawPixmap(target, tex)
                    elif op < 1.0:
                        p.save()
                        p.setOpacity(op)
                        p.drawPixmap(rect.topLeft(), tex)
                        p.restore()
                    else:
                        p.drawPixmap(rect.topLeft(), tex)
                elif op < 1.0:
                    p.save()
                    p.setOpacity(op)
                    p.drawPixmap(rect.topLeft(), tex)
                    p.restore()
                else:
                    p.drawPixmap(rect.topLeft(), tex)

        # ── Rubber band overlay ──
        if self._rubber_band_active and not self._rubber_band_rect.isNull():
            rb = QColor(self._clr_accent)
            rb.setAlpha(30)
            p.setPen(QPen(self._clr_accent, 1))
            p.setBrush(rb)
            p.drawRect(self._rubber_band_rect)

        p.end()

    # ── Animation engine ─────────────────────────────────────

    @staticmethod
    def _detect_reduce_motion() -> bool:
        try:
            from AssetsManager.core.settings import AppSettings
            return AppSettings.instance().get("reduce_motion", False)
        except Exception:
            return False

    def _start_entrance_stagger(self):
        """Queue visible items to appear one-by-one after navigation."""
        if self._reduce_motion:
            return
        self._entrance_queue.clear()
        self._entrance_visible.clear()
        if self._layout and self._model_rows > 0:
            visible = self._layout.visible_rows(self._scroll_y, self.height())
            if visible:
                for row in visible:
                    self._entrance_queue.append(row)
            else:
                # Fallback: layout exists but visible rows empty (e.g. first render)
                for row in range(min(self._model_rows, 20)):
                    self._entrance_queue.append(row)
        elif self._model_rows > 0:
            for row in range(min(self._model_rows, 20)):
                self._entrance_queue.append(row)
        if self._entrance_queue and not self._anim_timer.isActive():
            self._anim_timer.start()

    def _apply_selection_progress(self, old_selection: set[int]):
        """Seed deselected rows for fade-out; mark all changed rows dirty for re-render."""
        for r in old_selection ^ self._selection:
            self._dirty.add(r)
            self._textures.pop(r, None)
        if self._reduce_motion:
            return
        for r in old_selection - self._selection:
            self._selection_progress[r] = 1.0
        if self._selection_progress and not self._anim_timer.isActive():
            self._anim_timer.start()

    def _anim_tick(self):
        """Process all animations: fade, hover, selection, entrance stagger."""
        active = False

        # Thumbnail fade-in: linear step per frame
        for row in list(self._thumb_opacity):
            v = self._thumb_opacity[row] + 0.12
            if v >= 1.0:
                del self._thumb_opacity[row]
            else:
                self._thumb_opacity[row] = v
                active = True

        # Hover fade-out (only deselected rows are animated)
        for row in list(self._hover_progress):
            target = 1.0 if row == self._hover_row else 0.0
            cur = self._hover_progress[row]
            cur += (target - cur) * 0.30
            if abs(cur - target) < 0.01:
                if target == 0.0:
                    del self._hover_progress[row]
                    self._dirty.add(row)
                    self._textures.pop(row, None)
                else:
                    self._hover_progress[row] = 1.0
                continue
            self._hover_progress[row] = cur
            active = True

        # Selection fade-out (only deselected rows are animated)
        for row in list(self._selection_progress):
            cur = self._selection_progress[row]
            cur += (0.0 - cur) * 0.30
            if abs(cur) < 0.01:
                del self._selection_progress[row]
                self._dirty.add(row)
                self._textures.pop(row, None)
                self.selection_changed.emit()
                continue
            self._selection_progress[row] = cur
            active = True

        # Entrance stagger: reveal next item in queue each tick
        if self._entrance_queue:
            n = max(1, len(self._entrance_queue) // 12)
            for _ in range(n):
                if self._entrance_queue:
                    r = self._entrance_queue.pop(0)
                    self._entrance_visible.add(r)
                    self._thumb_opacity[r] = 0.0
            active = True

        if not active:
            self._anim_timer.stop()
        self.update()

    def _render_item(self, row: int, item_rect: QRect) -> QPixmap | None:
        """Render item to offscreen QPixmap. Selection/hover baked into texture."""
        dpr = max(1.0, float(self.devicePixelRatioF() or 1.0))
        tex = QPixmap(int(item_rect.width() * dpr), int(item_rect.height() * dpr))
        tex.setDevicePixelRatio(dpr)
        tex.fill(Qt.GlobalColor.transparent)
        tp = QPainter(tex)
        tp.setRenderHint(QPainter.RenderHint.Antialiasing)
        tp.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        is_dir = self._model.data(self._model.index(row, 0), FileSystemModel.IS_DIR_ROLE)
        pixmap = self._model.data(self._model.index(row, 0), FileSystemModel.RAW_PIXMAP_ROLE)
        name = self._model.data(self._model.index(row, 0), Qt.ItemDataRole.DisplayRole)
        subtitle = self._model.data(self._model.index(row, 0), FileSystemModel.SUBTITLE_ROLE)
        selected = row in self._selection
        hovered = row == self._hover_row

        card = self._card_rect_in_item(QRect(0, 0, item_rect.width(), item_rect.height()))

        # Card fill + border — tinted by selection and hover state
        if selected:
            fill = QColor(self._clr_accent)
            fill.setAlpha(80)
            border = QColor(self._clr_accent)
            border.setAlpha(200)
        elif hovered:
            r2, g2, b2 = self._clr_heading.red(), self._clr_heading.green(), self._clr_heading.blue()
            fill = QColor(r2, g2, b2, 20)
            border = QColor(r2, g2, b2, 50)
        else:
            r2, g2, b2 = self._clr_heading.red(), self._clr_heading.green(), self._clr_heading.blue()
            fill = QColor(r2, g2, b2, 10)
            border = QColor(r2, g2, b2, 20)
        tp.setPen(QPen(border, 1.5 if selected else 1))
        tp.setBrush(fill)
        tp.drawRoundedRect(card, _CORNER_R, _CORNER_R)

        preview = QRect(card.x() + _PREVIEW_MARGIN, card.y() + _PREVIEW_MARGIN,
                        self._thumb_size, self._thumb_size)
        if is_dir:
            self._draw_folder(tp, preview, pixmap)
        elif pixmap and not pixmap.isNull():
            self._draw_image(tp, preview, pixmap)
        else:
            self._draw_type_icon(tp, preview, is_dir, name)

        # ── Category badge ──
        ext = ""
        if not is_dir:
            if name and "." in name:
                ext = name[name.rfind("."):].lower()
            if ext:
                self._draw_badge(tp, preview, ext)

        tp.setFont(self._font_name)
        name_color = self._ext_name_color(ext) if not is_dir else self._clr_body
        tp.setPen(name_color)
        name_y = preview.bottom() + _TEXT_TOP_GAP
        name_rect = QRect(card.x() + _CARD_PAD // 2, name_y,
                          card.width() - _CARD_PAD, self._fm_name.height())
        elided = self._fm_name.elidedText(
            name or "", Qt.TextElideMode.ElideRight, name_rect.width())
        tp.drawText(name_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, elided)

        if subtitle:
            tp.setFont(self._font_sub)
            tp.setPen(self._clr_muted)
            sub_y = name_rect.bottom() + _TEXT_LINE_GAP
            sub_rect = QRect(card.x() + _CARD_PAD // 2, sub_y,
                             card.width() - _CARD_PAD, self._fm_sub.height())
            elided_sub = self._fm_sub.elidedText(
                subtitle or "", Qt.TextElideMode.ElideRight, sub_rect.width())
            tp.drawText(sub_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                        elided_sub)

        tp.end()

        if len(self._textures) >= 200:
            self._textures.popitem(last=False)
        return tex

    # ── Folder / Image rendering ────────────────────────────

    def _folder_colors(self):
        """Folder colors — warm gold tones blended with theme accent.
        Matches delegate formula: accent*0.6+gold*0.4 (body), accent*0.4+gold*0.6 (front)."""
        accent = self._clr_accent
        body = QColor(
            int(accent.red() * 0.6 + 0xc9 * 0.4),
            int(accent.green() * 0.6 + 0xa0 * 0.4),
            int(accent.blue() * 0.6 + 0x63 * 0.4))
        front = QColor(
            int(accent.red() * 0.4 + 0xfb * 0.6),
            int(accent.green() * 0.4 + 0xd8 * 0.6),
            int(accent.blue() * 0.4 + 0x96 * 0.6))
        return body, front

    def _draw_folder(self, p: QPainter, rect: QRect, pixmap):
        body_c, front_c = self._folder_colors()
        icon_w = rect.width()
        icon_h = int(rect.height() * 0.85)
        folder = QRect(rect.x(), rect.y() + int(rect.height() * 0.15), icon_w, icon_h)
        tab_w = int(icon_w * 0.35)
        tab_h = max(5, int(icon_h * 0.10))
        tab_rect = QRect(folder.left(), folder.top() - tab_h, tab_w, tab_h + 5)
        has_image = pixmap is not None and not pixmap.isNull()
        front_h = int(icon_h * (0.25 if has_image else 0.70))
        front_rect = QRect(folder.left(), folder.bottom() - front_h, folder.width(), front_h)

        # Subtle folder shadow (two overlapping rects, no path merge)
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 20))
        p.drawRoundedRect(tab_rect.adjusted(1, 1, 1, 1), 4, 4)
        p.drawRoundedRect(folder.adjusted(1, 2, -1, -1), 5, 5)
        p.restore()

        # Tab + Body (two overlapping rects matching delegate — avoids antialias seam)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(body_c)
        p.drawRoundedRect(tab_rect, 4, 4)
        p.drawRoundedRect(folder, 5, 5)

        if has_image:
            img_rect = folder.adjusted(6, -15, -6, -8)
            scaled = pixmap.scaled(img_rect.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            px = img_rect.center().x() - scaled.width() // 2
            py = img_rect.bottom() - scaled.height()
            p.save()
            p.setClipRect(folder)
            p.drawPixmap(px, py, scaled)
            p.restore()

        p.setBrush(front_c)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(front_rect, 5, 5)
        p.setPen(QPen(self._clr_folder_highlight, 1))
        p.drawLine(front_rect.left() + 2, front_rect.top(),
                    front_rect.right() - 2, front_rect.top())

    def _draw_image(self, p: QPainter, rect: QRect, pixmap):
        bg = self._clr_base.lighter(120)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(rect, _PREVIEW_R, _PREVIEW_R)
        inner = rect.adjusted(3, 3, -3, -3)
        scaled = pixmap.scaled(inner.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
        ix = inner.x() + (inner.width() - scaled.width()) // 2
        iy = inner.y() + (inner.height() - scaled.height()) // 2
        p.drawPixmap(ix, iy, scaled)

    def _draw_type_icon(self, p: QPainter, rect: QRect, is_dir: bool, name: str):
        if is_dir:
            body_c, _ = self._folder_colors()
            folder = QRect(rect.x(), rect.y() + int(rect.height() * 0.15),
                           rect.width(), int(rect.height() * 0.85))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(body_c)
            p.drawRoundedRect(folder, 5, 5)
        else:
            ext = name[name.rfind("."):].lower() if "." in name else ""
            clr = QColor(badge_color_for_extension(ext))
            clr.setAlpha(50)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(clr)
            p.drawRoundedRect(rect, _PREVIEW_R, _PREVIEW_R)
            p.setFont(self._font_sub)
            p.setPen(self._clr_muted)
            cat = EXT_TO_CATEGORY.get(ext, "Other")
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, cat[:4])

    # ── Badge ────────────────────────────────────────────────

    @staticmethod
    def _ext_name_color(ext: str) -> QColor:
        t = themes.get()
        cat = EXT_TO_CATEGORY.get(ext)
        if cat == "Images":
            return QColor(t['success'])
        if cat == "3D Models":
            return QColor(t['accent'])
        if cat == "Videos":
            return QColor("#c480d4")  # purple — no theme equivalent
        if cat == "Archives":
            return QColor(t['warning'])
        return QColor(t['muted'])

    def _draw_badge(self, p: QPainter, preview_rect: QRect, ext: str):
        color = badge_color_for_extension(ext)
        label = badge_label_for_extension(ext)
        p.setFont(self._font_badge)
        bw = self._fm_badge.horizontalAdvance(label) + _BADGE_PAD_H * 2
        badge_rect = QRect(
            preview_rect.right() - bw - 2, preview_rect.top() + 2,
            bw, _BADGE_H,
        )
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        p.drawRoundedRect(badge_rect, _BADGE_R, _BADGE_R)
        text_color = QColor("white") if QColor(color).lightness() < 128 else QColor("black")
        p.setPen(text_color)
        p.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, label)

    # ── Theme ────────────────────────────────────────────────

    def _rebuild_theme(self):
        t = themes.get()
        self._clr_accent = QColor(t["accent"])
        self._clr_heading = QColor(t["heading"])
        self._clr_body = QColor(t["body"])
        self._clr_muted = QColor(t["muted"])
        self._clr_base = QColor(t["base"])
        self._clr_panel = QColor(t["panel"])
        self._clr_border = QColor(t["border"])
        self._apply_scrollbar_theme()

    def _apply_scrollbar_theme(self):
        t = themes.get()
        self._scrollbar.setStyleSheet(
            f"QScrollBar:vertical {{ background: {t['panel']}; width:{scaled_px(8)}px; }}"
            f"QScrollBar::handle:vertical {{ background: {t['border']}; "
            f"border-radius:{scaled_px(4)}px; min-height:30px; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}")

    def refresh_theme(self):
        self._rebuild_theme()
        self._textures.clear()
        self._dirty = set(range(self._model_rows))
        self.update()

    # ── Scroll ───────────────────────────────────────────────

    def scroll_to(self, row: int):
        if self._layout:
            rect = self._layout.rect_at(row)
            if rect:
                self._scrollbar.setValue(rect.top() - self.height() // 4)

    def _on_scroll(self, value: int):
        self._scroll_y = value
        self.update()

    # ── Resize ───────────────────────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scrollbar.setGeometry(self.width() - 8, 0, 8, self.height())
        if self._model_rows > 0:
            self.update_layout(self._model_rows, self.width())
        self.update()

    # ── Mouse events ─────────────────────────────────────────

    def mousePressEvent(self, event):
        pos = event.position().toPoint()
        pos.setY(pos.y() + self._scroll_y)
        old_selection = self._selection.copy()
        if self._layout:
            row = self._layout.row_at(pos.x(), pos.y())
            if row >= 0:
                if event.button() == Qt.MouseButton.LeftButton:
                    if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                        if row in self._selection:
                            self._selection.discard(row)
                        else:
                            self._selection.add(row)
                        self.clicked.emit(row)
                    elif (event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                          and self._last_click_row >= 0):
                        lo = min(row, self._last_click_row)
                        hi = max(row, self._last_click_row)
                        self._selection = set(range(lo, hi + 1))
                        self.clicked.emit(row)
                    else:
                        self._click_pending_row = row
                        if row not in self._selection:
                            self._selection = {row}
                            self.clicked.emit(row)
                    self._last_click_row = row
                    self._hover_row = row
                    self.selection_changed.emit()
                    # Seed selection progress for animation
                    self._apply_selection_progress(old_selection)
                    self.update()
            elif event.button() == Qt.MouseButton.LeftButton:
                self._rubber_band_active = True
                self._rubber_band_origin = QPoint(pos)
                self._rubber_band_rect = QRect(pos.x(), pos.y(), 0, 0)
                if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                    old_sel = self._selection.copy()
                    self._selection.clear()
                    for r in old_sel:
                        self._dirty.add(r)
                        self._textures.pop(r, None)
                self.selection_changed.emit()
                self.update()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        pos = event.position().toPoint()
        pos.setY(pos.y() + self._scroll_y)
        if self._layout:
            row = self._layout.row_at(pos.x(), pos.y())
            if row >= 0:
                self.double_clicked.emit(row)
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        pos.setY(pos.y() + self._scroll_y)
        if self._rubber_band_active and self._rubber_band_origin:
            self._rubber_band_rect = QRect(self._rubber_band_origin, pos).normalized()
            if self._layout:
                preview_sel = set()
                visible = self._layout.visible_rows(self._scroll_y, self.height())
                for r in visible:
                    item_rect = self._layout.rect_at(r)
                    if item_rect and self._rubber_band_rect.intersects(item_rect):
                        preview_sel.add(r)
                if preview_sel != self._selection:
                    # Seed selection progress for animation
                    if not self._reduce_motion:
                        for r in preview_sel - self._selection:
                            self._selection_progress.setdefault(r, 0.0)
                        for r in self._selection - preview_sel:
                            if r not in self._selection_progress:
                                self._selection_progress[r] = 1.0
                        if not self._anim_timer.isActive():
                            self._anim_timer.start()
                    self._selection = preview_sel
                    self.selection_changed.emit()
            self.update()
        elif self._layout:
            # Freeze hover during potential drag (left button held on an item)
            if (event.buttons() & Qt.MouseButton.LeftButton
                    and not self._rubber_band_active
                    and self._click_pending_row >= 0):
                super().mouseMoveEvent(event)
                return
            row = self._layout.row_at(pos.x(), pos.y())
            if self._hover_row != row:
                old = self._hover_row
                self._dirty.add(old)
                self._hover_row = row
                self._dirty.add(row)
                if not self._reduce_motion:
                    if old >= 0:
                        self._hover_progress.setdefault(old, 1.0)
                    if row >= 0:
                        self._hover_progress.setdefault(row, 0.0)
                    if not self._anim_timer.isActive():
                        self._anim_timer.start()
                self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._rubber_band_active:
            self._rubber_band_active = False
            if self._layout and not self._rubber_band_rect.isNull():
                final_sel = set()
                rect = self._rubber_band_rect
                ih = self._layout._item_h
                first_row = max(0, rect.top() // ih)
                last_row = min(self._model_rows - 1, (rect.bottom() + ih - 1) // ih)
                for r in range(first_row, last_row + 1):
                    item_rect = self._layout.rect_at(r)
                    if item_rect and rect.intersects(item_rect):
                        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                            self._selection.discard(r)
                        else:
                            self._selection.add(r)
                            final_sel.add(r)
                # Seed progress for final selection
                if not self._reduce_motion and final_sel:
                    for r in final_sel:
                        self._selection_progress.setdefault(r, 0.0)
                    if not self._anim_timer.isActive():
                        self._anim_timer.start()
                self.selection_changed.emit()
            self._rubber_band_origin = None
            self._rubber_band_rect = QRect()
            self.update()
        elif self._click_pending_row >= 0:
            row = self._click_pending_row
            self._click_pending_row = -1
            # If a drag was started (QDrag.exec was called), skip deselect
            # _drag_started is set by parent eventFilter before QDrag begins
            if getattr(self, '_drag_started', False):
                pass
            elif row in self._selection and len(self._selection) > 1:
                old_sel = self._selection.copy()
                self._selection = {row}
                self._apply_selection_progress(old_sel)
                self.clicked.emit(row)
                self.selection_changed.emit()
                self.update()
        super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        # Use actual cursor position, not entry-point (entry may be at y=0 above first item)
        pos = self.mapFromGlobal(self.cursor().pos())
        pos.setY(pos.y() + self._scroll_y)
        if self._layout:
            row = self._layout.row_at(pos.x(), pos.y())
            if row >= 0 and self._hover_row != row:
                old = self._hover_row
                self._hover_row = row
                if old >= 0:
                    self._hover_progress.setdefault(old, 1.0)
                self._hover_progress.setdefault(row, 0.0)
                if not self._anim_timer.isActive():
                    self._anim_timer.start()
                self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._hover_row >= 0:
            old = self._hover_row
            self._hover_row = -1
            self._dirty.add(old)
            if not self._reduce_motion:
                self._hover_progress.setdefault(old, 1.0)
                if not self._anim_timer.isActive():
                    self._anim_timer.start()
            self.update()
        super().leaveEvent(event)

    def contextMenuEvent(self, event):
        self.context_menu.emit(event.globalPos())

    # ── Keyboard ─────────────────────────────────────────────

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        cols = self._layout.columns if self._layout else 1
        if key == Qt.Key.Key_Home:
            self._scrollbar.setValue(0)
        elif key == Qt.Key.Key_End:
            self._scrollbar.setValue(self._scrollbar.maximum())
        elif key == Qt.Key.Key_PageUp:
            self._scrollbar.triggerAction(QScrollBar.SliderAction.SliderPageStepSub)
        elif key == Qt.Key.Key_PageDown:
            self._scrollbar.triggerAction(QScrollBar.SliderAction.SliderPageStepAdd)
        elif key == Qt.Key.Key_Space:
            if self._hover_row >= 0:
                if self._hover_row in self._selection:
                    self._selection.discard(self._hover_row)
                else:
                    self._selection.add(self._hover_row)
                self._last_click_row = self._hover_row
                self.selection_changed.emit()
                self.update()
        elif key == Qt.Key.Key_Up:
            self._step_mod_arrow(-cols, mods)
        elif key == Qt.Key.Key_Down:
            self._step_mod_arrow(cols, mods)
        elif key == Qt.Key.Key_Left:
            if self._selection:
                row = next(iter(self._selection))
                if row % cols > 0:
                    self._step_mod_arrow(-1, mods)
        elif key == Qt.Key.Key_Right:
            if self._selection:
                row = next(iter(self._selection))
                if row % cols < cols - 1:
                    self._step_mod_arrow(1, mods)
        elif key == Qt.Key.Key_A and mods & Qt.KeyboardModifier.ControlModifier:
            self.select_all()
        else:
            super().keyPressEvent(event)

    def _step_mod_arrow(self, delta: int, mods):
        if not self._selection:
            return
        new_row = max(0, min(self._model_rows - 1, (self._last_click_row or 0) + delta))
        if mods & Qt.KeyboardModifier.ShiftModifier:
            lo = min(new_row, self._last_click_row or 0)
            hi = max(new_row, self._last_click_row or 0)
            self._selection = set(range(lo, hi + 1))
        elif mods & Qt.KeyboardModifier.ControlModifier:
            # Ctrl+Arrow: move focus only, don't change selection
            self._last_click_row = new_row
            self.scroll_to(new_row)
            self.update()
            return
        else:
            self._selection = {new_row}
        self._last_click_row = new_row
        self.scroll_to(new_row)
        self.selection_changed.emit()
        self.update()

    # ── Inline rename ────────────────────────────────────────

    def _start_rename(self, row: int):
        from PySide6.QtWidgets import QLineEdit
        if not self._layout:
            return
        rect = self._layout.rect_at(row)
        if rect is None:
            return
        name = self._model.data(self._model.index(row, 0), Qt.ItemDataRole.DisplayRole) or ""
        editor = QLineEdit(self)
        editor.setText(name)
        editor.selectAll()
        editor.setGeometry(rect.x(), rect.y() - self._scroll_y,
                           rect.width(), editor.sizeHint().height())
        editor.setFocus()
        editor.show()
        def _finish():
            new_name = editor.text().strip()
            editor.deleteLater()
            if new_name and new_name != name:
                self.rename_requested.emit(row, new_name)
        editor.editingFinished.connect(_finish)
        editor.returnPressed.connect(_finish)

    # ── Wheel / zoom ─────────────────────────────────────────

    def wheelEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            event.ignore()
            return
        self._scrollbar.wheelEvent(event)
        self._scroll_y = self._scrollbar.value()


