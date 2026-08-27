import os
import warnings

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
from pathlib import Path

from PySide6.QtWidgets import QApplication

from AssetsManager.dialogs.startup import StartupWindow, _LibraryCard


class _Settings:
    def __init__(self, paths):
        self._paths = paths

    def load(self):
        pass

    def get_list(self, key, default):
        return self._paths if key == "recent_libraries" else default


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
