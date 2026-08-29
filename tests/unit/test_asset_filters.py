"""Tests for shared asset_filters module and desktop/LAN consistency."""
from AssetsManager.application.asset_filters import (
    extension_matches_category,
    filters_accept,
    is_hidden,
    matches_search,
    natural_key,
    normalize_filter_category,
    normalize_sort_key,
    sort_key_for_entry,
)
from AssetsManager.domain.asset import category_for_extension


def test_normalize_sort_key_from_display_names():
    assert normalize_sort_key("Name") == "name"
    assert normalize_sort_key("Date") == "date"
    assert normalize_sort_key("Size") == "size"
    assert normalize_sort_key("Type") == "type"


def test_normalize_sort_key_from_canonical():
    assert normalize_sort_key("name") == "name"
    assert normalize_sort_key("date") == "date"
    assert normalize_sort_key("size") == "size"
    assert normalize_sort_key("type") == "type"


def test_normalize_sort_key_defaults_to_name():
    assert normalize_sort_key("") == "name"
    assert normalize_sort_key("unknown") == "unknown"


def test_normalize_filter_category_from_display_names():
    assert normalize_filter_category("All") == "all"
    assert normalize_filter_category("Images") == "images"
    assert normalize_filter_category("3D Models") == "models"
    assert normalize_filter_category("Videos") == "videos"
    assert normalize_filter_category("Documents") == "documents"
    assert normalize_filter_category("Archives") == "archives"


def test_normalize_filter_category_from_canonical():
    assert normalize_filter_category("all") == "all"
    assert normalize_filter_category("images") == "images"


def test_normalize_filter_category_defaults_to_all():
    assert normalize_filter_category("") == "all"
    assert normalize_filter_category("unknown") == "unknown"


def test_category_for_extension():
    assert category_for_extension(".png") == "images"
    assert category_for_extension(".blend") == "3d"
    assert category_for_extension(".mp4") == "videos"
    assert category_for_extension(".txt") == "documents"
    assert category_for_extension(".zip") == "archives"
    assert category_for_extension(".xyz") == "other"


def test_extension_matches_category():
    assert extension_matches_category(".png", "images") is True
    assert extension_matches_category(".png", "Images") is True
    assert extension_matches_category(".png", "all") is True
    assert extension_matches_category(".png", "videos") is False
    assert extension_matches_category(".blend", "3D Models") is True
    assert extension_matches_category(".blend", "models") is True


def test_is_hidden():
    assert is_hidden(".hidden") is True
    assert is_hidden("visible") is False
    assert is_hidden(".gitignore") is True


def test_matches_search():
    assert matches_search("hero.png", "hero") is True
    assert matches_search("hero.png", "HERO") is True  # case handled internally
    assert matches_search("hero.png", "HeRo") is True
    assert matches_search("hero.png", "") is True
    assert matches_search("hero.png", "villain") is False


# ── filters_accept (shared desktop/LAN accept-predicate) ───────────

def test_filters_accept_defaults_pass_everything():
    assert filters_accept("any-name.bin", False) is True
    assert filters_accept("folder", True) is True


def test_filters_accept_hidden():
    assert filters_accept(".secret", False, show_hidden=False) is False
    assert filters_accept(".secret", False, show_hidden=True) is True
    assert filters_accept("visible.txt", False, show_hidden=False) is True


def test_filters_accept_exclude_patterns():
    assert filters_accept("asset.tmp", False, exclude_patterns=("*.tmp",)) is False
    assert filters_accept(".tmp-cache", False, exclude_patterns=("*.tmp",)) is True
    assert filters_accept("keep.txt", False, exclude_patterns=("*.tmp",)) is True
    # Leading-dot-insensitive second pass (LAN semantics): the pattern
    # without a dot still excludes the dot-prefixed entry, and vice versa.
    assert filters_accept(".cache", False, exclude_patterns=("cache",)) is False
    assert filters_accept("cache", False, exclude_patterns=(".cache",)) is False
    assert filters_accept(".gitignore", False, exclude_patterns=(".gitignore",)) is False


def test_filters_accept_include_types_applies_to_files_only():
    assert filters_accept("hero.png", False, include_types=("images",)) is True
    assert filters_accept("notes.txt", False, include_types=("images",)) is False
    assert filters_accept("subfolder", True, include_types=("images",)) is True


def test_filters_accept_max_depth_applies_to_dirs_only():
    assert filters_accept("child", True, max_depth=1, current_depth=1) is False
    assert filters_accept("child", True, max_depth=1, current_depth=0) is True
    assert filters_accept("asset.txt", False, max_depth=1, current_depth=1) is True


def test_filters_accept_search_is_case_insensitive():
    assert filters_accept("hero.png", False, search="HERO") is True
    assert filters_accept("hero.png", False, search="villain") is False
    assert filters_accept("hero.png", False, search="") is True


def test_filters_accept_category_keeps_directories():
    assert filters_accept("hero.png", False, filter_category="images") is True
    assert filters_accept("notes.txt", False, filter_category="images") is False
    assert filters_accept("subfolder", True, filter_category="images") is True
    assert filters_accept("subfolder", True, filter_category="Images") is True


def test_filters_accept_combined_pipeline():
    # hidden → exclude → include_types → max_depth → search → category
    assert filters_accept(
        "hero.png", False,
        show_hidden=False, exclude_patterns=("*.png",), search="hero", filter_category="images",
    ) is False
    assert filters_accept(
        "hero.png", False,
        show_hidden=False, exclude_patterns=(), search="HERO", filter_category="images",
    ) is True
    assert filters_accept(
        "subfolder", True,
        show_hidden=False, exclude_patterns=(), search="nomatch", filter_category="images",
    ) is False


def test_natural_key_sorting():
    files = ["file10.txt", "file2.txt", "file1.txt", "file20.txt"]
    result = sorted(files, key=natural_key)
    assert result == ["file1.txt", "file2.txt", "file10.txt", "file20.txt"]


def test_sort_key_for_entry_dirs_first():
    key_dir = sort_key_for_entry("folder", True, 0, 0, "", "name")
    key_file = sort_key_for_entry("file.txt", False, 0, 0, ".txt", "name")
    assert key_dir < key_file


def test_sort_key_for_entry_by_name():
    key_a = sort_key_for_entry("alpha", False, 0, 0, ".txt", "name")
    key_b = sort_key_for_entry("beta", False, 0, 0, ".txt", "name")
    assert key_a < key_b


def test_sort_key_for_entry_by_date():
    key_old = sort_key_for_entry("old", False, 100, 0, ".txt", "date")
    key_new = sort_key_for_entry("new", False, 200, 0, ".txt", "date")
    assert key_old > key_new


def test_sort_key_for_entry_by_size():
    key_small = sort_key_for_entry("small", False, 0, 100, ".txt", "size")
    key_big = sort_key_for_entry("big", False, 0, 200, ".txt", "size")
    assert key_small > key_big


def test_matches_structured_extension_normalization():
    from AssetsManager.application.asset_filters import matches_structured

    assert matches_structured("a.png", False, size=1, mtime=1.0, extensions=["PNG", ".jpg"]) is True
    assert matches_structured("a.png", False, size=1, mtime=1.0, extensions=["png"]) is True
    assert matches_structured("a.png", False, size=1, mtime=1.0, extensions=["jpg"]) is False
    assert matches_structured("a.png", False, size=1, mtime=1.0, extensions=[" "]) is True
    # Directories always pass so navigation never disappears.
    assert matches_structured("subdir", True, size=0, mtime=0.0, extensions=["png"]) is True


def test_matches_structured_size_and_mtime_bounds_inclusive():
    from AssetsManager.application.asset_filters import matches_structured

    accept = matches_structured(
        "a.png", False, size=1000, mtime=2000.0,
        size_min=1000, size_max=1000, mtime_after=2000.0, mtime_before=2000.0,
    )
    assert accept is True
    assert matches_structured("a.png", False, size=999, mtime=1.0, size_min=1000) is False
    assert matches_structured("a.png", False, size=1001, mtime=1.0, size_max=1000) is False
    assert matches_structured("a.png", False, size=1, mtime=1999.9, mtime_after=2000.0) is False
    assert matches_structured("a.png", False, size=1, mtime=2000.1, mtime_before=2000.0) is False
