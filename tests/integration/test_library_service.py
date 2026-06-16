from pathlib import Path

import pytest


def test_open_library_returns_context(tmp_path):
    from AssetsManager.application import get_library_service

    root = tmp_path / "library"
    root.mkdir()

    service = get_library_service()
    context = service.open_library(root)

    assert context.root == root.resolve()
    assert context.data_dir.exists()
    assert context.thumb_dir.exists()
    assert context.db_conn is not None
    assert context.tag_store is not None
    assert context.project_data is not None
    assert service.current_session is not None
    assert service.current_session.context is context


def test_current_session_is_none_before_open():
    from AssetsManager.application.library_service import LibraryService

    service = LibraryService()

    assert service.current_session is None


def test_current_context_remains_legacy_compatibility_api(tmp_path):
    from AssetsManager.application.library_service import LibraryService

    root = tmp_path / "library"
    root.mkdir()

    service = LibraryService()
    session = service.open_session(root)

    assert service.current is session.context


def test_open_library_reuses_context(tmp_path):
    from AssetsManager.application import get_library_service

    root = tmp_path / "library"
    root.mkdir()

    service = get_library_service()
    first = service.open_library(str(root))
    second = service.open_library(Path(root))

    assert first is second


def test_open_session_wraps_cached_context(tmp_path):
    from AssetsManager.application.library_service import LibraryService

    root = tmp_path / "library"
    root.mkdir()

    service = LibraryService()
    context = service.open_library(root)
    session = service.open_session(root)

    assert session.context is context
    assert session.root == context.root
    assert session.db_conn is context.db_conn
    assert service.current_session is not None
    assert service.current_session.context is context


def test_open_session_reuses_cached_context(tmp_path):
    from AssetsManager.application.library_service import LibraryService

    root = tmp_path / "library"
    root.mkdir()

    service = LibraryService()
    first = service.open_session(str(root))
    second = service.open_session(Path(root))

    assert first.context is second.context
    assert first.root == root.resolve()
    assert second.root == root.resolve()


def test_open_session_contexts_do_not_follow_current_library(tmp_path):
    from AssetsManager.application.library_service import LibraryService

    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()

    service = LibraryService()
    first = service.open_session(first_root)
    second = service.open_session(second_root)

    assert first.context is not second.context
    assert first.root == first_root.resolve()
    assert second.root == second_root.resolve()
    assert first.db_conn is service._db.connection_for(first_root)
    assert second.db_conn is service._db.connection_for(second_root)
    assert first.db_conn is not second.db_conn


def test_current_session_tracks_latest_opened_library(tmp_path):
    from AssetsManager.application.library_service import LibraryService

    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()

    service = LibraryService()
    first = service.open_session(first_root)
    second = service.open_session(second_root)

    assert service.current_session is not None
    assert service.current_session.context is second.context
    assert service.current_session.root == second.root
    assert service.current_session is not first


def test_library_session_connection_provider_rejects_mismatched_root(tmp_path):
    from AssetsManager.application.library_service import LibraryService

    root = tmp_path / "library"
    other = tmp_path / "other"
    root.mkdir()
    other.mkdir()

    session = LibraryService().open_session(root)

    assert session.connection_for(root) is session.db_conn
    assert session.connection_for(str(root)) is session.db_conn
    with pytest.raises(ValueError):
        session.connection_for(other)


def test_open_library_contexts_do_not_follow_current_library(tmp_path):
    from AssetsManager.application.library_service import LibraryService

    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()

    service = LibraryService()
    first = service.open_library(first_root)
    second = service.open_library(second_root)

    assert first is not second
    assert first.root == first_root.resolve()
    assert second.root == second_root.resolve()
    assert first.db_conn is service._db.connection_for(first_root)
    assert second.db_conn is service._db.connection_for(second_root)
    assert first.db_conn is not second.db_conn
    assert first.data_dir == service._db.data_dir_for(first_root)
    assert second.data_dir == service._db.data_dir_for(second_root)


def test_open_library_context_resources_share_explicit_connection(tmp_path):
    from AssetsManager.application.library_service import LibraryService

    root = tmp_path / "library"
    root.mkdir()

    context = LibraryService().open_library(root)

    assert context.tag_store._db is context.db_conn
    assert context.project_data._db is context.db_conn


def test_library_context_connection_provider_rejects_mismatched_root(tmp_path):
    from AssetsManager.application.library_service import LibraryService

    root = tmp_path / "library"
    other = tmp_path / "other"
    root.mkdir()
    other.mkdir()

    context = LibraryService().open_library(root)

    assert context.connection_for(root) is context.db_conn
    assert context.connection_for(str(root)) is context.db_conn
    with pytest.raises(ValueError):
        context.connection_for(other)


def test_close_clears_current_session(tmp_path):
    from AssetsManager.application.library_service import LibraryService

    root = tmp_path / "library"
    root.mkdir()

    service = LibraryService()
    service.open_session(root)
    service.close()

    assert service.current_session is None


def test_session_is_not_closed_by_default(tmp_path):
    from AssetsManager.application.library_service import LibraryService

    root = tmp_path / "library"
    root.mkdir()

    session = LibraryService().open_session(root)

    assert session.is_closed is False


def test_session_close_marks_closed(tmp_path):
    from AssetsManager.application.library_service import LibraryService

    root = tmp_path / "library"
    root.mkdir()

    session = LibraryService().open_session(root)
    session.close()

    assert session.is_closed is True


def test_session_close_is_idempotent(tmp_path):
    from AssetsManager.application.library_service import LibraryService

    root = tmp_path / "library"
    root.mkdir()

    session = LibraryService().open_session(root)
    session.close()
    session.close()

    assert session.is_closed is True


def test_closed_session_still_exposes_resources(tmp_path):
    from AssetsManager.application.library_service import LibraryService

    root = tmp_path / "library"
    root.mkdir()

    session = LibraryService().open_session(root)
    session.close()

    assert session.root == root.resolve()
    assert session.is_closed is True

    import pytest
    with pytest.raises(RuntimeError, match="closed"):
        _ = session.db_conn
    with pytest.raises(RuntimeError, match="closed"):
        _ = session.tag_store
    with pytest.raises(RuntimeError, match="closed"):
        _ = session.project_data
    with pytest.raises(RuntimeError, match="closed"):
        session.connection_for(root)


def test_session_close_does_not_affect_other_sessions(tmp_path):
    from AssetsManager.application.library_service import LibraryService

    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()

    service = LibraryService()
    first = service.open_session(first_root)
    second = service.open_session(second_root)

    first.close()

    assert first.is_closed is True
    assert second.is_closed is False
    assert second.root == second_root.resolve()


def test_library_service_close_session_removes_context(tmp_path):
    from AssetsManager.application.library_service import LibraryService

    root = tmp_path / "library"
    root.mkdir()

    service = LibraryService()
    session = service.open_session(root)

    assert service.current_session is not None
    service.close_session(session)
    assert service.current_session is None


def test_library_service_close_session_is_idempotent(tmp_path):
    from AssetsManager.application.library_service import LibraryService

    root = tmp_path / "library"
    root.mkdir()

    service = LibraryService()
    session = service.open_session(root)

    service.close_session(session)
    service.close_session(session)

    assert service.current_session is None
