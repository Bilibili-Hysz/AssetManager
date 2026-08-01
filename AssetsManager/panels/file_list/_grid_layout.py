"""Grid layout math — matches GridDelegate sizeHint exactly."""
from PySide6.QtCore import QRect, QSize


class GridLayout:
    """Pre-computed item positions matching delegate dimensions."""

    def __init__(self):
        self._item_count = 0
        self._widget_width = 0
        self._item_size = 96
        self._spacing = 12
        self._cols = 1
        self._rows = 0
        self._item_w = 0
        self._item_h = 0
        self._x0 = 0
        self._rects: list[QRect] = []

    def compute(self, item_count: int, widget_width: int, item_size: int = 96,
                spacing: int = 12, item_hint: QSize | None = None):
        next_item_w = item_hint.width() if item_hint is not None else item_size + spacing
        next_item_h = item_hint.height() if item_hint is not None else item_size + spacing + 30
        if (item_count == self._item_count and widget_width == self._widget_width
                and item_size == self._item_size and spacing == self._spacing
                and next_item_w == self._item_w and next_item_h == self._item_h
                and self._rects):
            return False
        self._item_count = item_count
        self._widget_width = widget_width
        self._item_size = item_size
        self._spacing = spacing
        self._item_w = next_item_w
        self._item_h = next_item_h
        self._cols = max(1, widget_width // self._item_w)
        self._rows = (item_count + self._cols - 1) // self._cols if self._cols else 0
        # File-manager grids need stable column tracks. Keep the first column
        # fixed instead of recentering the whole array as width or count changes.
        self._x0 = max(0, spacing)
        self._rects = self._build_rects(item_count)
        return True

    def _build_rects(self, n) -> list[QRect]:
        rects = []
        for i in range(n):
            col = i % self._cols
            grid_row = i // self._cols
            x = self._x0 + col * self._item_w
            y = self._spacing + grid_row * self._item_h
            rects.append(QRect(x, y, self._item_w, self._item_h))
        return rects

    def invalidate(self):
        self._item_count = -1
        self._rects.clear()

    def rect_at(self, row: int) -> QRect | None:
        if 0 <= row < len(self._rects):
            return self._rects[row]
        return None

    def row_at(self, x: int, y: int) -> int:
        if not self._rects or x < self._x0 or y < self._spacing:
            return -1
        col = (x - self._x0) // self._item_w
        if col < 0 or col >= self._cols:
            return -1
        grid_row = (y - self._spacing) // self._item_h
        if grid_row < 0 or grid_row >= self._rows:
            return -1
        idx = grid_row * self._cols + col
        return idx if 0 <= idx < self._item_count else -1

    def visible_rows(self, scroll_y: int, viewport_h: int) -> list[int]:
        if not self._rects:
            return []
        sy = max(0, scroll_y - self._spacing)
        first_grid_row = max(0, sy // self._item_h)
        last_grid_row = min(self._rows - 1, (sy + viewport_h) // self._item_h + 1)
        first_item = first_grid_row * self._cols
        last_item = min(self._item_count - 1, last_grid_row * self._cols + self._cols - 1)
        return list(range(first_item, last_item + 1))

    @property
    def total_height(self) -> int:
        if not self._rects:
            return 0
        return self._rects[-1].bottom() + self._spacing

    @property
    def columns(self) -> int:
        return self._cols

    @property
    def item_hint(self) -> QSize:
        return QSize(self._item_w, self._item_h)
