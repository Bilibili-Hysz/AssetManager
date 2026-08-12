import pytest

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
    scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services

    result = scoped.file_operation_service.copy_to_directory([external], library)

    assert result.ok
    assert (library / "external.txt").read_text(encoding="utf-8") == "asset"
    conn = scoped.session.connection_for(library)
    assert scoped.asset_index_service.get_entry(conn, library / "external.txt") is not None


def test_file_copied_observers_see_new_file_indexed(tmp_path):
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import FileSystemChanged

    library = tmp_path / "library"
    external = tmp_path / "external.txt"
    library.mkdir()
    external.write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
    conn = scoped.session.connection_for(library)
    index = scoped.asset_index_service
    observed = []

    def observe(event):
        observed.append(index.get_entry(conn, event.paths[0]) is not None)

    get_event_bus().subscribe(FileSystemChanged, observe)

    result = scoped.file_operation_service.copy_to_directory([external], library)

    assert result.ok
    assert observed == [True]


def test_file_commands_record_after_projection_and_event_publication(tmp_path):
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.core.performance import PerformanceRecorder
    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import FileSystemChanged

    library = tmp_path / "library"
    library.mkdir()
    external = tmp_path / "external.txt"
    external.write_text("asset", encoding="utf-8")
    recorder = PerformanceRecorder(enabled=True)
    bootstrap = ApplicationBootstrap(performance_recorder=recorder)
    scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
    observed = []

    def observe(_event):
        events = [event for event in recorder.recent() if event.name == "file.command"]
        observed.append(events == [])

    get_event_bus().subscribe(FileSystemChanged, observe)
    result = scoped.file_operation_service.copy_to_directory([external], library)

    event = next(event for event in recorder.recent() if event.name == "file.command")
    assert result.ok
    assert observed == [True]
    assert event.session_token == scoped.session.event_token
    assert event.path == scoped.session.root_str
    assert event.attributes["command"] == "copy"
    assert event.attributes["outcome"] == "success"
    assert event.attributes["affected_count"] == 1
    assert event.attributes["phase"] == "events_published"
    assert event.attributes["operation_id"]


def test_file_command_recorder_failure_does_not_change_operation(tmp_path, monkeypatch):
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.core.performance import PerformanceRecorder

    library = tmp_path / "library"
    library.mkdir()
    external = tmp_path / "external.txt"
    external.write_text("asset", encoding="utf-8")
    recorder = PerformanceRecorder(enabled=True)
    monkeypatch.setattr(recorder, "record", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError()))
    bootstrap = ApplicationBootstrap(performance_recorder=recorder)
    scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services

    result = scoped.file_operation_service.copy_to_directory([external], library)

    assert result.ok
    assert (library / "external.txt").exists()


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


def test_move_to_directory_partial_success_records_only_moved_pairs(tmp_path):
    from AssetsManager.application import FileOperationService

    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()
    good = src_dir / "good.txt"
    good.write_text("asset", encoding="utf-8")
    missing = src_dir / "missing.txt"  # does not exist

    result = FileOperationService().move_to_directory([good, missing], dst_dir)

    # Partial failure: the missing source fails, the good one still moves.
    assert not result.ok
    assert len(result.errors) == 1
    assert result.moved_pairs == ((good, dst_dir / "good.txt"),)
    assert (dst_dir / "good.txt").read_text(encoding="utf-8") == "asset"
    assert not good.exists()
    assert not (dst_dir / "missing.txt").exists()


def test_rename_migrates_metadata(tmp_path):
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.core.tag_store import TagStore

    library = tmp_path / "library"
    library.mkdir()
    old = library / "old.txt"
    old.write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
    store = TagStore(str(library), db_conn=scoped.session.connection_for(library))
    store.add_tag(str(old), "hero")

    new = scoped.file_operation_service.rename(old, "new.txt")

    assert new.name == "new.txt"
    assert store.get_tags(str(new)) == ["hero"]


def test_unbound_rename_with_library_root_migrates_metadata(tmp_path):
    from AssetsManager.application import FileOperationService
    from AssetsManager.core.tag_store import TagStore

    library = tmp_path / "library"
    library.mkdir()
    old = library / "old.txt"
    old.write_text("asset", encoding="utf-8")
    store = TagStore(str(library))
    store.add_tag(str(old), "hero")

    new = FileOperationService().rename(old, "new.txt", library_root=library)

    assert store.get_tags(str(new)) == ["hero"]


def test_rename_ignores_asset_index_revision_conflict_after_filesystem_move(
    tmp_path, monkeypatch
):
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.application.asset_index_service import (
        AssetIndexPublishResult,
        AssetIndexPublishStatus,
    )

    library = tmp_path / "library"
    library.mkdir()
    old = library / "old.txt"
    old.write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services

    def stale_refresh(*_args, **_kwargs):
        return AssetIndexPublishResult(
            AssetIndexPublishStatus.STALE,
            expected_revision=1,
            actual_revision=2,
        )

    monkeypatch.setattr(
        scoped.asset_index_service, "index_directory_result", stale_refresh
    )
    try:
        new = scoped.file_operation_service.rename(old, "new.txt")
        assert new == library / "new.txt"
        assert new.exists()
        assert not old.exists()
        warnings = scoped.file_operation_service.last_refresh_warnings
        assert len(warnings) == 1
        assert warnings[0].code == "asset_index_refresh_stale"
        assert warnings[0].phase == "parent"
        assert warnings[0].status == "stale"
    finally:
        bootstrap.library_service.close()


def test_file_operation_records_degraded_index_refresh(tmp_path, monkeypatch):
    from sqlite3 import OperationalError

    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.application.asset_index_service import (
        AssetIndexPublishResult,
        AssetIndexPublishStatus,
    )
    from AssetsManager.core.performance import PerformanceRecorder

    library = tmp_path / "library"
    external = tmp_path / "external.txt"
    library.mkdir()
    external.write_text("asset", encoding="utf-8")
    recorder = PerformanceRecorder(enabled=True)
    bootstrap = ApplicationBootstrap(performance_recorder=recorder)
    session = bootstrap.library_service.open_session(library)
    try:
        scoped = bootstrap.runtime_for(session).services
        monkeypatch.setattr(
            scoped.asset_index_service,
            "index_directory_result",
            lambda *_args, **_kwargs: AssetIndexPublishResult(
                AssetIndexPublishStatus.BUSY,
                retry_count=2,
                failure=OperationalError("database is busy"),
            ),
        )

        result = scoped.file_operation_service.copy_to_directory([external], library)

        assert result.ok
        assert result.degraded
        assert len(result.warnings) == 1
        assert result.warnings[0].code == "asset_index_refresh_busy"
        assert result.warnings[0].phase == "parent"
        assert result.warnings[0].retry_count == 2
        assert result.warnings[0].failure_type == "OperationalError"
        assert result.warnings[0].path == str(library.resolve())
        assert result.warnings[0].message == f"asset_index_refresh_busy: {library.resolve()}"
        assert result.warnings[0].operation_id
        refresh_events = [
            event
            for event in recorder.recent()
            if event.name == "file.index_refresh"
        ]
        assert len(refresh_events) == 1
        assert refresh_events[0].attributes["phase"] == "parent"
        assert refresh_events[0].attributes["status"] == "busy"
        assert refresh_events[0].attributes["retry_count"] == 2
        assert refresh_events[0].attributes["failure_type"] == "OperationalError"
        assert refresh_events[0].attributes["reconciliation_state"] == "queued"
        assert refresh_events[0].attributes["reconciliation_error_type"] == ""
    finally:
        bootstrap.library_service.close()


def test_file_operation_labels_non_durable_index_refresh_as_staged(
    tmp_path, monkeypatch
):
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.application.asset_index_service import (
        AssetIndexPublishResult,
        AssetIndexPublishStatus,
    )

    library = tmp_path / "library"
    external = tmp_path / "external.txt"
    library.mkdir()
    external.write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    try:
        scoped = bootstrap.runtime_for(session).services
        monkeypatch.setattr(
            scoped.asset_index_service,
            "index_directory_result",
            lambda *_args, **_kwargs: AssetIndexPublishResult(
                AssetIndexPublishStatus.PUBLISHED,
                committed=False,
            ),
        )

        result = scoped.file_operation_service.copy_to_directory([external], library)

        assert result.ok
        assert result.degraded
        assert len(result.warnings) == 1
        assert result.warnings[0].code == "asset_index_refresh_staged"
        assert result.warnings[0].status == "staged"
    finally:
        bootstrap.library_service.close()


def test_path_command_refresh_diagnostics_survive_worker_thread(tmp_path, monkeypatch):
    from threading import Thread

    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.application.asset_index_service import (
        AssetIndexPublishResult,
        AssetIndexPublishStatus,
    )

    library = tmp_path / "library"
    library.mkdir()
    old = library / "old.txt"
    old.write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    failures: list[BaseException] = []
    try:
        scoped = bootstrap.runtime_for(session).services
        monkeypatch.setattr(
            scoped.asset_index_service,
            "index_directory_result",
            lambda *_args, **_kwargs: AssetIndexPublishResult(
                AssetIndexPublishStatus.STALE,
                expected_revision=1,
                actual_revision=2,
            ),
        )

        def run() -> None:
            try:
                scoped.file_operation_service.rename(old, "new.txt")
            except BaseException as exc:  # assertion below must observe worker errors
                failures.append(exc)

        worker = Thread(target=run)
        worker.start()
        worker.join(timeout=5)

        assert not worker.is_alive()
        assert not failures
        diagnostics = scoped.file_operation_service.drain_refresh_diagnostics()
        assert len(diagnostics) == 1
        operation_id, warnings = diagnostics[0]
        assert operation_id
        assert len(warnings) == 1
        assert warnings[0].operation_id == operation_id
        assert warnings[0].code == "asset_index_refresh_stale"
        assert scoped.file_operation_service.drain_refresh_diagnostics() == ()
        monkeypatch.setattr(
            scoped.asset_index_service,
            "index_directory_result",
            lambda *_args, **_kwargs: AssetIndexPublishResult(
                AssetIndexPublishStatus.PUBLISHED,
                committed=True,
            ),
        )
        scoped.file_operation_service.rename(library / "new.txt", "final.txt")
        assert scoped.file_operation_service.last_refresh_warnings == ()
    finally:
        bootstrap.library_service.close()


def test_refresh_diagnostics_filter_by_operation_id(tmp_path, monkeypatch):
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.application.asset_index_service import (
        AssetIndexPublishResult,
        AssetIndexPublishStatus,
    )

    library = tmp_path / "library"
    library.mkdir()
    first = library / "first.txt"
    second = library / "second.txt"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    try:
        scoped = bootstrap.runtime_for(session).services
        monkeypatch.setattr(
            scoped.asset_index_service,
            "index_directory_result",
            lambda *_args, **_kwargs: AssetIndexPublishResult(
                AssetIndexPublishStatus.STALE,
                expected_revision=1,
                actual_revision=2,
            ),
        )

        scoped.file_operation_service.rename(first, "first-new.txt")
        first_operation_id = scoped.file_operation_service.last_operation_id
        scoped.file_operation_service.rename(second, "second-new.txt")
        second_operation_id = scoped.file_operation_service.last_operation_id

        assert first_operation_id
        assert second_operation_id
        assert first_operation_id != second_operation_id
        first_diagnostics = scoped.file_operation_service.drain_refresh_diagnostics(
            first_operation_id
        )
        assert [operation_id for operation_id, _warnings in first_diagnostics] == [
            first_operation_id
        ]
        second_diagnostics = scoped.file_operation_service.drain_refresh_diagnostics(
            second_operation_id
        )
        assert [operation_id for operation_id, _warnings in second_diagnostics] == [
            second_operation_id
        ]
    finally:
        bootstrap.library_service.close()


def test_rename_reindexes_parent_after_metadata_migration(tmp_path):
    from AssetsManager.application import ApplicationBootstrap

    library = tmp_path / "library"
    library.mkdir()
    old = library / "old.txt"
    old.write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
    conn = scoped.session.connection_for(library)
    scoped.asset_index_service.index_directory(conn, library, library)

    new = scoped.file_operation_service.rename(old, "new.txt")

    assert scoped.asset_index_service.get_entry(conn, old) is None
    assert scoped.asset_index_service.get_entry(conn, new) is not None


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
    scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
    index = scoped.asset_index_service
    conn = scoped.session.connection_for(library)
    index.index_directory(conn, library, source_dir)
    index.index_directory(conn, library, destination_dir)

    copied = scoped.file_operation_service.copy_to_directory([source], destination_dir)
    moved = scoped.file_operation_service.move_to_directory([source], destination_dir)

    assert copied.ok and moved.ok
    assert index.get_entry(conn, copied.changed_paths[0]) is not None
    assert index.get_entry(conn, source) is None
    assert index.get_entry(conn, moved.changed_paths[0]) is not None


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
    scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
    conn = scoped.session.connection_for(library)
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
    scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services

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
    scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
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
    scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
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
    scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
    conn = scoped.session.connection_for(library)
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


def test_projection_cleanup_failure_rolls_back_prior_repository_deletes(
    tmp_path, monkeypatch
):
    import sqlite3

    import pytest

    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.core.tag_store import TagStore
    from AssetsManager.repositories.favorite_repository import FavoriteRepository
    from AssetsManager.repositories.metadata_repository import MetadataRepository

    library = tmp_path / "library"
    target = library / "asset.txt"
    target.parent.mkdir(parents=True)
    target.write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    try:
        scoped = bootstrap.runtime_for(session).services
        conn = session.connection_for(session.root)
        key = str(target.resolve())
        TagStore(str(library)).add_tag(key, "hero")
        MetadataRepository(conn).set_notes(key, "note")

        def fail_favorite_delete(self, file_path, *, commit=True):
            raise sqlite3.OperationalError("injected favorite cleanup failure")

        monkeypatch.setattr(FavoriteRepository, "delete_path", fail_favorite_delete)

        with pytest.raises(sqlite3.OperationalError, match="injected favorite"):
            scoped.file_operation_service._clear_deleted_projection(target)

        assert TagStore(str(library)).get_tags(key) == ["hero"]
        assert MetadataRepository(conn).get_notes(key) == "note"
        assert conn.in_transaction is False
    finally:
        bootstrap.library_service.close()


@pytest.mark.parametrize("failing_stage", ["thumbnail", "asset_index"])
def test_projection_cleanup_rolls_back_all_db_projections_on_late_failure(
    tmp_path, monkeypatch, failing_stage
):
    import sqlite3

    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.application.asset_index_service import AssetIndexService
    from AssetsManager.core.tag_store import TagStore
    from AssetsManager.repositories.favorite_repository import FavoriteRepository
    from AssetsManager.repositories.metadata_repository import MetadataRepository
    from AssetsManager.repositories.thumbnail_repository import ThumbnailRepository

    library = tmp_path / "library"
    target = library / "folder"
    child = target / "asset.txt"
    child.parent.mkdir(parents=True)
    child.write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    try:
        scoped = bootstrap.runtime_for(session).services
        conn = session.connection_for(library)
        key = str(child.resolve())
        scoped.asset_index_service.index_directory(conn, library, library)
        scoped.asset_index_service.index_directory(conn, library, target)
        TagStore(str(library)).add_tag(key, "hero")
        MetadataRepository(conn).set_notes(key, "note")
        FavoriteRepository(conn).add("owner", key)
        ThumbnailRepository(conn).upsert_entry("thumb", key, 1.0, 1, 1, 1)

        if failing_stage == "thumbnail":
            def fail_thumbnail_delete(self, source_path, *, commit=True):
                raise sqlite3.OperationalError("injected thumbnail cleanup failure")

            monkeypatch.setattr(ThumbnailRepository, "delete_path", fail_thumbnail_delete)
        else:
            def fail_index_delete(self, conn, file_path, *, commit=True):
                raise sqlite3.OperationalError("injected asset index cleanup failure")

            monkeypatch.setattr(AssetIndexService, "remove_entry", fail_index_delete)

        with pytest.raises(sqlite3.OperationalError, match="injected"):
            scoped.file_operation_service._clear_deleted_projection(target)

        assert TagStore(str(library)).get_tags(key) == ["hero"]
        assert MetadataRepository(conn).get_notes(key) == "note"
        assert FavoriteRepository(conn).contains("owner", key)
        assert ThumbnailRepository(conn).list_all() == [("thumb", key)]
        assert scoped.asset_index_service.get_entry(conn, child) is not None
        assert conn.in_transaction is False
    finally:
        bootstrap.library_service.close()


def test_delete_projection_publishes_tag_catalog_invalidation(tmp_path, monkeypatch):
    import AssetsManager.domain.event_bus as event_bus_module
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import TagCatalogChanged

    library = tmp_path / "library"
    target = library / "asset.txt"
    library.mkdir()
    target.write_text("asset", encoding="utf-8")
    bus = EventBus()
    catalogs: list[object] = []
    bus.subscribe(TagCatalogChanged, catalogs.append)
    monkeypatch.setattr(event_bus_module, "_instance", bus)

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    try:
        scoped = bootstrap.runtime_for(session).services
        scoped.tag_service.add_tag(library, target, "hero")
        catalogs.clear()

        result = scoped.file_operation_service.delete_permanent([target])

        assert result.ok
        assert len(catalogs) == 1
        assert catalogs[0].session_token == session.event_token
    finally:
        bootstrap.library_service.close()


def test_trash_delete_clears_projections_before_file_deleted_subscribers_run(tmp_path, monkeypatch):
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.core.tag_store import TagStore
    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import FileSystemChanged
    from AssetsManager.repositories.thumbnail_repository import ThumbnailRepository

    library = tmp_path / "library"
    target = library / "folder"
    child = target / "asset.txt"
    child.parent.mkdir(parents=True)
    child.write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
    conn = scoped.session.connection_for(library)
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

    get_event_bus().subscribe(FileSystemChanged, observe_projection_cleanup)

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
    scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services

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
    scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
    conn = scoped.session.connection_for(library)
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


def test_bound_move_rejects_caller_outer_transaction_before_filesystem_change(tmp_path):
    from AssetsManager.application import ApplicationBootstrap

    library = tmp_path / "library"
    source = library / "source.txt"
    destination = library / "destination.txt"
    library.mkdir()
    source.write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    try:
        runtime = bootstrap.runtime_for(session)
        # The reconciliation worker shares the session connection and can
        # hold a write transaction while the test opens its own; stop it so
        # the caller-owned outer transaction is the only one in flight.
        runtime.services.reconciliation_service.stop()
        service = runtime.services.file_operation_service
        conn = session.connection_for(library)
        conn.execute("CREATE TABLE caller_data (value TEXT NOT NULL)")
        conn.commit()
        conn.execute("BEGIN")
        conn.execute("INSERT INTO caller_data VALUES ('keep-me')")

        with pytest.raises(RuntimeError, match="clean transaction boundary"):
            service.move(source, destination)

        assert source.exists()
        assert not destination.exists()
        assert conn.execute("SELECT * FROM caller_data").fetchall() == [("keep-me",)]
        conn.rollback()
    finally:
        bootstrap.library_service.close()


def test_file_renamed_observers_see_moved_directory_projection(tmp_path):
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import FileSystemChanged

    library = tmp_path / "library"
    old_dir = library / "source" / "folder"
    old_child = old_dir / "nested" / "asset.txt"
    destination = library / "destination"
    old_child.parent.mkdir(parents=True)
    old_child.write_text("asset", encoding="utf-8")
    destination.mkdir()
    bootstrap = ApplicationBootstrap()
    scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
    conn = scoped.session.connection_for(library)
    index = scoped.asset_index_service
    index.index_directory(conn, library, library)
    index.index_directory(conn, library, old_dir)
    index.index_directory(conn, library, old_child.parent)
    observed = []

    def observe(event):
        new_dir = event.paths[0]
        new_child = str((destination / old_dir.name / "nested" / "asset.txt").resolve())
        observed.append((
            index.get_entry(conn, event.old_paths[0]) is None,
            index.get_entry(conn, old_child) is None,
            index.get_entry(conn, new_dir) is not None,
            index.get_entry(conn, new_child) is not None,
        ))

    get_event_bus().subscribe(FileSystemChanged, observe)

    scoped.file_operation_service.move(old_dir, destination / old_dir.name)

    assert observed == [(True, True, True, True)]


def test_restore_backup_reindexes_directory_tree_before_publishing_created(tmp_path):
    import shutil

    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import FileSystemChanged

    library = tmp_path / "library"
    target = library / "folder"
    child = target / "nested" / "asset.txt"
    backup = tmp_path / "backup"
    child.parent.mkdir(parents=True)
    child.write_text("asset", encoding="utf-8")
    shutil.copytree(target, backup)
    shutil.rmtree(target)
    bootstrap = ApplicationBootstrap()
    scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
    conn = scoped.session.connection_for(library)
    index = scoped.asset_index_service
    observed = []

    def observe(event):
        observed.append((
            event.paths[0],
            index.get_entry(conn, target) is not None,
            index.get_entry(conn, child) is not None,
        ))

    get_event_bus().subscribe(FileSystemChanged, observe)

    restored = scoped.file_operation_service.restore_backup(backup, target)

    assert restored == target
    assert observed == [(str(target), True, True)]


def test_create_and_duplicate_reindex_before_publishing_created(tmp_path):
    from pathlib import Path

    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import FileSystemChanged

    library = tmp_path / "library"
    source = library / "source.txt"
    source.parent.mkdir()
    source.write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
    conn = scoped.session.connection_for(library)
    index = scoped.asset_index_service
    observed = []

    def observe(event):
        path = Path(event.paths[0])
        observed.append((path, index.get_entry(conn, path) is not None))

    get_event_bus().subscribe(FileSystemChanged, observe)

    created = scoped.file_operation_service.create_folder(library)
    duplicate = scoped.file_operation_service.duplicate(source)

    assert observed == [(created, True), (duplicate, True)]


def test_bound_restore_backup_rejects_destination_outside_library(tmp_path):
    import pytest

    from AssetsManager.application import ApplicationBootstrap

    library = tmp_path / "library"
    backup = tmp_path / "backup.txt"
    external = tmp_path / "external.txt"
    library.mkdir()
    backup.write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services

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


def test_refresh_warning_enqueues_reconciliation_without_consuming_it(tmp_path, monkeypatch):
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.application.asset_index_service import (
        AssetIndexPublishResult,
        AssetIndexPublishStatus,
    )

    library = tmp_path / "library"
    external = tmp_path / "external.txt"
    library.mkdir()
    external.write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    try:
        scoped = bootstrap.runtime_for(session).services
        assert scoped.reconciliation_service is not None
        scoped.reconciliation_service.stop()
        monkeypatch.setattr(
            scoped.asset_index_service,
            "index_directory_result",
            lambda *_args, **_kwargs: AssetIndexPublishResult(
                AssetIndexPublishStatus.STALE,
                expected_revision=3,
                actual_revision=4,
            ),
        )

        result = scoped.file_operation_service.copy_to_directory([external], library)

        assert result.ok
        assert result.degraded
        assert scoped.reconciliation_queue is not None
        tasks = scoped.reconciliation_queue.snapshot()
        assert len(tasks) == 1
        task = tasks[0]
        assert task.reason == "stale"
        assert task.expected_revision == 3
        assert task.observed_revision == 4
        assert result.warnings[0].operation_id in task.operation_ids

        scoped.file_operation_service.drain_refresh_diagnostics(
            result.warnings[0].operation_id
        )
        assert scoped.reconciliation_queue.get(task.task_id) is not None
    finally:
        bootstrap.library_service.close()



@pytest.mark.parametrize("operation", ["delete_permanent", "delete_to_trash"])
def test_bound_delete_rejects_outer_transaction_before_filesystem_change(
    tmp_path, operation
):
    from AssetsManager.application import ApplicationBootstrap

    library = tmp_path / "library"
    source = library / "source.txt"
    library.mkdir()
    source.write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    try:
        runtime = bootstrap.runtime_for(session)
        # The reconciliation worker shares the session connection and can
        # hold a write transaction while the test opens its own; stop it so
        # the caller-owned outer transaction is the only one in flight.
        runtime.services.reconciliation_service.stop()
        service = runtime.services.file_operation_service
        conn = session.connection_for(library)
        conn.execute("CREATE TABLE caller_data (value TEXT NOT NULL)")
        conn.commit()
        conn.execute("BEGIN")
        conn.execute("INSERT INTO caller_data VALUES ('keep-me')")

        with pytest.raises(RuntimeError, match="clean transaction boundary"):
            getattr(service, operation)([source])

        assert source.exists()
        assert conn.execute("SELECT * FROM caller_data").fetchall() == [("keep-me",)]
        conn.rollback()
    finally:
        bootstrap.library_service.close()
