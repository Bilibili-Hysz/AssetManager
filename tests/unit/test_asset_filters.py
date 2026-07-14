"""Tests for shared asset_filters module and desktop/LAN consistency."""
from AssetsManager.application.asset_filters import (
    extension_matches_category,
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
    assert matches_search("hero.png", "HERO") is False
    assert matches_search("hero.png", "") is True
    assert matches_search("hero.png", "villain") is False


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
