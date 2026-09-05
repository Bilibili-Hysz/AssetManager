"""D6: TabbedDialog language/ui-scale live refresh is the DEFAULT contract.

Locks the dialect-unification P2 flip (2026-09-04): an open dialog must
re-derive its chrome text when the language changes, without being rebuilt,
and opt-outs must be explicit class-level declarations with a reason.
"""
from PySide6.QtWidgets import QApplication, QDialogButtonBox

import pytest

from AssetsManager.core import signal_bus
from AssetsManager.dialogs import tabbed_dialog
from AssetsManager.dialogs.modal_dialog import StandardModalDialog
from AssetsManager.dialogs.tabbed_dialog import TabbedDialog


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _BareDialog(TabbedDialog):
    """No overrides: the default contract must cover it out of the box."""

    def _build_ui(self):
        pass


class _ModalDialog(StandardModalDialog):
    def setup_content(self, layout):
        pass


def test_default_supports_runtime_refresh_is_true():
    assert TabbedDialog.supports_runtime_refresh is True
    assert _BareDialog.supports_runtime_refresh is True
    # The base no-op retranslate stays overridable.
    assert TabbedDialog.retranslate_ui(_BareDialog.__new__(_BareDialog)) is None


def test_language_changed_refreshes_button_box(qapp, monkeypatch):
    dialog = _BareDialog.__new__(_BareDialog)
    TabbedDialog.__init__(dialog, title="t", min_size=(120, 100))
    dialog._setup_tabbed_ui()
    monkeypatch.setattr(tabbed_dialog, "tr", lambda key, **kw: f"[{key}]")
    dialog._on_language_changed("zh")
    ok = dialog._button_box.button(QDialogButtonBox.StandardButton.Ok)
    cancel = dialog._button_box.button(QDialogButtonBox.StandardButton.Cancel)
    assert ok.text() == "[dialog.ok]"
    assert cancel.text() == "[dialog.cancel]"


def test_language_changed_refreshes_modal_button_row(qapp, monkeypatch):
    dialog = _ModalDialog(title="t")
    dialog.show()
    monkeypatch.setattr(tabbed_dialog, "tr", lambda key, **kw: f"[{key}]")
    dialog._on_language_changed("zh")
    assert dialog._ok_btn.text() == "[dialog.ok]"
    assert dialog._cancel_btn.text() == "[dialog.cancel]"
    assert dialog.windowTitle() == "t"
    dialog.close()


def test_refresh_bus_wiring_follows_the_flag(qapp):
    """A shown dialog connects the refresh signals; dismissal disconnects."""
    dialog = _BareDialog.__new__(_BareDialog)
    TabbedDialog.__init__(dialog, title="t", min_size=(120, 100))
    dialog.show()
    assert dialog._refresh_bus_connected is True
    dialog.close()
    assert dialog._refresh_bus_connected is False


def test_signal_bus_emits_language_change(qapp, monkeypatch):
    """The dialog refresh path is driven by the process signal bus."""
    bus = signal_bus.get()
    dialog = _BareDialog.__new__(_BareDialog)
    TabbedDialog.__init__(dialog, title="t", min_size=(120, 100))
    dialog.show()
    calls: list[str] = []
    monkeypatch.setattr(dialog, "retranslate_ui", lambda: calls.append("re"))
    bus.language_changed.emit("zh")
    dialog.close()
    assert calls == ["re"]
