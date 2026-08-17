"""Collect CommandOperator params from a small modal form."""
from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from AssetsManager.core import themes
from AssetsManager.plugin_api.types import CommandOperator


def prompt_operator_params(
    operator_cls: type[CommandOperator],
    defaults: dict[str, Any],
    parent: QWidget | None = None,
) -> dict[str, Any] | None:
    schema = operator_cls.params or {}
    if not schema:
        return dict(defaults)

    dialog = QDialog(parent)
    dialog.setWindowTitle(str(operator_cls.title or operator_cls.id or "Plugin"))
    themes.apply_to(dialog)
    layout = QVBoxLayout(dialog)
    form = QFormLayout()
    editors: dict[str, QWidget] = {}
    for key, spec in schema.items():
        if not isinstance(spec, dict):
            continue
        kind = str(spec.get("type") or "str")
        label = str(spec.get("label") or key)
        value = defaults.get(key, spec.get("default"))
        if kind == "bool":
            widget = QCheckBox()
            widget.setChecked(bool(value))
        elif kind in {"int", "number"}:
            widget = QSpinBox()
            widget.setRange(int(spec.get("min", -1_000_000)), int(spec.get("max", 1_000_000)))
            widget.setValue(int(value or 0))
        else:
            widget = QLineEdit()
            widget.setText("" if value is None else str(value))
            if spec.get("secret"):
                widget.setEchoMode(QLineEdit.EchoMode.Password)
        editors[str(key)] = widget
        form.addRow(label, widget)
    layout.addLayout(form)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    values = dict(defaults)
    for key, widget in editors.items():
        if isinstance(widget, QCheckBox):
            values[key] = widget.isChecked()
        elif isinstance(widget, QSpinBox):
            values[key] = int(widget.value())
        elif isinstance(widget, QLineEdit):
            values[key] = widget.text()
    return values
