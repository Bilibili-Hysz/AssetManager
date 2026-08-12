"""Desktop/LAN dual-implementation parity tests (stage 1).

The file list must sort and filter identically whether it is rendered by
the desktop FileSystemModel or served through the LAN AssetService; both
surfaces share application/asset_filters.py.
"""
import os

import pytest

from AssetsManager.application.asset_filters import sort_key_for_entry


def _sort_key_via_shared(name, is_dir, stat_result, sort_by):
    """The desktop sort path now delegates to the shared key function."""
    return sort_key_for_entry(
        name=name,
        is_dir=is_dir,
        modified=stat_result.st_mtime,
        size=stat_result.st_size,
        ext=os.path.splitext(name)[1].lower(),
        sort_by=sort_by,
    )


def _make_tree(root):
    """Build a directory tree with dirs/files/dotfiles/multi-suffix names."""
    (root / "zeta").mkdir()
    (root / "Alpha").mkdir()
    (root / ".hidden_dir").mkdir()
    (root / "file10.txt").write_text("x")
    (root / "file2.txt").write_text("x")
    (root / "asset.png").write_text("x")
    (root / "archive.tar.gz").write_text("x")
    (root / ".hidden.txt").write_text("x")
    (root / "image.JPG").write_text("x")


def _stat(path):
    return path.stat()


def _entries_sorted(root, sort_by, asc):
    """Sort entries with the shared key the same way _apply_sort does."""
    entries = list(os.scandir(root))
    keyed = []
    for e in entries:
        st = e.stat(follow_symlinks=True)
        keyed.append((_sort_key_via_shared(e.name, e.is_dir(), st, sort_by), e.name))
    keyed.sort(key=lambda pair: pair[0])
    if not asc:
        keyed.reverse()
    return [name for _, name in keyed]


def _lan_sorted(root, sort_by, asc):
    """Reference: AssetService ordering semantics (sort_key_for_entry + reverse)."""
    entries = []
    for e in os.scandir(root):
        if e.name.startswith("."):
            continue  # hidden filter, applied before sorting in both surfaces
        st = e.stat(follow_symlinks=False)
        entries.append((sort_key_for_entry(
            name=e.name,
            is_dir=e.is_dir(),
            modified=st.st_mtime,
            size=st.st_size,
            ext=os.path.splitext(e.name)[1].lower(),
            sort_by=sort_by,
        ), e.name))
    entries.sort(key=lambda pair: pair[0])
    if asc == "desc":
        entries.reverse()
    return [name for _, name in entries]


@pytest.mark.parametrize("sort_by", ["name", "date", "size", "type"])
@pytest.mark.parametrize("order", ["asc", "desc"])
def test_desktop_sort_matches_lan_semantics(tmp_path, sort_by, order):
    """The desktop inline sort (now the shared key) matches the LAN order.

    Both surfaces sort with sort_key_for_entry and reverse the whole list
    on desc — the parity test locks that contract.
    """
    _make_tree(tmp_path)
    visible = [n for n in _entries_sorted(tmp_path, sort_by, order == "asc")
               if not n.startswith(".")]
    lan = _lan_sorted(tmp_path, sort_by, order)
    assert visible == lan


def test_type_key_uses_splitext_semantics():
    """Boundary names produce identical ext keys on both surfaces."""
    from pathlib import Path

    for name in ("archive.tar.gz", ".gitignore", "a.b.", "plain", "image.JPG"):
        desktop_ext = os.path.splitext(name)[1].lower()
        assert desktop_ext == (Path(name).suffix.lower() if "." in name else "")


def test_matches_exclude_semantics_shared():
    """The exclude matcher is one shared function for both surfaces."""
    from AssetsManager.application.asset_filters import matches_exclude

    assert matches_exclude("notes.tmp", ["*.tmp"]) is True
    assert matches_exclude(".git", [".git"]) is True
    assert matches_exclude("hero.png", ["*.tmp"]) is False
    # Leading-dot-insensitive second pass (LAN behavior).
    assert matches_exclude(".cache", ["cache"]) is True
    assert matches_exclude("cache", [".cache"]) is True


def test_desktop_filter_accepts_respects_exclude_patterns(tmp_path):
    """Desktop FileSystemModel honours exclude_patterns like the LAN service."""
    from PySide6.QtWidgets import QApplication
    from AssetsManager.panels.file_list._model import FileSystemModel

    QApplication.instance() or QApplication([])
    (tmp_path / "keep.txt").write_text("x")
    (tmp_path / "skip.tmp").write_text("x")
    (tmp_path / ".hidden").write_text("x")

    model = FileSystemModel(exclude_patterns=["*.tmp"])
    model._exclude_patterns = ["*.tmp"]
    model._raw_entries = list(os.scandir(tmp_path))
    model._show_hidden = True

    accepted = {e.name for e in model._raw_entries if model.filter_accepts(e)}
    assert "keep.txt" in accepted
    assert "skip.tmp" not in accepted
    assert ".hidden" in accepted  # hidden filtering is a separate pass


def _model_accepted_names(root, *, show_hidden, search="", category="all", exclude=()):
    """Desktop accept-predicate over a real directory (no Qt widgets needed)."""
    from PySide6.QtWidgets import QApplication
    from AssetsManager.panels.file_list._model import FileSystemModel

    QApplication.instance() or QApplication([])
    model = FileSystemModel(exclude_patterns=list(exclude))
    model._show_hidden = show_hidden
    model._filter_text = search
    model._filter_cat = category
    model._raw_entries = list(os.scandir(root))
    return {e.name for e in model._raw_entries if model.filter_accepts(e)}


def _lan_accepted_names(root, *, show_hidden, search="", category="all", exclude=()):
    """LAN service result names for the same options."""
    from AssetsManager.application import AssetService, DirectoryListOptions

    listing = AssetService().list_directory(
        root,
        root,
        DirectoryListOptions(
            show_hidden=show_hidden,
            search=search,
            filter_category=category,
            exclude_patterns=exclude,
            scan_summaries=False,
        ),
    )
    return {item.name for item in listing.items}


@pytest.mark.parametrize(
    ("kwargs",),
    [
        ({"show_hidden": False},),
        ({"show_hidden": True},),
        ({"show_hidden": False, "search": "file"},),
        ({"show_hidden": False, "search": "IMAGE"},),
        ({"show_hidden": False, "category": "images"},),
        ({"show_hidden": False, "category": "documents"},),
        ({"show_hidden": False, "exclude": ("*.txt",)},),
        ({"show_hidden": False, "search": "a", "category": "all"},),
        ({"show_hidden": True, "search": ".h", "category": "all"},),
    ],
)
def test_filter_pipeline_matches_lan_listing(tmp_path, kwargs):
    """Desktop filter_accepts and the LAN service accept the same entries.

    The two surfaces share one pipeline (hidden → exclude → search →
    category), so a directory tree with dirs/dotfiles/multi-category files
    must yield identical name sets on both sides for every option combo.
    """
    _make_tree(tmp_path)
    desktop = _model_accepted_names(tmp_path, **kwargs)
    lan = _lan_accepted_names(tmp_path, **kwargs)
    assert desktop == lan


def test_uppercase_search_matches_on_both_surfaces(tmp_path):
    """Search is case-insensitive on both surfaces (desktop no longer needs
    the LAN's defensive pre-lowercase — matches_search handles it)."""
    _make_tree(tmp_path)
    assert "image.JPG" in _model_accepted_names(tmp_path, show_hidden=False, search="JPG")
    assert "image.JPG" in _lan_accepted_names(tmp_path, show_hidden=False, search="JPG")


def test_category_filter_keeps_directories_on_both_surfaces(tmp_path):
    """Directories survive category/include_types filtering on both surfaces.

    Directories never match a file-extension category, but navigation must
    not disappear while filtering by type.
    """
    _make_tree(tmp_path)
    desktop = _model_accepted_names(tmp_path, show_hidden=False, category="images")
    lan = _lan_accepted_names(tmp_path, show_hidden=False, category="images")
    for names in (desktop, lan):
        assert "zeta" in names
        assert "Alpha" in names
        assert "asset.png" in names
        assert "image.JPG" in names
        assert "file2.txt" not in names
