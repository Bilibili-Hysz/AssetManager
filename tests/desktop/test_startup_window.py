import warnings


import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from AssetsManager.dialogs.startup import StartupWindow, _LibraryCard


class _Settings:
    def __init__(self, paths):
        self._paths = paths

    def load(self):
        pass

    def get_list(self, key, default):
        return self._paths if key == "recent_libraries" else default

    def prepend_list(self, key, value, max_items=None):
        if key == "recent_libraries":
            self._paths = [value] + [p for p in self._paths if p != value]
            if max_items:
                self._paths = self._paths[:max_items]

    def save(self):
        pass


def _make_startup_window(monkeypatch, paths):
    monkeypatch.setattr(
        "AssetsManager.dialogs.startup.AppSettings.instance",
        classmethod(lambda _cls: _Settings(paths)),
    )
    # Keep the open path hermetic: record_visit touches the real settings.
    monkeypatch.setattr(
        "AssetsManager.core.library_manager.record_visit",
        lambda _path: "",
    )
    return StartupWindow()


def test_startup_keeps_truncation_indicator_out_of_library_cards(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    paths = [str(tmp_path / f"library-{index}") for index in range(31)]
    monkeypatch.setattr(
        "AssetsManager.dialogs.startup.AppSettings.instance",
        classmethod(lambda _cls: _Settings(paths)),
    )
    window = StartupWindow()
    try:
        assert len(window._cards) == 30
        assert all(isinstance(card, _LibraryCard) for card in window._cards)
        assert window._truncation_indicator is not None
        window._on_card_clicked(paths[0])
    finally:
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            window.close()
            window.deleteLater()
            app.processEvents()


_RESTORE_MARKER_KEYS = frozenset(
    {
        "restore_marker.open_failed_title",
        "restore_marker.title",
        "restore_marker.body",
        "restore_marker.retry_button",
        "restore_marker.ack_button",
        "restore_marker.failed_title",
    }
)


def test_i18n_json_key_sets_match_and_include_restore_marker():
    """Pure-JSON assertion (no Qt): all locale files share one key set."""
    i18n_dir = Path(__file__).resolve().parents[2] / "AssetsManager" / "i18n"
    data = {}
    for code in ("en", "zh", "ja"):
        data[code] = json.loads(
            (i18n_dir / f"{code}.json").read_text(encoding="utf-8")
        )
    key_sets = {
        code: set(payload) - {"_meta"} for code, payload in data.items()
    }
    assert key_sets["en"] == key_sets["zh"] == key_sets["ja"]
    assert _RESTORE_MARKER_KEYS <= key_sets["en"]


_LIBRARY_CARD_KEYS = frozenset(
    {
        "library.switch_failed",
        "library.switch_failed_retry_hint",
    }
)


def test_i18n_includes_library_switch_failure_keys():
    """The lifecycle switch-failure message is present in all locales."""
    i18n_dir = Path(__file__).resolve().parents[2] / "AssetsManager" / "i18n"
    for code in ("en", "zh", "ja"):
        payload = json.loads((i18n_dir / f"{code}.json").read_text(encoding="utf-8"))
        for key in _LIBRARY_CARD_KEYS:
            assert key in payload
        assert "{reason}" in payload["library.switch_failed"]


def test_startup_focuses_first_card_and_tab_reaches_cards(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    paths = [str(tmp_path / f"library-{index}") for index in range(2)]
    for p in paths:
        Path(p).mkdir()
    window = _make_startup_window(monkeypatch, paths)
    window.show()
    app.processEvents()
    try:
        assert all(c.focusPolicy() == Qt.FocusPolicy.StrongFocus for c in window._cards)
        # Default focus lands on the first (selected) card after show.
        assert window.focusWidget() is window._cards[0]
        # Tab walks the card list.
        QTest.keyClick(window._cards[0], Qt.Key.Key_Tab)
        app.processEvents()
        assert window.focusWidget() is window._cards[1]
        # Focusing a card via keyboard selects it (detail panel follows).
        assert window._selected_path == paths[1]
    finally:
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            window.close()
            window.deleteLater()
            app.processEvents()


def test_startup_card_enter_and_space_open_library(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    lib = tmp_path / "keyboard-lib"
    lib.mkdir()
    for key in (Qt.Key.Key_Return, Qt.Key.Key_Space):
        opened = []
        window = _make_startup_window(monkeypatch, [str(lib)])
        window.library_opened.connect(opened.append)
        window.show()
        app.processEvents()
        try:
            assert window.focusWidget() is window._cards[0]
            QTest.keyClick(window.focusWidget(), key)
            app.processEvents()
            assert opened == [str(lib)]
        finally:
            with warnings.catch_warnings():
                warnings.simplefilter("error", RuntimeWarning)
                window.close()
                window.deleteLater()
                app.processEvents()


class _QuestionStub:
    """QMessageBox replacement recording question() and returning an answer."""

    StandardButton = QMessageBox.StandardButton

    def __init__(self):
        self.calls = []
        self.answer = QMessageBox.StandardButton.Yes

    def question(self, parent, title, body, buttons=None, default=None):
        self.calls.append((title, body))
        return self.answer


def test_startup_first_run_shows_new_and_open_cards(monkeypatch, tmp_path):
    """No recent libraries: two equal-weight action cards, no library cards."""
    app = QApplication.instance() or QApplication([])
    window = _make_startup_window(monkeypatch, [])
    window.show()
    app.processEvents()
    try:
        assert window._cards == []
        assert window._empty_state.isVisible()
        assert window._new_library_card.isVisible()
        assert window._open_existing_card.isVisible()
        # Keyboard focus lands on the new-library card after show().
        assert window.focusWidget() is window._new_library_card
    finally:
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            window.close()
            window.deleteLater()
            app.processEvents()


def test_startup_with_recent_libraries_keeps_old_layout(monkeypatch, tmp_path):
    """With history the classic recent-card layout is unchanged and the
    first-run empty state stays hidden."""
    app = QApplication.instance() or QApplication([])
    lib = tmp_path / "existing-lib"
    lib.mkdir()
    window = _make_startup_window(monkeypatch, [str(lib)])
    window.show()
    app.processEvents()
    try:
        assert len(window._cards) == 1
        assert not window._empty_state.isVisible()
    finally:
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            window.close()
            window.deleteLater()
            app.processEvents()


def test_startup_new_library_empty_folder_emits_opened(monkeypatch, tmp_path):
    """First-run new-library card: empty folder is adopted without prompt."""
    app = QApplication.instance() or QApplication([])
    fresh = tmp_path / "fresh-library"
    fresh.mkdir()
    monkeypatch.setattr(
        "AssetsManager.dialogs.startup.QFileDialog.getExistingDirectory",
        staticmethod(lambda *args, **kwargs: str(fresh)),
    )
    opened = []
    window = _make_startup_window(monkeypatch, [])
    window.library_opened.connect(opened.append)
    try:
        window._new_library_card.activated.emit()
        app.processEvents()
        assert opened == [str(fresh)]
        assert window._settings._paths == [str(fresh)]
        # Window closes after adopting the folder.
        assert not window.isVisible()
    finally:
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            window.close()
            window.deleteLater()
            app.processEvents()


def test_startup_new_library_non_empty_folder_asks_confirmation(
    monkeypatch, tmp_path
):
    """Non-empty folder: No aborts, Yes adopts and emits library_opened."""
    app = QApplication.instance() or QApplication([])
    existing = tmp_path / "stuffed-library"
    existing.mkdir()
    (existing / "asset.png").write_bytes(b"x")
    monkeypatch.setattr(
        "AssetsManager.dialogs.startup.QFileDialog.getExistingDirectory",
        staticmethod(lambda *args, **kwargs: str(existing)),
    )
    stub = _QuestionStub()
    monkeypatch.setattr(
        "AssetsManager.dialogs.startup.QMessageBox", stub)

    opened = []
    window = _make_startup_window(monkeypatch, [])
    window.library_opened.connect(opened.append)
    try:
        stub.answer = QMessageBox.StandardButton.No
        window._new_library_card.activated.emit()
        app.processEvents()
        assert opened == []
        assert window._settings._paths == []
        assert len(stub.calls) == 1

        stub.answer = QMessageBox.StandardButton.Yes
        window._new_library_card.activated.emit()
        app.processEvents()
        assert opened == [str(existing)]
        assert window._settings._paths == [str(existing)]
    finally:
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            window.close()
            window.deleteLater()
            app.processEvents()


def test_startup_new_library_cancelled_dialog_is_noop(monkeypatch, tmp_path):
    """Cancelling the folder dialog must not touch history or emit."""
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(
        "AssetsManager.dialogs.startup.QFileDialog.getExistingDirectory",
        staticmethod(lambda *args, **kwargs: ""),
    )
    opened = []
    window = _make_startup_window(monkeypatch, [])
    window.library_opened.connect(opened.append)
    try:
        window._new_library_card.activated.emit()
        app.processEvents()
        assert opened == []
        assert window._settings._paths == []
    finally:
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            window.close()
            window.deleteLater()
            app.processEvents()
