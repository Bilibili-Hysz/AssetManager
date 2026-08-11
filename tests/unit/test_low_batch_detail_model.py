"""Low-priority regression tests: DetailModel sort/tags, GridLayout, batch rename.

Covers fix-group C defects:
  A2  — sort() remaps persistent indexes (selection must not jump).
  A6  — _do_sort keeps directories on top in both ascending and descending.
  B1  — GridLayout survives a zero-sized item_hint (no division by zero).
  C1  — _name_errors rejects path separators on every platform; a pattern
        containing "/" no longer crashes plan_batch_rename on non-Windows.
  C2  — unresolvable occupied paths are skipped instead of raising.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

from PySide6.QtCore import QPersistentModelIndex, QSize, Qt
from PySide6.QtWidgets import QApplication

from AssetsManager.panels.file_list._batch_rename import _name_errors, plan_batch_rename
from AssetsManager.panels.file_list._detail_model import DetailModel, _natural_key
from AssetsManager.panels.file_list._grid_layout import GridLayout

_app = QApplication.instance() or QApplication([])


def _entry(name: str, is_dir: bool):
    return SimpleNamespace(name=name, path=f"/synthetic/{name}", is_dir=lambda: is_dir)


def _make_model(entries, fs=None):
    model = DetailModel()
    model._fs_model = fs  # None → sort value helpers fall back to 0
    model._store = None
    model._lib_root = None
    model._tags_cache = {}
    model._entries = list(entries)
    return model


# ── A6: directories always on top ─────────────────────────────────

def test_do_sort_keeps_directories_on_top_ascending():
    model = _make_model([
        _entry("file_a.txt", False),
        _entry("dir_z", True),
        _entry("file_b.txt", False),
        _entry("dir_a", True),
    ])
    model._do_sort(0, Qt.SortOrder.AscendingOrder)
    names = [entry.name for entry in model._entries]
    assert names == ["dir_a", "dir_z", "file_a.txt", "file_b.txt"]


def test_do_sort_keeps_directories_on_top_descending():
    model = _make_model([
        _entry("file_a.txt", False),
        _entry("dir_z", True),
        _entry("file_b.txt", False),
        _entry("dir_a", True),
    ])
    model._do_sort(0, Qt.SortOrder.DescendingOrder)
    names = [entry.name for entry in model._entries]
    # Directories stay first even when the group order is reversed.
    assert names == ["dir_z", "dir_a", "file_b.txt", "file_a.txt"]


def test_do_sort_size_and_date_columns_keep_directories_on_top():
    model = _make_model([
        _entry("file_a.txt", False),
        _entry("dir_z", True),
        _entry("file_b.txt", False),
    ])
    for column in (2, 3, 4):  # size / date / tags — fs is None, values fall back to 0
        for order in (Qt.SortOrder.AscendingOrder, Qt.SortOrder.DescendingOrder):
            model._do_sort(column, order)
            dirs = [i for i, e in enumerate(model._entries) if e.is_dir()]
            files = [i for i, e in enumerate(model._entries) if not e.is_dir()]
            assert dirs and max(dirs) < min(files), f"column {column} order {order}"


# ── Natural sort key ──────────────────────────────────────────────

def test_natural_key_orders_file2_before_file10():
    assert _natural_key("file2") < _natural_key("file10")
    names = sorted(["file10", "file2", "file1", "file11"], key=_natural_key)
    assert names == ["file1", "file2", "file10", "file11"]


# ── B1: GridLayout zero-dimension protection ──────────────────────

def test_grid_layout_zero_item_hint_does_not_divide_by_zero():
    layout = GridLayout()
    # compute() with a QSize(0, 0) hint used to raise ZeroDivisionError.
    assert layout.compute(10, 800, item_hint=QSize(0, 0)) is True
    assert layout.columns >= 1
    assert layout.rect_at(0) is not None
    # hit-testing helpers must stay safe too (item_h=1 → whole grid visible).
    assert layout.row_at(0, 0) == -1
    assert layout.visible_rows(0, 100) == list(range(10))
    # before any compute() the dimensions are zero — still no crash.
    assert GridLayout().row_at(50, 50) == -1
    assert GridLayout().visible_rows(0, 100) == []


# ── C1: separators rejected on all platforms ──────────────────────

def test_name_errors_rejects_separators_on_all_platforms():
    assert "invalid_name" in _name_errors("a/b", windows_rules=False)
    assert "invalid_name" in _name_errors("a\\b", windows_rules=False)
    assert "invalid_name" in _name_errors("a/b", windows_rules=True)
    # Non-separator names stay valid on non-Windows.
    assert _name_errors("ok-name.txt", windows_rules=False) == ()
    # Windows-only checks are unchanged.
    assert _name_errors("CON", windows_rules=True) == ("reserved_name",)


def test_plan_with_separator_pattern_does_not_crash(tmp_path):
    plan = plan_batch_rename(
        [tmp_path / "a.txt"],
        "sub/name",
        occupied_paths=[],
        windows_rules=False,
    )
    assert "invalid_name" in plan.errors
    assert not plan.is_valid
    # Placeholder target keeps the entry flagged instead of raising.
    assert not plan.entries[0].changed


def test_plan_skips_unresolvable_occupied_path(tmp_path):
    # A NUL byte makes the path unresolvable; the occupied collection must
    # skip it instead of raising.
    plan = plan_batch_rename(
        [tmp_path / "a.txt"],
        "renamed",
        occupied_paths=["\x00unresolvable"],
        windows_rules=False,
    )
    assert plan.is_valid
    assert plan.entries[0].target.name == "renamed.txt"


# ── A2: sort() remaps persistent indexes ──────────────────────────

def test_sort_remaps_persistent_indexes_to_same_entries():
    # fs must be truthy so data() serves UserRole (entry.path) lookups.
    model = _make_model([
        _entry("zeta.txt", False),
        _entry("alpha.txt", False),
        _entry("dir_mid", True),
    ], fs=object())
    original_paths = [entry.path for entry in model._entries]
    persistent = [QPersistentModelIndex(model.index(row, 0)) for row in range(len(model._entries))]
    assert all(index.isValid() for index in persistent)

    model.sort(0, Qt.SortOrder.AscendingOrder)

    # Each persistent index must still point at the entry it was created
    # for — without changePersistentIndexList the row-based indexes would
    # have followed the reordered rows instead.
    after = [model.data(index, Qt.ItemDataRole.UserRole) for index in persistent]
    assert after == original_paths
    assert all(index.isValid() for index in persistent)
    # Model rows are actually sorted (dirs on top, natural order inside).
    assert [entry.name for entry in model._entries] == ["dir_mid", "alpha.txt", "zeta.txt"]
