"""Shared visual helpers used by more than one sharing-settings page."""
from AssetsManager.core import themes
from AssetsManager.core.color_utils import alpha
from AssetsManager.core.ui_scale import scaled_px
from AssetsManager.dialogs._sharing_helpers import _t


class SharedUiMixin:
    """Visual helpers shared by the share-links and access pages."""

    def _apply_table_theme(self):
        t = _t()
        radius = scaled_px(int(themes.prop("border_radius", "sm")))
        pad_x = scaled_px(int(themes.prop("spacing", "sm")))
        table_style = (
            f"QTableWidget {{ background: {t['panel']}; color: {t['body']}; "
            f"alternate-background-color: {alpha(t['header'], 0.18)}; "
            f"selection-background-color: {alpha(t['accent'], 0.24)}; "
            f"selection-color: {t['heading']}; "
            f"border: {scaled_px(1)}px solid {t['border_subtle']}; border-radius: {radius}px; outline: none; }}"
            f"QTableWidget::item {{ padding: {scaled_px(5)}px {pad_x}px; border: none; "
            f"border-bottom: {scaled_px(1)}px solid {alpha(t['border'], 0.16)}; }}"
            f"QTableWidget::item:hover {{ background: {alpha(t['accent'], 0.10)}; }}"
            f"QTableWidget::item:selected {{ background: {alpha(t['accent'], 0.24)}; color: {t['heading']}; }}"
            f"QHeaderView::section {{ background: {t['header']}; color: {t['heading']}; "
            f"padding: {scaled_px(6)}px {pad_x}px; border: none; "
            f"border-right: {scaled_px(1)}px solid {alpha(t['border'], 0.24)}; "
            f"font-weight: bold; }}"
        )
        for table in (
            getattr(self, "_links_table", None),
            getattr(self, "_codes_table", None),
            getattr(self, "_online_table", None),
        ):
            if table is None:
                continue
            table.setAlternatingRowColors(True)
            table.setShowGrid(False)
            table.verticalHeader().setDefaultSectionSize(scaled_px(30))
            table.horizontalHeader().setMinimumHeight(scaled_px(30))
            table.setStyleSheet(table_style)
