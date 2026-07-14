"""Color picker dialog with HSV/RGB mode toggle."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QLineEdit, QLabel, QPushButton, QRadioButton,
    QSpinBox, QGroupBox, QButtonGroup,
)
from PySide6.QtGui import QColor
from AssetsManager.core.ui_scale import scaled_px
from AssetsManager.widgets.hsv_wheel import HSVWheel, BrightnessSlider
from AssetsManager import i18n
tr = i18n.tr


class ColorPickerDialog(QDialog):
    color_selected = Signal(QColor)

    def __init__(self, initial_color: QColor | None = None, parent=None):
        super().__init__(parent)
        self._color = initial_color or QColor("#ff6b6b")
        self._updating = False
        self.setWindowTitle(tr("colorpicker.title"))
        self.setMinimumSize(scaled_px(400), scaled_px(350))
        self._setup_ui()
        self._update_from_color(self._color)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(scaled_px(8))

        # Top: HSV wheel + brightness slider
        top = QHBoxLayout()
        self._wheel = HSVWheel()
        self._wheel.color_changed.connect(self._on_wheel_changed)
        self._brightness = BrightnessSlider()
        self._brightness.value_changed.connect(self._on_brightness_changed)
        top.addWidget(self._wheel, 1)
        top.addWidget(self._brightness)
        layout.addLayout(top, 1)

        # Mode toggle
        mode_row = QHBoxLayout()
        self._mode_group = QButtonGroup(self)
        self._hsv_mode = QRadioButton(tr("colorpicker.mode_hsv"))
        self._rgb_mode = QRadioButton(tr("colorpicker.mode_rgb"))
        self._mode_group.addButton(self._hsv_mode)
        self._mode_group.addButton(self._rgb_mode)
        self._hsv_mode.setChecked(True)
        self._hsv_mode.toggled.connect(self._on_mode_changed)
        mode_row.addWidget(self._hsv_mode)
        mode_row.addWidget(self._rgb_mode)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        # HSV inputs
        self._hsv_group = QGroupBox(tr("colorpicker.group_hsv"))
        hsv_layout = QHBoxLayout(self._hsv_group)
        self._h_spin = self._make_spin(0, 360, "H:")
        self._s_spin = self._make_spin(0, 100, "S:")
        self._v_spin = self._make_spin(0, 100, "V:")
        hsv_layout.addWidget(self._h_spin[0])
        hsv_layout.addWidget(self._h_spin[1])
        hsv_layout.addWidget(self._s_spin[0])
        hsv_layout.addWidget(self._s_spin[1])
        hsv_layout.addWidget(self._v_spin[0])
        hsv_layout.addWidget(self._v_spin[1])
        layout.addWidget(self._hsv_group)

        # RGB inputs
        self._rgb_group = QGroupBox(tr("colorpicker.group_rgb"))
        rgb_layout = QHBoxLayout(self._rgb_group)
        self._r_spin = self._make_spin(0, 255, "R:")
        self._g_spin = self._make_spin(0, 255, "G:")
        self._b_spin = self._make_spin(0, 255, "B:")
        rgb_layout.addWidget(self._r_spin[0])
        rgb_layout.addWidget(self._r_spin[1])
        rgb_layout.addWidget(self._g_spin[0])
        rgb_layout.addWidget(self._g_spin[1])
        rgb_layout.addWidget(self._b_spin[0])
        rgb_layout.addWidget(self._b_spin[1])
        self._rgb_group.setVisible(False)
        layout.addWidget(self._rgb_group)

        # HEX + preview
        hex_row = QHBoxLayout()
        hex_row.addWidget(QLabel(tr("colorpicker.hex_label")))
        self._hex_input = QLineEdit()
        self._hex_input.setMaximumWidth(scaled_px(100))
        self._hex_input.editingFinished.connect(self._on_hex_changed)
        hex_row.addWidget(self._hex_input)
        self._preview = QLabel()
        self._preview.setFixedSize(scaled_px(32), scaled_px(32))
        self._preview.setStyleSheet(
            f"background: {self._color.name()}; border: 1px solid #555; border-radius: 4px;"
        )
        hex_row.addWidget(self._preview)
        hex_row.addStretch()
        layout.addLayout(hex_row)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton(tr("colorpicker.ok"))
        ok_btn.clicked.connect(self._on_ok)
        cancel_btn = QPushButton(tr("colorpicker.cancel"))
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _make_spin(self, min_val, max_val, label):
        lbl = QLabel(label)
        spin = QSpinBox()
        spin.setRange(min_val, max_val)
        spin.setMinimumWidth(scaled_px(60))
        spin.valueChanged.connect(self._on_spin_changed)
        return lbl, spin

    def _on_mode_changed(self, checked):
        self._hsv_group.setVisible(self._hsv_mode.isChecked())
        self._rgb_group.setVisible(self._rgb_mode.isChecked())

    def _on_wheel_changed(self, color: QColor):
        if self._updating:
            return
        self._color = color
        self._brightness.set_hsv(color.hueF(), color.saturationF())
        self._update_displays()

    def _on_brightness_changed(self, value: float):
        if self._updating:
            return
        self._wheel.set_value(value)
        self._color = self._wheel.get_color()
        self._update_displays()

    def _on_spin_changed(self, _):
        if self._updating:
            return
        if self._hsv_mode.isChecked():
            h = self._h_spin[1].value()
            s = self._s_spin[1].value() / 100.0
            v = self._v_spin[1].value() / 100.0
            self._color = QColor.fromHsvF(h / 360.0, s, v)
        else:
            r = self._r_spin[1].value()
            g = self._g_spin[1].value()
            b = self._b_spin[1].value()
            self._color = QColor.fromRgb(r, g, b)
        self._update_from_color(self._color)

    def _on_hex_changed(self):
        text = self._hex_input.text().strip()
        if not text.startswith("#"):
            text = "#" + text
        color = QColor(text)
        if color.isValid():
            self._color = color
            self._update_from_color(color)

    def _update_from_color(self, color: QColor):
        self._updating = True
        self._wheel.set_color(color)
        self._brightness.set_hsv(color.hueF(), color.saturationF())
        self._brightness.set_value(color.valueF())
        self._update_displays()
        self._updating = False

    def _update_displays(self):
        self._updating = True
        # HSV
        self._h_spin[1].setValue(int(self._color.hueF() * 360))
        self._s_spin[1].setValue(int(self._color.saturationF() * 100))
        self._v_spin[1].setValue(int(self._color.valueF() * 100))
        # RGB
        self._r_spin[1].setValue(self._color.red())
        self._g_spin[1].setValue(self._color.green())
        self._b_spin[1].setValue(self._color.blue())
        # HEX
        self._hex_input.setText(self._color.name())
        # Preview
        self._preview.setStyleSheet(
            f"background: {self._color.name()}; border: 1px solid #555; border-radius: 4px;"
        )
        self._updating = False

    def _on_ok(self):
        self.color_selected.emit(self._color)
        self.accept()

    def get_color(self) -> QColor:
        return self._color
