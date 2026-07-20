from AssetsManager.dialogs.sidebar_favorites import SidebarFavorites
from AssetsManager.dialogs.sidebar_recent import SidebarRecentFolders


def test_sidebar_json_stores_use_explicit_library_data_dir(tmp_path):
    data_dir = tmp_path / "runtime" / "library"
    root = tmp_path / "library-root"

    favorites = SidebarFavorites()
    recents = SidebarRecentFolders()
    favorites.set_library_root(str(root), data_dir)
    recents.set_library_root(str(root), data_dir)

    assert favorites._path == data_dir / "favorites.json"
    assert recents._path == data_dir / "recent.json"
