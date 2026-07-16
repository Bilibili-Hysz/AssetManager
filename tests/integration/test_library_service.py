from pathlib import Path
import threading

import pytest


def test_open_library_returns_context(tmp_path):
    from AssetsManager.application.library_service import LibraryService

    root = tmp_path / "library"
    root.mkdir()

    service = LibraryService()
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
    from AssetsManager.application.library_service import LibraryService

    root = tmp_path / "library"
    root.mkdir()

    service = LibraryService()
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


@pytest.mark.parametrize("close_all", [False, True], ids=["close_session", "close"])
def test_open_session_survives_close_during_library_open_event(
    tmp_path, monkeypatch, close_all
):
    from concurrent.futures import ThreadPoolExecutor

    import AssetsManager.application.library_service as library_service_module

    root = tmp_path / "library"
    root.mkdir()
    service = library_service_module.LibraryService()

    class ClosingEventBus:
        def publish(self, event):
            session = service.current_session
            assert session is not None
            close = service.close if close_all else lambda: service.close_session(session)
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(close).result()

    monkeypatch.setattr(
        library_service_module, "get_event_bus", lambda: ClosingEventBus()
    )

    session = service.open_session(root)

    assert session.root == root.resolve()
    assert session.is_closed is True


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


def test_session_close_removes_owned_canonical_session(tmp_path):
    from AssetsManager.application.library_service import LibraryService

    root = tmp_path / "library"
    root.mkdir()
    service = LibraryService()
    session = service.open_session(root)

    session.close()

    assert service.current_session is None
    replacement = service.open_session(root)
    assert replacement is not session
    assert replacement.is_closed is False


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


def test_library_service_close_session_closes_library_connection(tmp_path):
    from AssetsManager.application.library_service import LibraryService

    root = tmp_path / "library"
    root.mkdir()

    service = LibraryService()
    session = service.open_session(root)
    conn = session.db_conn

    service.close_session(session)

    import sqlite3
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_close_session_serializes_same_root_reopen_through_db_teardown(
    tmp_path, monkeypatch
):
    from AssetsManager.application.library_service import LibraryService

    root = tmp_path / "library"
    root.mkdir()
    service = LibraryService()
    session = service.open_session(root)
    old_conn = session.db_conn
    teardown_started = threading.Event()
    allow_teardown = threading.Event()
    reopen_started = threading.Event()
    connection_requested = threading.Event()
    reopened: list = []
    original_close_library = service._db.close_library
    original_connection_for = service._db.connection_for

    def blocking_close_library(root_path):
        teardown_started.set()
        assert allow_teardown.wait(5)
        original_close_library(root_path)

    def tracked_connection_for(root_path):
        connection_requested.set()
        return original_connection_for(root_path)

    monkeypatch.setattr(service._db, "close_library", blocking_close_library)
    monkeypatch.setattr(service._db, "connection_for", tracked_connection_for)

    close_thread = threading.Thread(target=service.close_session, args=(session,))

    def reopen():
        reopen_started.set()
        reopened.append(service.open_session(root))

    reopen_thread = threading.Thread(target=reopen)
    close_thread.start()
    assert teardown_started.wait(5)
    reopen_thread.start()
    assert reopen_started.wait(5)
    try:
        assert not connection_requested.wait(0.2)
    finally:
        allow_teardown.set()
    close_thread.join(5)
    reopen_thread.join(5)

    assert not close_thread.is_alive()
    assert not reopen_thread.is_alive()
    assert reopened[0].db_conn is not old_conn
    reopened[0].db_conn.execute("SELECT 1")


def test_direct_session_close_serializes_same_root_reopen_through_db_teardown(
    tmp_path, monkeypatch
):
    from AssetsManager.application.library_service import LibraryService

    root = tmp_path / "library"
    root.mkdir()
    service = LibraryService()
    session = service.open_session(root)
    old_conn = session.db_conn
    teardown_started = threading.Event()
    allow_teardown = threading.Event()
    reopen_started = threading.Event()
    connection_requested = threading.Event()
    reopened: list = []
    original_close_library = service._db.close_library
    original_connection_for = service._db.connection_for

    def blocking_close_library(root_path):
        teardown_started.set()
        assert allow_teardown.wait(5)
        original_close_library(root_path)

    def tracked_connection_for(root_path):
        connection_requested.set()
        return original_connection_for(root_path)

    monkeypatch.setattr(service._db, "close_library", blocking_close_library)
    monkeypatch.setattr(service._db, "connection_for", tracked_connection_for)

    close_thread = threading.Thread(target=session.close)

    def reopen():
        reopen_started.set()
        reopened.append(service.open_session(root))

    reopen_thread = threading.Thread(target=reopen)
    close_thread.start()
    assert teardown_started.wait(5)
    reopen_thread.start()
    assert reopen_started.wait(5)
    try:
        assert not connection_requested.wait(0.2)
    finally:
        allow_teardown.set()
    close_thread.join(5)
    reopen_thread.join(5)

    assert not close_thread.is_alive()
    assert not reopen_thread.is_alive()
    assert reopened[0] is not session
    assert reopened[0].is_closed is False
    assert reopened[0].db_conn is not old_conn
    reopened[0].db_conn.execute("SELECT 1")


def test_close_serializes_same_root_reopen_through_db_teardown(tmp_path, monkeypatch):
    from AssetsManager.application.library_service import LibraryService

    root = tmp_path / "library"
    root.mkdir()
    service = LibraryService()
    session = service.open_session(root)
    old_conn = session.db_conn
    teardown_started = threading.Event()
    allow_teardown = threading.Event()
    reopen_started = threading.Event()
    connection_requested = threading.Event()
    reopened: list = []
    original_close = service._db.close
    original_connection_for = service._db.connection_for

    def blocking_close():
        teardown_started.set()
        assert allow_teardown.wait(5)
        original_close()

    def tracked_connection_for(root_path):
        connection_requested.set()
        return original_connection_for(root_path)

    monkeypatch.setattr(service._db, "close", blocking_close)
    monkeypatch.setattr(service._db, "connection_for", tracked_connection_for)

    close_thread = threading.Thread(target=service.close)

    def reopen():
        reopen_started.set()
        reopened.append(service.open_session(root))

    reopen_thread = threading.Thread(target=reopen)
    close_thread.start()
    assert teardown_started.wait(5)
    reopen_thread.start()
    assert reopen_started.wait(5)
    try:
        assert not connection_requested.wait(0.2)
    finally:
        allow_teardown.set()
    close_thread.join(5)
    reopen_thread.join(5)

    assert not close_thread.is_alive()
    assert not reopen_thread.is_alive()
    assert reopened[0].db_conn is not old_conn
    reopened[0].db_conn.execute("SELECT 1")


def test_library_service_close_session_is_idempotent(tmp_path):
    from AssetsManager.application.library_service import LibraryService

    root = tmp_path / "library"
    root.mkdir()

    service = LibraryService()
    session = service.open_session(root)

    service.close_session(session)
    service.close_session(session)

    assert service.current_session is None


def test_close_session_for_stale_identity_preserves_replacement(tmp_path):
    from AssetsManager.application.library_service import LibraryService

    root = tmp_path / "library"
    root.mkdir()

    service = LibraryService()
    old = service.open_session(root)
    old.close()
    replacement = service.open_session(root)

    service.close_session(old)

    assert service.current_session is replacement
    assert service.open_session(root) is replacement
    assert replacement.context is not old.context
    replacement.db_conn.execute("SELECT 1")


def test_open_library_replaces_directly_closed_canonical_session_and_context(tmp_path):
    from AssetsManager.application.library_service import LibraryService

    root = tmp_path / "library"
    root.mkdir()

    service = LibraryService()
    session = service.open_session(root)
    context = session.context
    session.close()

    reopened_context = service.open_library(root)
    replacement = service.current_session

    assert reopened_context is not context
    assert replacement is not None
    assert replacement is not session
    assert replacement.is_closed is False
    assert service.open_session(root) is replacement


# ── Phase 2.5: Per-library database teardown ──────────────────────

def test_close_session_does_not_close_other_library_connections(tmp_path):
    """Closing one library must not close another library's DB connection."""
    from AssetsManager.application.library_service import LibraryService

    lib_a = tmp_path / "lib_a"
    lib_b = tmp_path / "lib_b"
    lib_a.mkdir()
    lib_b.mkdir()

    service = LibraryService()
    session_a = service.open_session(lib_a)
    session_b = service.open_session(lib_b)

    conn_a = session_a.db_conn
    conn_b = session_b.db_conn

    # Close library A
    service.close_session(session_a)

    # Library A connection should be closed
    import sqlite3
    with pytest.raises(sqlite3.ProgrammingError):
        conn_a.execute("SELECT 1")

    # Library B connection should still be alive
    conn_b.execute("SELECT 1")

    service.close_session(session_b)


@pytest.mark.parametrize(
    ("service_name", "method_name", "arguments", "block_target"),
    [
        ("metadata_service", "get_notes", lambda root: (root, root / "asset.txt"), "_repo"),
        ("tag_service", "list_tags", lambda root: (root,), "_connection_provider"),
        ("project_service", "count_projects", lambda root: (root,), "_count_projects_recursive"),
        ("file_operation_service", "create_folder", lambda root: (root,), "create_folder"),
        ("undo_service", "prepare_delete", lambda root: (str(root / "asset.txt"),), "_make_backup"),
    ],
)
@pytest.mark.parametrize("direct_close", [False, True], ids=["close_session", "session_close"])
def test_scoped_public_operation_lease_drains_before_close(
    tmp_path, monkeypatch, service_name, method_name, arguments, block_target, direct_close
):
    from AssetsManager.application import ApplicationBootstrap

    root = tmp_path / f"library-{service_name}-{direct_close}"
    root.mkdir()
    (root / "asset.txt").write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(root)
    scoped = bootstrap.for_library(session)
    target = getattr(scoped, service_name)
    entered = threading.Event()
    release = threading.Event()
    operation_done = threading.Event()
    close_done = threading.Event()

    if service_name == "metadata_service":
        original = target._repo

        def blocking_repo(*args, **kwargs):
            repo = original(*args, **kwargs)
            original_get_notes = repo.get_notes

            def get_notes(*repo_args, **repo_kwargs):
                entered.set()
                assert release.wait(5)
                return original_get_notes(*repo_args, **repo_kwargs)

            repo.get_notes = get_notes
            return repo

        monkeypatch.setattr(target, block_target, blocking_repo)
    elif service_name == "tag_service":
        original = target._connection_provider

        def blocking_provider(*args, **kwargs):
            conn = original(*args, **kwargs)
            entered.set()
            assert release.wait(5)
            return conn

        monkeypatch.setattr(target, block_target, blocking_provider)
    elif service_name == "project_service":
        original = target._count_projects_recursive

        def blocking_count(*args, **kwargs):
            entered.set()
            assert release.wait(5)
            return original(*args, **kwargs)

        monkeypatch.setattr(target, block_target, blocking_count)
    elif service_name == "file_operation_service":
        import AssetsManager.application.file_operation_service as file_operations_module

        original = file_operations_module.unique_destination

        def blocking_create(*args, **kwargs):
            entered.set()
            assert release.wait(5)
            return original(*args, **kwargs)

        monkeypatch.setattr(file_operations_module, "unique_destination", blocking_create)
    else:
        original = target._make_backup

        def blocking_backup(*args, **kwargs):
            entered.set()
            assert release.wait(5)
            return original(*args, **kwargs)

        monkeypatch.setattr(target, block_target, blocking_backup)

    operation = threading.Thread(
        target=lambda: (getattr(target, method_name)(*arguments(root)), operation_done.set())
    )
    operation.start()
    assert entered.wait(5)
    close = session.close if direct_close else lambda: bootstrap.library_service.close_session(session)
    closer = threading.Thread(target=lambda: (close(), close_done.set()))
    closer.start()
    try:
        assert not close_done.wait(0.2)
        assert session.is_closed
        with pytest.raises(RuntimeError, match="closed"):
            getattr(target, method_name)(*arguments(root))
    finally:
        release.set()
    assert operation_done.wait(5)
    assert close_done.wait(5)
    operation.join(5)
    closer.join(5)


def test_stale_duplicate_close_drains_without_blocking_other_root_open(tmp_path):
    from AssetsManager.application import ApplicationBootstrap

    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    bootstrap = ApplicationBootstrap()
    first = bootstrap.library_service.open_session(first_root)
    entered = threading.Event()
    release = threading.Event()

    def operation():
        with first.operation():
            entered.set()
            assert release.wait(5)

    worker = threading.Thread(target=operation)
    worker.start()
    assert entered.wait(5)
    first_closer = threading.Thread(target=lambda: bootstrap.library_service.close_session(first))
    first_closer.start()
    for _ in range(100):
        if first.is_closed:
            break
        threading.Event().wait(0.01)
    assert first.is_closed
    stale_closer = threading.Thread(target=lambda: bootstrap.library_service.close_session(first))
    stale_closer.start()
    second = bootstrap.library_service.open_session(second_root)
    assert second.root == second_root.resolve()
    release.set()
    worker.join(5)
    first_closer.join(5)
    stale_closer.join(5)


def test_duplicate_direct_close_waits_for_active_operation(tmp_path):
    from AssetsManager.application.library_service import LibraryService

    root = tmp_path / "library"
    root.mkdir()
    session = LibraryService().open_session(root)
    entered = threading.Event()
    release = threading.Event()
    first_done = threading.Event()
    duplicate_done = threading.Event()

    def operation():
        with session.operation():
            entered.set()
            assert release.wait(5)

    worker = threading.Thread(target=operation)
    worker.start()
    assert entered.wait(5)
    first = threading.Thread(target=lambda: (session.close(), first_done.set()))
    first.start()
    for _ in range(100):
        if session.is_closed:
            break
        threading.Event().wait(0.01)
    duplicate = threading.Thread(target=lambda: (session.close(), duplicate_done.set()))
    duplicate.start()
    assert not first_done.wait(0.2)
    assert not duplicate_done.wait(0.2)
    release.set()
    worker.join(5)
    first.join(5)
    duplicate.join(5)
    assert first_done.is_set()
    assert duplicate_done.is_set()

def test_library_context_not_in_public_application_exports():
    """LibraryContext should not be in the public application __all__."""
    from AssetsManager import application
    assert hasattr(application, "__all__"), "application package must have __all__"
    assert "LibraryContext" not in application.__all__, (
        "LibraryContext must not be in __all__; LibrarySession is the public boundary"
    )


def test_open_library_emits_deprecation_warning():
    """open_library() is legacy and must emit a DeprecationWarning."""
    import warnings
    from AssetsManager.application.library_service import LibraryService
    from pathlib import Path
    import tempfile

    root = Path(tempfile.mkdtemp())
    service = LibraryService()
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        service.open_library(root)
        deprecations = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert len(deprecations) >= 1, "open_library() must emit a DeprecationWarning"
    service.close()


def test_current_property_emits_deprecation_warning():
    """LibraryService.current is legacy and must emit a DeprecationWarning."""
    import warnings
    from AssetsManager.application.library_service import LibraryService

    service = LibraryService()
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        _ = service.current
        deprecations = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert len(deprecations) >= 1, "LibraryService.current must emit a DeprecationWarning"
