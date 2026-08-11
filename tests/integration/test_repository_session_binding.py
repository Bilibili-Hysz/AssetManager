"""Direct repository session/root binding regressions."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace
from typing import Any, cast

import pytest

from AssetsManager.application import ApplicationBootstrap
from AssetsManager.repositories.auth_repository import AuthRepository
from AssetsManager.repositories.share_repository import ShareRepository


def _init_auth(repo) -> None:
    repo.init_tables()


def _init_share(repo) -> None:
    repo.init_table()


def _read_auth(repo):
    return repo.list_users()


def _read_share(repo):
    return repo.list_all()


def _write_auth(repo, suffix: str):
    return repo.insert_user(f"user-{suffix}", "password-hash")


def _write_share(repo, suffix: str):
    return repo.insert(
        f"share-{suffix}",
        ["project"],
        None,
        None,
        None,
        True,
        None,
    )


_REPOSITORIES = [
    (AuthRepository, _init_auth, _read_auth, _write_auth),
    (ShareRepository, _init_share, _read_share, _write_share),
]


def _fake_session(root, conn):
    return SimpleNamespace(
        root=root,
        root_str=str(root),
        event_token="fake-session-token",
        connection_for=lambda _root: conn,
        operation=nullcontext,
    )


def test_for_session_same_root_managed_success(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        conn = session.connection_for(session.root)
        for repository_type, initialize, _read, _write in _REPOSITORIES:
            factory_repo = repository_type.for_session(session)
            constructor_repo = repository_type(conn, session=session)

            assert factory_repo._session is session
            assert constructor_repo._session is session
            assert factory_repo._conn is conn
            assert constructor_repo._conn is conn
            initialize(factory_repo)
            initialize(constructor_repo)
    finally:
        bootstrap.library_service.close()


@pytest.mark.parametrize("repository_type", [AuthRepository, ShareRepository], ids=["auth", "share"])
@pytest.mark.parametrize("entry_point", ["factory", "constructor"])
def test_unmanaged_connection_is_rejected_for_session_bound_repository(
    repository_type, entry_point, tmp_path
):
    conn = sqlite3.connect(":memory:")
    session = _fake_session(tmp_path / "library", conn)
    try:
        with pytest.raises(
            RuntimeError,
            match=r"(?i)(managed|unmanaged|ownership)",
        ):
            if entry_point == "factory":
                repository_type.for_session(session)
            else:
                repository_type(conn, session=session)
    finally:
        conn.close()


@pytest.mark.parametrize(
    "repository_type",
    [AuthRepository, ShareRepository],
    ids=["auth", "share"],
)
def test_real_sessions_reject_foreign_managed_connection(repository_type, tmp_path):
    bootstrap = ApplicationBootstrap()
    first = bootstrap.library_service.open_session(tmp_path / "first")
    second = bootstrap.library_service.open_session(tmp_path / "second")
    try:
        foreign_connection = first.connection_for(first.root)
        with pytest.raises(
            ValueError,
            match=r"(?i)(different|belong|root|connection)",
        ):
            repository_type(foreign_connection, session=second)
    finally:
        bootstrap.library_service.close()


@pytest.mark.parametrize(
    "repository_type",
    [AuthRepository, ShareRepository],
    ids=["auth", "share"],
)
def test_explicit_library_root_must_match_session_root(repository_type, tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        conn = session.connection_for(session.root)
        with pytest.raises(
            ValueError,
            match=r"(?i)(different|belong|root|connection)",
        ):
            repository_type(
                conn,
                library_root=tmp_path / "another-library",
                session=session,
            )
    finally:
        bootstrap.library_service.close()


@pytest.mark.parametrize("repository_type", [AuthRepository, ShareRepository], ids=["auth", "share"])
def test_repository_rebinding_same_session_is_idempotent_but_second_session_is_rejected(
    repository_type, tmp_path
):
    bootstrap = ApplicationBootstrap()
    first = bootstrap.library_service.open_session(tmp_path / "first")
    second = bootstrap.library_service.open_session(tmp_path / "second")
    try:
        repository = repository_type.for_session(first)

        assert repository._bind_session(first) is None
        with pytest.raises(RuntimeError, match=r"(?i)(already bound|another|session)"):
            repository._bind_session(second)
    finally:
        bootstrap.library_service.close()


@pytest.mark.parametrize(
    "repository_type",
    [AuthRepository, ShareRepository],
    ids=["auth", "share"],
)
def test_repository_binding_is_not_published_for_closing_session(
    repository_type, tmp_path
):
    bootstrap = ApplicationBootstrap()
    real_session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        conn = real_session.connection_for(real_session.root)

        def reject_publication(_callback):
            raise RuntimeError("Cannot publish services for a closing LibrarySession")

        session = SimpleNamespace(
            root=real_session.root,
            root_str=real_session.root_str,
            connection_for=lambda _root: conn,
            operation=nullcontext,
            _publish_while_live=reject_publication,
        )
        repository = repository_type(conn)

        with pytest.raises(RuntimeError, match="closing LibrarySession"):
            repository._bind_session(session)

        assert repository._session is None
        assert repository._library_root_key is None
    finally:
        bootstrap.library_service.close()


@pytest.mark.parametrize(
    "repository_type",
    [AuthRepository, ShareRepository],
    ids=["auth", "share"],
)
def test_concurrent_second_session_bind_is_serialized(repository_type, tmp_path):
    bootstrap = ApplicationBootstrap()
    real_session = bootstrap.library_service.open_session(tmp_path / "library")
    release_first = threading.Event()
    first_entered = threading.Event()
    second_entered = threading.Event()
    first_errors: list[BaseException] = []
    second_errors: list[BaseException] = []
    first_thread: threading.Thread | None = None
    second_thread: threading.Thread | None = None
    try:
        conn = real_session.connection_for(real_session.root)

        @contextmanager
        def first_operation():
            first_entered.set()
            if not release_first.wait(timeout=5):
                raise TimeoutError("first repository bind was not released")
            yield

        @contextmanager
        def second_operation():
            second_entered.set()
            yield

        first_session = SimpleNamespace(
            root=real_session.root,
            root_str=real_session.root_str,
            connection_for=lambda _root: conn,
            operation=first_operation,
        )
        second_session = SimpleNamespace(
            root=real_session.root,
            root_str=real_session.root_str,
            connection_for=lambda _root: conn,
            operation=second_operation,
        )
        repository = repository_type(conn)

        def bind_first() -> None:
            try:
                repository._bind_session(first_session)
            except BaseException as exc:  # pragma: no cover - asserted below
                first_errors.append(exc)

        def bind_second() -> None:
            try:
                repository._bind_session(second_session)
            except BaseException as exc:  # pragma: no cover - asserted below
                second_errors.append(exc)

        first_thread = threading.Thread(target=bind_first)
        first_thread.start()
        assert first_entered.wait(timeout=5)

        second_thread = threading.Thread(target=bind_second)
        second_thread.start()
        assert second_entered.wait(timeout=0.1) is False

        release_first.set()
        first_thread.join(timeout=5)
        second_thread.join(timeout=5)

        assert not first_thread.is_alive()
        assert not second_thread.is_alive()
        assert first_errors == []
        assert len(second_errors) == 1
        assert isinstance(second_errors[0], RuntimeError)
        assert repository._session is first_session
        assert second_entered.is_set() is False
    finally:
        release_first.set()
        if first_thread is not None:
            first_thread.join(timeout=5)
        if second_thread is not None:
            second_thread.join(timeout=5)
        bootstrap.library_service.close()


@pytest.mark.parametrize(
    "repository_type,initialize,read,write",
    _REPOSITORIES,
    ids=["auth", "share"],
)
def test_session_close_rejects_read_write_and_init_before_sqlite_mutation(
    repository_type, initialize, read, write, tmp_path
):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        repository = repository_type.for_session(session)
        initialize(repository)
        conn = repository._conn
        statements: list[str] = []
        conn.set_trace_callback(statements.append)
        statements.clear()

        session.close()

        operations = (
            lambda: read(repository),
            lambda: write(repository, "after-close"),
            lambda: initialize(repository),
        )
        for operation in operations:
            with pytest.raises(RuntimeError, match="closed LibrarySession"):
                operation()
        assert statements == []
    finally:
        bootstrap.library_service.close()


@pytest.mark.parametrize(
    "repository_type,initialize,read",
    [
        pytest.param(AuthRepository, _init_auth, _read_auth, id="auth"),
        pytest.param(ShareRepository, _init_share, _read_share, id="share"),
    ],
)
def test_in_flight_repository_operation_holds_lease_until_release(
    repository_type, initialize, read, tmp_path
):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    worker_errors: list[BaseException] = []
    close_errors: list[BaseException] = []
    release_operation = threading.Event()
    worker: threading.Thread | None = None
    closer: threading.Thread | None = None
    try:
        repository = repository_type.for_session(session)
        initialize(repository)
        conn = repository._conn

        operation_entered = threading.Event()
        begin_close = threading.Event()
        close_done = threading.Event()

        def trace(statement: str) -> None:
            if operation_entered.is_set() or not statement.lstrip().upper().startswith("SELECT"):
                return
            operation_entered.set()
            if not release_operation.wait(timeout=5):
                worker_errors.append(TimeoutError("blocked repository operation was not released"))

        original_begin_close = session._begin_close

        def instrumented_begin_close() -> None:
            original_begin_close()
            begin_close.set()

        object.__setattr__(session, "_begin_close", instrumented_begin_close)
        conn.set_trace_callback(trace)

        def run_operation() -> None:
            try:
                read(repository)
            except BaseException as exc:  # pragma: no cover - assertion below reports it
                worker_errors.append(exc)

        def close_session() -> None:
            try:
                session.close()
            except BaseException as exc:  # pragma: no cover - assertion below reports it
                close_errors.append(exc)
            finally:
                close_done.set()

        worker = threading.Thread(target=run_operation)
        worker.start()
        assert operation_entered.wait(timeout=5)

        closer = threading.Thread(target=close_session)
        closer.start()
        assert begin_close.wait(timeout=5)
        assert close_done.wait(timeout=0.1) is False

        with pytest.raises(RuntimeError, match="closed LibrarySession"):
            read(repository)

        release_operation.set()
        worker.join(timeout=5)
        closer.join(timeout=5)

        assert not worker.is_alive()
        assert not closer.is_alive()
        assert close_done.is_set()
        assert worker_errors == []
        assert close_errors == []
    finally:
        release_operation.set()
        if worker is not None:
            worker.join(timeout=5)
        if closer is not None:
            closer.join(timeout=5)
        bootstrap.library_service.close()


@pytest.mark.parametrize(
    "repository_type,initialize,read,write",
    _REPOSITORIES,
    ids=["auth", "share"],
)
def test_same_root_close_reopen_invalidates_old_repository_and_allows_new_one(
    repository_type, initialize, read, write, tmp_path
):
    bootstrap = ApplicationBootstrap()
    root = tmp_path / "library"
    first_session = bootstrap.library_service.open_session(root)
    try:
        old_repository = repository_type.for_session(first_session)
        initialize(old_repository)
        assert write(old_repository, "before-reopen")
        old_connection = old_repository._conn

        first_session.close()
        second_session = bootstrap.library_service.open_session(root)
        try:
            new_repository = repository_type.for_session(second_session)
            initialize(new_repository)
            assert new_repository._conn is not old_connection
            assert read(new_repository)
            assert write(new_repository, "after-reopen")

            for operation in (
                lambda: read(old_repository),
                lambda: write(old_repository, "old-repository"),
                lambda: initialize(old_repository),
            ):
                with pytest.raises(RuntimeError, match="closed LibrarySession"):
                    operation()
        finally:
            second_session.close()
    finally:
        bootstrap.library_service.close()


def test_library_context_root_identity_falls_back_when_root_key_is_omitted(tmp_path):
    from AssetsManager.application.context import LibraryContext
    from AssetsManager.core.path_resolver import root_identity

    conn = sqlite3.connect(":memory:")
    try:
        context = LibraryContext(
            root=tmp_path,
            data_dir=tmp_path / ".data",
            thumb_dir=tmp_path / ".thumbs",
            db_conn=conn,
            tag_store=cast(Any, SimpleNamespace()),
            project_data=cast(Any, SimpleNamespace()),
        )
        assert context.root_identity == root_identity(tmp_path, strict=False)
    finally:
        conn.close()
