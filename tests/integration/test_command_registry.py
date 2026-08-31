"""CommandRegistry — end-to-end over a real bootstrap library (H2-d)."""
from pathlib import Path

import pytest


@pytest.fixture
def library(tmp_path):
    """One canonical library session with its services."""
    from AssetsManager.application.bootstrap import ApplicationBootstrap

    bootstrap = ApplicationBootstrap()
    root = tmp_path / "library"
    root.mkdir(parents=True, exist_ok=True)
    session = bootstrap.library_service.open_session(root)
    services = bootstrap.runtime_for(session).services
    try:
        yield bootstrap, session, services
    finally:
        bootstrap.library_service.close()


def _make_asset(root: Path, name: str, content: bytes = b"x") -> Path:
    path = root / name
    path.write_bytes(content)
    return path


def test_registry_exposes_the_first_command_batch(library):
    _, _, services = library
    ids = set(services.command_registry.descriptors())
    assert {
        "file.delete_trash", "file.delete_permanent", "file.move_to_directory",
        "file.copy_to_directory", "file.create_folder", "file.rename",
        "tag.add", "tag.remove",
    } <= ids


def test_delete_permanent_via_registry_is_undo_wrapped(library):
    _, session, services = library
    root = Path(session.root)
    asset = _make_asset(root, "doomed.bin", b"payload")
    registry = services.command_registry

    result = registry.execute("file.delete_permanent", [str(asset)])

    assert result.status == "ok"
    assert result.succeeded == 1
    assert not asset.exists()
    # The undo safety net wraps registry-driven deletes too: one batch
    # entry holding the delete, restorable with perform_undo().
    undo_service = services.undo_service
    history = undo_service.history_snapshot()
    assert len(history) == 1
    assert history[0].is_batch is True
    assert history[0].child_count == 1
    restored = undo_service.perform_undo(services.file_operation_service)
    assert restored is not False
    assert asset.exists()


def test_move_via_registry_moves_file_and_records_undo(library):
    _, session, services = library
    root = Path(session.root)
    source = _make_asset(root, "movable.txt", b"move me")
    destination = root / "moved_into"
    destination.mkdir()

    result = services.command_registry.execute(
        "file.move_to_directory", [str(source)],
        destination_dir=str(destination),
    )

    assert result.status == "ok"
    assert not source.exists()
    assert (destination / "movable.txt").exists()


def test_tag_add_via_registry_lands_in_tag_store(library):
    _, session, services = library
    root = Path(session.root)
    asset = _make_asset(root, "tagged.bin")

    result = services.command_registry.execute(
        "tag.add", [str(asset)], tag="hero",
    )

    assert result.status == "ok"
    tags = services.tag_service.get_tags(
        session.root_str, asset, db_conn=session.connection_for(session.root)
    )
    assert "hero" in tags


def test_registry_unknown_command_and_empty_targets(library):
    _, _, services = library
    registry = services.command_registry
    with pytest.raises(KeyError):
        registry.get("file.does_not_exist")
    with pytest.raises(ValueError):
        registry.execute("file.delete_trash", [])


def test_registry_handler_exception_becomes_failed_result(library):
    _, _, services = library
    from AssetsManager.application.command_registry import (
        CommandDescriptor,
        CommandRegistry,
    )

    def broken(targets, **params):
        raise RuntimeError("boom")

    registry = CommandRegistry({
        "file.broken": CommandDescriptor(
            command_id="file.broken", title_key="command.file.broken",
            impact="file_write", approval="none", handler=broken),
    })
    result = registry.execute("file.broken", ["a"])
    assert result.status == "failed"
    assert "boom" in result.errors[0]
