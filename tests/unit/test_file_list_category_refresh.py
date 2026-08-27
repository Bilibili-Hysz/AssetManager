"""Focused Qt coverage for live file-list filter category refreshes."""

import os
from threading import Event, Thread
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from AssetsManager.application.asset_filters import (
    FILTER_CATEGORIES,
    FILTER_CATEGORY_EXTS,
    category_registry_snapshot,
    normalize_filter_category,
    subscribe_category_registry_changed,
)
from AssetsManager.core.format_utils import CATEGORY_MAP, _BUILTIN_CATEGORY_MAP
from AssetsManager.panels.file_list._base import FileListPanel


@pytest.fixture
def qt_app():
    app = QApplication.instance() or QApplication([])
    return app


def _rebuild(contributions):
    FILTER_CATEGORY_EXTS.rebuild(
        contributions,
        CATEGORY_MAP,
        _BUILTIN_CATEGORY_MAP,
    )


def test_open_file_list_refreshes_new_category_and_preserves_unchanged_selection(qt_app):
    panel = FileListPanel()
    try:
        _rebuild([("cad", "CAD Files", {".dwg"}, "cad-plugin")])
        qt_app.processEvents()
        assert panel._filter_combo.findData("cad") >= 0
        assert panel._filter_combo.itemText(panel._filter_combo.findData("cad")) == "CAD Files"

        panel._filter_combo.setCurrentIndex(panel._filter_combo.findData("cad"))
        assert panel._filter_combo.currentData() == "cad"

        _rebuild([("cad", "CAD Drawings", {".dwg"}, "cad-plugin")])
        qt_app.processEvents()

        assert panel._filter_combo.currentData() == "cad"
        assert panel._model._filter_cat == "cad"
        assert panel._filter_combo.currentText() == "CAD Drawings"
    finally:
        panel.shutdown()
        panel.deleteLater()
        _rebuild([])
        qt_app.processEvents()


def test_retained_category_membership_change_reapplies_open_file_list_filter(qt_app, monkeypatch):
    panel = FileListPanel()
    try:
        _rebuild([("cad", "CAD Files", {".dwg"}, "cad-plugin")])
        qt_app.processEvents()
        panel._filter_combo.setCurrentIndex(panel._filter_combo.findData("cad"))
        set_filter = Mock(wraps=panel._model.set_filter)
        monkeypatch.setattr(panel._model, "set_filter", set_filter)

        _rebuild([("cad", "CAD Files", {".dxf"}, "cad-plugin")])
        qt_app.processEvents()

        assert panel._filter_combo.currentData() == "cad"
        assert panel._model._filter_cat == "cad"
        assert set_filter.call_args.kwargs == {
            "text": panel._search.text().lower(), "category": "cad",
        }
    finally:
        panel.shutdown()
        panel.deleteLater()
        _rebuild([])
        qt_app.processEvents()


def test_unloading_selected_category_resets_open_file_list_to_all(qt_app):
    panel = FileListPanel()
    try:
        _rebuild([("cad", "CAD Files", {".dwg"}, "cad-plugin")])
        qt_app.processEvents()
        panel._filter_combo.setCurrentIndex(panel._filter_combo.findData("cad"))
        assert panel._model._filter_cat == "cad"

        _rebuild([])
        qt_app.processEvents()

        assert panel._filter_combo.findData("cad") == -1
        assert panel._filter_combo.currentData() == "all"
        assert panel._model._filter_cat == "all"
    finally:
        panel.shutdown()
        panel.deleteLater()
        _rebuild([])
        qt_app.processEvents()


def test_category_subscription_closes_once_before_panel_shutdown(qt_app):
    panel = FileListPanel()
    try:
        subscription = panel._category_registry_subscription
        assert subscription is not None
        panel.shutdown()
        assert subscription._closed is True
        assert panel._category_registry_subscription is None
        panel.shutdown()
    finally:
        panel.deleteLater()
        qt_app.processEvents()


def test_category_registry_notification_is_application_only_and_unsubscribable():
    calls = []
    subscription = subscribe_category_registry_changed(lambda: calls.append("changed"))
    try:
        _rebuild([("cad", "CAD Files", {".dwg"}, "cad-plugin")])
        assert calls == ["changed"]
        subscription.close()
        _rebuild([])
        assert calls == ["changed"]
    finally:
        subscription.close()
        _rebuild([])


def test_queued_category_refresh_is_ignored_after_panel_shutdown(qt_app, monkeypatch):
    panel = FileListPanel()
    try:
        refresh = Mock()
        monkeypatch.setattr(panel._model, "set_filter", refresh)
        _rebuild([("cad", "CAD Files", {".dwg"}, "cad-plugin")])
        panel.shutdown()
        FileListPanel._on_category_registry_changed(panel)
        qt_app.processEvents()

        refresh.assert_not_called()
    finally:
        panel.deleteLater()
        _rebuild([])
        qt_app.processEvents()


def test_duplicate_plugin_labels_are_rejected_without_corrupting_legacy_lookup():
    try:
        _rebuild([
            ("cad", "Design Files", {".dwg"}, "cad-plugin"),
            ("vector", "Design Files", {".svgx"}, "vector-plugin"),
        ])

        assert normalize_filter_category("cad") == "cad"
        assert normalize_filter_category("Design Files") == "cad"
        assert FILTER_CATEGORIES["Design Files"] == frozenset({".dwg"})
        assert "vector" not in FILTER_CATEGORY_EXTS
    finally:
        _rebuild([])


def test_plugin_label_conflicting_with_builtin_is_rejected():
    try:
        _rebuild([("cad", "Images", {".dwg"}, "cad-plugin")])

        assert "cad" not in FILTER_CATEGORY_EXTS
        assert normalize_filter_category("Images") == "images"
        assert FILTER_CATEGORIES["Images"] == FILTER_CATEGORY_EXTS["images"]
    finally:
        _rebuild([])


def test_registered_unique_label_normalizes_to_its_canonical_key():
    try:
        _rebuild([("cad", "CAD Files", {".dwg"}, "cad-plugin")])

        assert normalize_filter_category("CAD Files") == "cad"
    finally:
        _rebuild([])


def test_concurrent_rebuild_category_map_reads_are_single_generation_snapshots():
    old_generation = {".gen_a": "old", ".gen_b": "old"}
    new_generation = {".gen_a": "new", ".gen_b": "new"}
    start = Event()
    mixed_generations = []

    def rebuild_loop():
        start.wait()
        for _index in range(100):
            _rebuild([("old", "Old Files", set(old_generation), "old-plugin")])
            _rebuild([("new", "New Files", set(new_generation), "new-plugin")])

    thread = Thread(target=rebuild_loop)
    thread.start()
    start.set()
    try:
        while thread.is_alive():
            snapshot = CATEGORY_MAP.snapshot()
            observed = (snapshot.get(".gen_a"), snapshot.get(".gen_b"))
            if observed not in {("old", "old"), ("new", "new"), (None, None)}:
                mixed_generations.append(observed)
        thread.join()
        assert mixed_generations == []
    finally:
        thread.join()
        _rebuild([])


def test_concurrent_rebuild_never_exposes_an_empty_category_map():
    start = Event()
    observed_empty = []

    def rebuild_loop():
        start.wait()
        for index in range(50):
            _rebuild([(
                "cad",
                f"CAD Files {index}",
                {f".cad{index}"},
                "cad-plugin",
            )])

    thread = Thread(target=rebuild_loop)
    thread.start()
    start.set()
    try:
        while thread.is_alive():
            if not CATEGORY_MAP:
                observed_empty.append(True)
        thread.join()
        assert observed_empty == []
    finally:
        thread.join()
        _rebuild([])


def test_concurrent_rebuilds_publish_consistent_category_label_snapshots():
    start = Event()
    errors = []

    def rebuild_loop():
        start.wait()
        for index in range(50):
            _rebuild([(
                "cad",
                f"CAD Files {index}",
                {f".cad{index}"},
                "cad-plugin",
            )])

    thread = Thread(target=rebuild_loop)
    thread.start()
    start.set()
    try:
        while thread.is_alive():
            categories, labels = category_registry_snapshot()
            for key, _label in labels:
                if key not in categories:
                    errors.append((categories, labels))
                    break
        thread.join()
        assert errors == []
    finally:
        thread.join()
        _rebuild([])
