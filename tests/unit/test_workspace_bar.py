import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from AssetsManager.widgets.workspace_bar import WorkspaceBar


def test_adding_a_library_emits_one_switch_per_new_tab(tmp_path):
    app = QApplication.instance() or QApplication([])
    bar = WorkspaceBar()
    switched = []
    bar.library_switched.connect(switched.append)

    first = str(tmp_path / "first")
    second = str(tmp_path / "second")
    bar.add_library(first)
    bar.add_library(second)

    assert switched == [first, second]
    bar.deleteLater()
    app.processEvents()


def test_adding_equivalent_library_path_reuses_existing_tab(tmp_path):
    app = QApplication.instance() or QApplication([])
    library = tmp_path / "library"
    library.mkdir()
    bar = WorkspaceBar()
    switched = []
    bar.library_switched.connect(switched.append)

    bar.add_library(str(library))
    bar.add_library(str(library / "."))

    assert bar.count() == 1
    assert switched == [str(library.resolve())]
    bar.deleteLater()
    app.processEvents()


def test_closing_inactive_tab_does_not_switch_library(tmp_path):
    app = QApplication.instance() or QApplication([])
    bar = WorkspaceBar()
    first = str(tmp_path / "first")
    second = str(tmp_path / "second")
    bar.add_library(first)
    bar.add_library(second)
    switched = []
    bar.library_switched.connect(switched.append)

    bar._on_close(0)

    assert bar.current_library() == second
    assert switched == []
    bar.deleteLater()
    app.processEvents()


def test_closing_inactive_tab_preserves_qt_current_changed_signal(tmp_path):
    app = QApplication.instance() or QApplication([])
    bar = WorkspaceBar()
    first = str(tmp_path / "first")
    second = str(tmp_path / "second")
    bar.add_library(first)
    bar.add_library(second)
    changes = []
    bar.currentChanged.connect(changes.append)

    bar._on_close(0)

    assert changes == [0]
    bar.deleteLater()
    app.processEvents()


def test_closing_active_tab_switches_once_to_remaining_tab(tmp_path):
    app = QApplication.instance() or QApplication([])
    bar = WorkspaceBar()
    first = str(tmp_path / "first")
    second = str(tmp_path / "second")
    bar.add_library(first)
    bar.add_library(second)
    switched = []
    bar.library_switched.connect(switched.append)

    bar._on_close(1)

    assert bar.current_library() == first
    assert switched == [first]
    bar.deleteLater()
    app.processEvents()


def test_close_others_emits_only_final_library_switch(tmp_path):
    app = QApplication.instance() or QApplication([])
    bar = WorkspaceBar()
    first = str(tmp_path / "first")
    second = str(tmp_path / "second")
    third = str(tmp_path / "third")
    bar.add_library(first)
    bar.add_library(second)
    bar.add_library(third)
    bar.setCurrentIndex(0)
    switched = []
    bar.library_switched.connect(switched.append)

    bar._close_others(2)

    assert bar.tab_paths() == [third]
    assert bar.current_library() == third
    assert switched == [third]
    bar.deleteLater()
    app.processEvents()
