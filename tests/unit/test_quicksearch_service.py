"""Focused tests for the command-palette quick-search service method."""
from __future__ import annotations

import os

import pytest

from AssetsManager.application.search_service import SearchService


def test_quick_search_returns_mixed_results_with_stable_priority(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    (root / "Alpha Folder").mkdir()
    (root / "Alpha Folder" / "nested.txt").write_text("nested")
    (root / "alpha.png").write_bytes(b"png")
    (root / "misc").mkdir()
    (root / "misc" / "alpha.txt").write_text("alpha")

    results = SearchService().quick_search(root, "alpha", limit=10)

    assert [(item.name, item.type) for item in results] == [
        ("Alpha Folder", "dir"),
        ("alpha.png", "file"),
        ("alpha.txt", "file"),
        ("nested.txt", "file"),
    ]
    assert results[0].path == "Alpha Folder"
    assert results[0].extension == ""
    assert results[0].category == "folder"
    assert results[1].path == "alpha.png"
    assert results[1].extension == ".png"
    assert results[1].category == "images"


def test_quick_search_supports_path_matches_without_returning_absolute_paths(tmp_path):
    root = tmp_path / "library"
    (root / "Textures" / "Wood").mkdir(parents=True)
    (root / "Textures" / "Wood" / "oak.dat").write_text("oak")

    results = SearchService().quick_search(root, "textures/wood", limit=10)

    assert [item.path for item in results] == ["Textures/Wood", "Textures/Wood/oak.dat"]
    assert all(not os.path.isabs(item.path) for item in results)
    assert str(root) not in results[0].path


def test_quick_search_skips_hidden_and_symlink_escape(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    (root / ".hidden.txt").write_text("hidden")
    (root / ".hidden_dir").mkdir()
    (root / ".hidden_dir" / "nested.txt").write_text("hidden")
    try:
        (root / "escape").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    results = SearchService().quick_search(root, "secret", limit=10)

    assert results == []


def test_quick_search_empty_query_and_limit_boundaries(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    (root / "asset.txt").write_text("asset")
    service = SearchService()

    assert service.quick_search(root, "   ") == []
    assert len(service.quick_search(root, "asset", limit=1)) == 1
    with pytest.raises(ValueError):
        service.quick_search(root, "asset", limit=0)
    with pytest.raises(ValueError):
        service.quick_search(root, "asset", limit=101)
