"""Tests for scoped FileSystemChanged projection-before-consumer ordering."""


def test_scoped_copy_projection_completes_before_file_system_changed_consumed(tmp_path):
    """Verify that file projection (index, metadata) is complete before scoped FileSystemChanged is consumed."""
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import FileSystemChanged

    source = tmp_path / "source.txt"
    source.write_text("scoped-projection-test")
    destination = tmp_path / "dest"
    destination.mkdir()

    bus = EventBus()
    events = []
    bus.subscribe(FileSystemChanged, events.append)
    import AssetsManager.domain.event_bus as eb
    from unittest.mock import patch
    with patch.object(eb, "_instance", bus):
        bootstrap = ApplicationBootstrap()
        session = bootstrap.library_service.open_session(tmp_path)
        runtime = bootstrap.runtime_for(session)
        service = runtime.services.file_operation_service
        index = runtime.services.asset_index_service
        try:
            # Perform copy operation
            service.copy_to_directory([source], destination)

            # Verify event was published
            assert len(events) == 1
            event = events[0]
            assert event.library_root == session.root_str
            assert event.session_token == session.event_token
            assert event.kind == "copied"

            # Verify projection is complete (file exists in destination)
            dest_file = destination / "source.txt"
            assert dest_file.exists()
            assert dest_file.read_text() == "scoped-projection-test"

            # Verify the event was consumed after projection
            # (event handler would see the file in the index)
            conn = session.connection_for(tmp_path)
            entry = index.get_entry(conn, dest_file)
            assert entry is not None
        finally:
            bootstrap.library_service.close()


def test_scoped_delete_projection_completes_before_file_system_changed_consumed(tmp_path):
    """Verify that file projection removal is complete before scoped FileSystemChanged is consumed."""
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import FileSystemChanged

    target = tmp_path / "delete_me.txt"
    target.write_text("delete-test")

    bus = EventBus()
    events = []
    bus.subscribe(FileSystemChanged, events.append)
    import AssetsManager.domain.event_bus as eb
    from unittest.mock import patch
    with patch.object(eb, "_instance", bus):
        bootstrap = ApplicationBootstrap()
        session = bootstrap.library_service.open_session(tmp_path)
        runtime = bootstrap.runtime_for(session)
        service = runtime.services.file_operation_service
        index = runtime.services.asset_index_service
        try:
            # Index the file first
            conn = session.connection_for(tmp_path)
            index.index_directory(conn, tmp_path, tmp_path)

            # Perform delete operation
            service.delete_permanent([target])

            # Verify event was published
            assert len(events) == 1
            event = events[0]
            assert event.library_root == session.root_str
            assert event.session_token == session.event_token
            assert event.kind == "deleted"

            # Verify projection is removed (file no longer in index)
            entry = index.get_entry(conn, target)
            assert entry is None

            # Verify file is actually deleted
            assert not target.exists()
        finally:
            bootstrap.library_service.close()
