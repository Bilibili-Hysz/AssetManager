def test_create_folder_uses_unique_destination(tmp_path):
    from AssetsManager.application import FileOperationService

    service = FileOperationService()
    first = service.create_folder(tmp_path, "New Folder")
    second = service.create_folder(tmp_path, "New Folder")

    assert first.name == "New Folder"
    assert second.name == "New Folder_1"
    assert first.is_dir()
    assert second.is_dir()


def test_copy_to_directory_copies_files_and_renames_conflicts(tmp_path):
    from AssetsManager.application import FileOperationService

    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()
    src = src_dir / "asset.txt"
    src.write_text("asset", encoding="utf-8")
    (dst_dir / "asset.txt").write_text("existing", encoding="utf-8")

    result = FileOperationService().copy_to_directory([src], dst_dir)

    assert result.ok
    assert (dst_dir / "asset_1.txt").read_text(encoding="utf-8") == "asset"


def test_move_to_directory_moves_and_renames_conflicts(tmp_path):
    from AssetsManager.application import FileOperationService

    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()
    src = src_dir / "asset.txt"
    src.write_text("asset", encoding="utf-8")
    (dst_dir / "asset.txt").write_text("existing", encoding="utf-8")

    result = FileOperationService().move_to_directory([src], dst_dir)

    assert result.ok
    assert not src.exists()
    assert (dst_dir / "asset_1.txt").read_text(encoding="utf-8") == "asset"


def test_rename_migrates_metadata(tmp_path):
    from AssetsManager.application import FileOperationService
    from AssetsManager.core.tag_store import TagStore

    library = tmp_path / "library"
    library.mkdir()
    old = library / "old.txt"
    old.write_text("asset", encoding="utf-8")
    store = TagStore(str(library))
    store.add_tag(str(old), "hero")

    new = FileOperationService().rename(old, "new.txt", library_root=library)

    assert new.name == "new.txt"
    assert TagStore(str(library)).get_tags(str(new)) == ["hero"]


def test_rename_rejects_path_traversal_name(tmp_path):
    import pytest
    from AssetsManager.application import FileOperationService

    old = tmp_path / "old.txt"
    old.write_text("asset", encoding="utf-8")

    with pytest.raises(ValueError):
        FileOperationService().rename(old, "../escaped.txt")

    assert old.exists()
    assert not (tmp_path.parent / "escaped.txt").exists()


def test_duplicate_file(tmp_path):
    from AssetsManager.application import FileOperationService

    src = tmp_path / "asset.txt"
    src.write_text("asset", encoding="utf-8")

    duplicate = FileOperationService().duplicate(src)

    assert duplicate.name == "asset_copy.txt"
    assert duplicate.read_text(encoding="utf-8") == "asset"


def test_delete_permanent_removes_files(tmp_path):
    from AssetsManager.application import FileOperationService

    src = tmp_path / "asset.txt"
    src.write_text("asset", encoding="utf-8")

    result = FileOperationService().delete_permanent([src])

    assert result.ok
    assert not src.exists()


def test_try_reserve_creates_and_removes_temp_file(tmp_path):
    from AssetsManager.application.file_operation_service import _try_reserve

    target = tmp_path / "reserved.txt"
    assert _try_reserve(target) is True
    assert not target.exists()


def test_try_reserve_returns_false_for_existing_file(tmp_path):
    from AssetsManager.application.file_operation_service import _try_reserve

    target = tmp_path / "existing.txt"
    target.write_text("data", encoding="utf-8")

    assert _try_reserve(target) is False
    assert target.read_text(encoding="utf-8") == "data"


def test_unique_destination_uses_atomic_reservation(tmp_path):
    from AssetsManager.application.file_operation_service import unique_destination

    (tmp_path / "file.txt").write_text("first", encoding="utf-8")

    candidate = unique_destination(tmp_path / "file.txt")
    assert candidate == tmp_path / "file_1.txt"
    assert not candidate.exists()


def test_create_folder_survives_toctou_race(tmp_path):
    """If mkdir raises FileExistsError (TOCTOU race), create_folder retries."""
    import os
    from pathlib import Path
    from unittest.mock import patch
    from AssetsManager.application import FileOperationService

    (tmp_path / "New Folder").mkdir()
    call_count = {"n": 0}
    real_mkdir = Path.mkdir

    def race_mkdir(self, *a, **kw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            os.mkdir(str(self))
            raise FileExistsError("simulated race")
        return real_mkdir(self, *a, **kw)

    with patch.object(Path, "mkdir", race_mkdir):
        result = FileOperationService().create_folder(tmp_path, "New Folder")

    assert result.is_dir()
    assert call_count["n"] == 2
