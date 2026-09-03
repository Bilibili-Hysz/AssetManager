"""Collect CommandOperator params from a small modal form."""
from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from AssetsManager.plugin_api.types import CommandOperator
from AssetsManager.dialogs.modal_dialog import StandardModalDialog


class _OperatorParamsDialog(StandardModalDialog):
    """Single-page modal form generated from a CommandOperator param schema."""

    def __init__(self, operator_cls: type[CommandOperator],
                 defaults: dict[str, Any], parent: QWidget | None = None):
        self._schema = operator_cls.params or {}
        self._defaults = defaults
        super().__init__(
            parent,
            title=str(operator_cls.title or operator_cls.id or "Plugin"),
        )

    def setup_content(self, layout: QVBoxLayout) -> None:
        form = QFormLayout()
        self._editors: dict[str, QWidget] = {}
        for key, spec in self._schema.items():
            if not isinstance(spec, dict):
                continue
            kind = str(spec.get("type") or "str")
            label = str(spec.get("label") or key)
            value = self._defaults.get(key, spec.get("default"))
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
            self._editors[str(key)] = widget
            form.addRow(label, widget)
        layout.addLayout(form)

    def collect_values(self) -> dict[str, Any]:
        values = dict(self._defaults)
        for key, widget in self._editors.items():
            if isinstance(widget, QCheckBox):
                values[key] = widget.isChecked()
            elif isinstance(widget, QSpinBox):
                values[key] = int(widget.value())
            elif isinstance(widget, QLineEdit):
                values[key] = widget.text()
        return values


def prompt_operator_params(
    operator_cls: type[CommandOperator],
    defaults: dict[str, Any],
    parent: QWidget | None = None,
) -> dict[str, Any] | None:
    schema = operator_cls.params or {}
    if not schema:
        return dict(defaults)

    dialog = _OperatorParamsDialog(operator_cls, defaults, parent=parent)
    if dialog.exec() != dialog.DialogCode.Accepted:
        return None
    return dialog.collect_values()
