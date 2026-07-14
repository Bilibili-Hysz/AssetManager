def test_asset_service_lists_visible_items(tmp_path):
    from AssetsManager.application import AssetService

    (tmp_path / "visible.txt").write_text("hello", encoding="utf-8")
    (tmp_path / ".hidden.txt").write_text("secret", encoding="utf-8")
    (tmp_path / "folder").mkdir()

    listing = AssetService().list_directory(tmp_path, tmp_path)
    names = [item.name for item in listing.items]

    assert names == ["folder", "visible.txt"]
    assert listing.total_count == 2
    assert listing.current_path == ""


def test_asset_service_filters_and_searches(tmp_path):
    from AssetsManager.application import AssetService, DirectoryListOptions

    (tmp_path / "hero.png").write_text("image", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("doc", encoding="utf-8")
    (tmp_path / "villain.png").write_text("image", encoding="utf-8")

    listing = AssetService().list_directory(
        tmp_path,
        tmp_path,
        DirectoryListOptions(filter_category="images", search="hero"),
    )

    assert [item.name for item in listing.items] == ["hero.png"]


def test_asset_service_respects_include_and_exclude(tmp_path):
    from AssetsManager.application import AssetService, DirectoryListOptions

    (tmp_path / "asset.png").write_text("image", encoding="utf-8")
    (tmp_path / "asset.tmp").write_text("tmp", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("doc", encoding="utf-8")

    listing = AssetService().list_directory(
        tmp_path,
        tmp_path,
        DirectoryListOptions(include_types=("images", "documents"), exclude_patterns=("*.tmp",)),
    )

    assert [item.name for item in listing.items] == ["asset.png", "notes.txt"]


def test_asset_service_applies_max_depth_to_child_dirs(tmp_path):
    from AssetsManager.application import AssetService, DirectoryListOptions

    (tmp_path / "child").mkdir()
    (tmp_path / "asset.txt").write_text("doc", encoding="utf-8")

    listing = AssetService().list_directory(
        tmp_path,
        tmp_path,
        DirectoryListOptions(max_depth=1, current_depth=1),
    )

    assert [item.name for item in listing.items] == ["asset.txt"]
