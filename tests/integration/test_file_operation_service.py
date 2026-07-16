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


def test_unbound_copy_to_directory_rejects_external_sources(tmp_path):
    import pytest

    from AssetsManager.application import FileOperationService

    library = tmp_path / "library"
    external = tmp_path.parent / "external.txt"
    library.mkdir()
    external.write_text("asset", encoding="utf-8")

    with pytest.raises(ValueError, match="outside library root"):
        FileOperationService().copy_to_directory([external], library)

    assert external.exists()
    assert not (library / external.name).exists()


def test_bound_copy_to_directory_allows_external_sources(tmp_path):
    from AssetsManager.application import ApplicationBootstrap

    library = tmp_path / "library"
    external = tmp_path / "external.txt"
    library.mkdir()
    external.write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    scoped = bootstrap.for_library(bootstrap.library_service.open_session(library))

    result = scoped.file_operation_service.copy_to_directory([external], library)

    assert result.ok
    assert (library / "external.txt").read_text(encoding="utf-8") == "asset"
    assert scoped.asset_index_service.get_entry(scoped.session.db_conn, library / "external.txt") is not None


def test_file_copied_observers_see_new_file_indexed(tmp_path):
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import FileCopied

    library = tmp_path / "library"
    external = tmp_path / "external.txt"
    library.mkdir()
    external.write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    scoped = bootstrap.for_library(bootstrap.library_service.open_session(library))
    conn = scoped.session.db_conn
    index = scoped.asset_index_service
    observed = []

    def observe(event):
        observed.append(index.get_entry(conn, event.destination_path) is not None)

    get_event_bus().subscribe(FileCopied, observe)

    result = scoped.file_operation_service.copy_to_directory([external], library)

    assert result.ok
    assert observed == [True]


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


def test_rename_reindexes_parent_after_metadata_migration(tmp_path):
    from AssetsManager.application import ApplicationBootstrap

    library = tmp_path / "library"
    library.mkdir()
    old = library / "old.txt"
    old.write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    scoped = bootstrap.for_library(bootstrap.library_service.open_session(library))
    scoped.asset_index_service.index_directory(scoped.session.db_conn, library, library)

    new = scoped.file_operation_service.rename(old, "new.txt")

    assert scoped.asset_index_service.get_entry(scoped.session.db_conn, old) is None
    assert scoped.asset_index_service.get_entry(scoped.session.db_conn, new) is not None


def test_copy_and_move_reindex_source_and_destination_parents(tmp_path):
    from AssetsManager.application import ApplicationBootstrap

    library = tmp_path / "library"
    source_dir = library / "source"
    destination_dir = library / "destination"
    source_dir.mkdir(parents=True)
    destination_dir.mkdir()
    source = source_dir / "asset.txt"
    source.write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    scoped = bootstrap.for_library(bootstrap.library_service.open_session(library))
    index = scoped.asset_index_service
    index.index_directory(scoped.session.db_conn, library, source_dir)
    index.index_directory(scoped.session.db_conn, library, destination_dir)

    copied = scoped.file_operation_service.copy_to_directory([source], destination_dir)
    moved = scoped.file_operation_service.move_to_directory([source], destination_dir)

    assert copied.ok and moved.ok
    assert index.get_entry(scoped.session.db_conn, copied.changed_paths[0]) is not None
    assert index.get_entry(scoped.session.db_conn, source) is None
    assert index.get_entry(scoped.session.db_conn, moved.changed_paths[0]) is not None


def test_directory_copy_reindexes_copied_tree(tmp_path):
    from AssetsManager.application import ApplicationBootstrap

    library = tmp_path / "library"
    source_dir = library / "source" / "folder"
    nested_dir = source_dir / "nested"
    destination_dir = library / "destination"
    asset = nested_dir / "asset.txt"
    nested_dir.mkdir(parents=True)
    destination_dir.mkdir()
    asset.write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    scoped = bootstrap.for_library(bootstrap.library_service.open_session(library))
    conn = scoped.session.db_conn
    index = scoped.asset_index_service

    copied = scoped.file_operation_service.copy_to_directory([source_dir], destination_dir)
    copied_root = copied.changed_paths[0]
    copied_nested = copied_root / nested_dir.name
    copied_asset = copied_nested / asset.name

    assert copied.ok
    assert index.get_entry(conn, copied_root) is not None
    assert index.get_entry(conn, copied_nested) is not None
    assert index.get_entry(conn, copied_asset) is not None


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


def test_bound_duplicate_rejects_external_source_and_destination(tmp_path):
    import pytest

    from AssetsManager.application import ApplicationBootstrap

    library = tmp_path / "library"
    external = tmp_path / "external.txt"
    library.mkdir()
    external.write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    scoped = bootstrap.for_library(bootstrap.library_service.open_session(library))

    with pytest.raises(ValueError, match="outside library root"):
        scoped.file_operation_service.duplicate(external)

    assert external.exists()
    assert not (tmp_path / "external_copy.txt").exists()


def test_bound_duplicate_rejects_external_destination(tmp_path, monkeypatch):
    import pytest

    from AssetsManager.application import ApplicationBootstrap

    library = tmp_path / "library"
    source = library / "asset.txt"
    external_destination = tmp_path / "external_copy.txt"
    library.mkdir()
    source.write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    scoped = bootstrap.for_library(bootstrap.library_service.open_session(library))
    monkeypatch.setattr(
        "AssetsManager.application.file_operation_service.unique_destination",
        lambda path: external_destination,
    )

    with pytest.raises(ValueError, match="outside library root"):
        scoped.file_operation_service.duplicate(source)

    assert source.exists()
    assert not external_destination.exists()


def test_bound_duplicate_rejects_closed_session_without_mutating(tmp_path):
    import pytest

    from AssetsManager.application import ApplicationBootstrap

    library = tmp_path / "library"
    source = library / "asset.txt"
    library.mkdir()
    source.write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    scoped = bootstrap.for_library(bootstrap.library_service.open_session(library))
    bootstrap.library_service.close_session(scoped.session)

    with pytest.raises(RuntimeError, match="closed LibrarySession"):
        scoped.file_operation_service.duplicate(source)

    assert source.exists()
    assert not (library / "asset_copy.txt").exists()


def test_delete_permanent_removes_files(tmp_path):
    from AssetsManager.application import FileOperationService

    src = tmp_path / "asset.txt"
    src.write_text("asset", encoding="utf-8")

    result = FileOperationService().delete_permanent([src])

    assert result.ok
    assert not src.exists()


def test_permanent_delete_clears_projection_subtree_and_reindexes_parent(tmp_path):
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.core.tag_store import TagStore
    from AssetsManager.repositories.thumbnail_repository import ThumbnailRepository

    library = tmp_path / "library"
    target = library / "folder"
    child = target / "asset.txt"
    child.parent.mkdir(parents=True)
    child.write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    scoped = bootstrap.for_library(bootstrap.library_service.open_session(library))
    conn = scoped.session.db_conn
    index = scoped.asset_index_service
    index.index_directory(conn, library, library)
    index.index_directory(conn, library, target)
    TagStore(str(library)).add_tag(str(child), "hero")
    conn.execute("INSERT INTO file_meta (file_path, notes) VALUES (?, ?)", (str(child.resolve()), "note"))
    ThumbnailRepository(conn).upsert_entry("thumb", str(child.resolve()), 1.0, 1, 1, 1)
    thumbnail_file = scoped.session.thumb_dir / "thumb.webp"
    thumbnail_file.write_bytes(b"thumb")

    result = scoped.file_operation_service.delete_permanent([target])

    assert result.ok
    assert conn.execute("SELECT 1 FROM file_meta WHERE file_path=?", (str(child.resolve()),)).fetchone() is None
    assert TagStore(str(library)).get_tags(str(child)) == []
    assert ThumbnailRepository(conn).list_all() == []
    assert not thumbnail_file.exists()
    assert index.get_entry(conn, target) is None
    assert index.get_entry(conn, child) is None


def test_trash_delete_clears_projections_before_file_deleted_subscribers_run(tmp_path, monkeypatch):
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.core.tag_store import TagStore
    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import FileDeleted
    from AssetsManager.repositories.thumbnail_repository import ThumbnailRepository

    library = tmp_path / "library"
    target = library / "folder"
    child = target / "asset.txt"
    child.parent.mkdir(parents=True)
    child.write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    scoped = bootstrap.for_library(bootstrap.library_service.open_session(library))
    conn = scoped.session.db_conn
    index = scoped.asset_index_service
    index.index_directory(conn, library, library)
    index.index_directory(conn, library, target)
    TagStore(str(library)).add_tag(str(child), "hero")
    conn.execute("INSERT INTO file_meta (file_path, notes) VALUES (?, ?)", (str(child.resolve()), "note"))
    ThumbnailRepository(conn).upsert_entry("thumb", str(child.resolve()), 1.0, 1, 1, 1)
    thumbnail_file = scoped.session.thumb_dir / "thumb.webp"
    thumbnail_file.write_bytes(b"thumb")
    monkeypatch.setattr("send2trash.send2trash", lambda path: target.rename(library / "trashed"))

    observed = []

    def observe_projection_cleanup(event):
        observed.append((
            TagStore(str(library)).get_tags(str(child)),
            conn.execute("SELECT 1 FROM file_meta WHERE file_path=?", (str(child.resolve()),)).fetchone(),
            ThumbnailRepository(conn).list_all(),
            thumbnail_file.exists(),
            index.get_entry(conn, target),
            index.get_entry(conn, child),
        ))

    get_event_bus().subscribe(FileDeleted, observe_projection_cleanup)

    result = scoped.file_operation_service.delete_to_trash([target])

    assert result.ok
    assert observed == [([], None, [], False, None, None)]


def test_bound_trash_delete_rejects_path_outside_library(tmp_path):
    import pytest
    from AssetsManager.application import ApplicationBootstrap

    library = tmp_path / "library"
    external = tmp_path / "external.txt"
    library.mkdir()
    external.write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    scoped = bootstrap.for_library(bootstrap.library_service.open_session(library))

    with pytest.raises(ValueError, match="outside library root"):
        scoped.file_operation_service.delete_to_trash([external])

    assert external.exists()


def test_directory_move_reindexes_new_hierarchy_and_removes_old_subtree(tmp_path):
    from AssetsManager.application import ApplicationBootstrap

    library = tmp_path / "library"
    source_parent = library / "source"
    destination_parent = library / "destination"
    old_dir = source_parent / "folder"
    nested_dir = old_dir / "nested"
    asset = nested_dir / "asset.txt"
    nested_dir.mkdir(parents=True)
    destination_parent.mkdir()
    asset.write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    scoped = bootstrap.for_library(bootstrap.library_service.open_session(library))
    conn = scoped.session.db_conn
    index = scoped.asset_index_service
    for directory in (library, source_parent, old_dir, nested_dir, destination_parent):
        index.index_directory(conn, library, directory)

    new_dir = scoped.file_operation_service.move(old_dir, destination_parent / old_dir.name)
    new_nested_dir = new_dir / nested_dir.name
    new_asset = new_nested_dir / asset.name

    assert index.get_entry(conn, old_dir) is None
    assert index.get_entry(conn, nested_dir) is None
    assert index.get_entry(conn, asset) is None
    assert index.get_entry(conn, new_dir) is not None
    assert index.get_entry(conn, new_nested_dir) is not None
    assert index.get_entry(conn, new_asset) is not None


def test_file_renamed_observers_see_moved_directory_projection(tmp_path):
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import FileRenamed

    library = tmp_path / "library"
    old_dir = library / "source" / "folder"
    old_child = old_dir / "nested" / "asset.txt"
    destination = library / "destination"
    old_child.parent.mkdir(parents=True)
    old_child.write_text("asset", encoding="utf-8")
    destination.mkdir()
    bootstrap = ApplicationBootstrap()
    scoped = bootstrap.for_library(bootstrap.library_service.open_session(library))
    conn = scoped.session.db_conn
    index = scoped.asset_index_service
    index.index_directory(conn, library, library)
    index.index_directory(conn, library, old_dir)
    index.index_directory(conn, library, old_child.parent)
    observed = []

    def observe(event):
        new_dir = event.new_path
        new_child = str((destination / old_dir.name / "nested" / "asset.txt").resolve())
        observed.append((
            index.get_entry(conn, event.old_path) is None,
            index.get_entry(conn, old_child) is None,
            index.get_entry(conn, new_dir) is not None,
            index.get_entry(conn, new_child) is not None,
        ))

    get_event_bus().subscribe(FileRenamed, observe)

    scoped.file_operation_service.move(old_dir, destination / old_dir.name)

    assert observed == [(True, True, True, True)]


def test_restore_backup_reindexes_directory_tree_before_publishing_created(tmp_path):
    import shutil

    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import FileCreated

    library = tmp_path / "library"
    target = library / "folder"
    child = target / "nested" / "asset.txt"
    backup = tmp_path / "backup"
    child.parent.mkdir(parents=True)
    child.write_text("asset", encoding="utf-8")
    shutil.copytree(target, backup)
    shutil.rmtree(target)
    bootstrap = ApplicationBootstrap()
    scoped = bootstrap.for_library(bootstrap.library_service.open_session(library))
    conn = scoped.session.db_conn
    index = scoped.asset_index_service
    observed = []

    def observe(event):
        observed.append((
            event.path,
            index.get_entry(conn, target) is not None,
            index.get_entry(conn, child) is not None,
        ))

    get_event_bus().subscribe(FileCreated, observe)

    restored = scoped.file_operation_service.restore_backup(backup, target)

    assert restored == target
    assert observed == [(str(target), True, True)]


def test_bound_restore_backup_rejects_destination_outside_library(tmp_path):
    import pytest

    from AssetsManager.application import ApplicationBootstrap

    library = tmp_path / "library"
    backup = tmp_path / "backup.txt"
    external = tmp_path / "external.txt"
    library.mkdir()
    backup.write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    scoped = bootstrap.for_library(bootstrap.library_service.open_session(library))

    with pytest.raises(ValueError, match="outside library root"):
        scoped.file_operation_service.restore_backup(backup, external)

    assert not external.exists()


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
