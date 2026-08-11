"""AssetIndexRepository session/root binding regressions."""

from __future__ import annotations

import sqlite3
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from AssetsManager.application import ApplicationBootstrap
from AssetsManager.repositories.asset_index_repository import (
    AssetIndexRepository,
    AssetIndexRevisionConflict,
)


def _entry(root, name="asset.txt"):
    path = root / name
    return (
        str(path),
        name,
        path.suffix,
        "file",
        1,
        1.0,
        str(root),
        str(root),
        1.0,
        1.0,
    )


def _fake_session(root, conn):
    return SimpleNamespace(
        root=root,
        root_str=str(root),
        connection_for=lambda _root: conn,
        operation=nullcontext,
    )



class _CommitFailingConnection(sqlite3.Connection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_commit = True
        self.rollback_count = 0

    def commit(self):
        if self.fail_commit:
            raise sqlite3.OperationalError("injected commit failure")
        return super().commit()

    def rollback(self):
        self.rollback_count += 1
        return super().rollback()


def test_repository_write_rolls_back_when_commit_fails():
    conn = sqlite3.connect(":memory:", factory=_CommitFailingConnection)
    conn.execute(
        "CREATE TABLE assets ("
        "file_path TEXT NOT NULL UNIQUE, name TEXT NOT NULL, extension TEXT NOT NULL, "
        "kind TEXT NOT NULL, size INTEGER, mtime REAL, parent_path TEXT NOT NULL, "
        "library_root TEXT NOT NULL, created_at REAL, updated_at REAL)"
    )
    conn.execute(
        "CREATE TABLE asset_index_state ("
        "library_root TEXT PRIMARY KEY NOT NULL, revision INTEGER NOT NULL DEFAULT 0, "
        "updated_at REAL NOT NULL)"
    )
    repo = AssetIndexRepository(conn)
    try:
        with pytest.raises(sqlite3.OperationalError, match="injected commit failure"):
            repo.replace_parent_entries(
                "/library", "/library", [_entry(Path("/library"))],
                clear_existing=True,
            )
        assert conn.rollback_count >= 1
        assert conn.in_transaction is False
        assert conn.execute("SELECT COUNT(*) FROM assets").fetchone() == (0,)
    finally:
        conn.close()


def test_repository_savepoint_rolls_back_when_commit_fails():
    conn = sqlite3.connect(":memory:", factory=_CommitFailingConnection)
    conn.execute("CREATE TABLE values_table (value TEXT NOT NULL)")
    repo = AssetIndexRepository(conn)
    try:
        with pytest.raises(sqlite3.OperationalError, match="injected commit failure"):
            with repo.transaction_scope(savepoint="asset_tree"):
                conn.execute("INSERT INTO values_table VALUES ('stale')")
        assert conn.rollback_count >= 1
        assert conn.in_transaction is False
        assert conn.execute("SELECT COUNT(*) FROM values_table").fetchone() == (0,)
    finally:
        conn.close()

def test_for_session_binds_same_managed_connection_and_root(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        repo = AssetIndexRepository.for_session(session)
        assert repo._session is session
        assert repo._conn is session.connection_for(session.root)
        assert repo._root_identity == session.context.root_identity

        repo.replace_parent_entries(
            str(session.root), str(session.root), [_entry(session.root)], clear_existing=True
        )
        assert repo.count(str(session.root)) == 1
        assert repo.get_entry(str(session.root / "asset.txt")) is not None
    finally:
        bootstrap.library_service.close()


def test_canonical_factory_rejects_fake_and_unmanaged_sessions(tmp_path):
    conn = sqlite3.connect(":memory:")
    fake = _fake_session(tmp_path / "library", conn)
    try:
        with pytest.raises(TypeError, match="registered LibrarySession"):
            AssetIndexRepository.for_session(fake)
    finally:
        conn.close()


def test_canonical_repository_rejects_foreign_session_and_root(tmp_path):
    bootstrap = ApplicationBootstrap()
    first = bootstrap.library_service.open_session(tmp_path / "first")
    second = bootstrap.library_service.open_session(tmp_path / "second")
    try:
        conn = first.connection_for(first.root)
        with pytest.raises(ValueError, match=r"(?i)(different|belong|connection)"):
            AssetIndexRepository(conn, session=second)

        repo = AssetIndexRepository.for_session(first)
        with pytest.raises(ValueError, match=r"(?i)(match|bound|different)"):
            repo.count(str(second.root))
        with pytest.raises(ValueError, match=r"(?i)(under|bound|belong)"):
            repo.get_entry(str(second.root / "outside.txt"))
    finally:
        bootstrap.library_service.close()


def test_commit_false_preserves_caller_transaction_boundary(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        repo = AssetIndexRepository.for_session(session)
        conn = session.connection_for(session.root)
        repo.replace_parent_entries(
            str(session.root), str(session.root), [_entry(session.root)],
            clear_existing=True,
            commit=False,
        )
        assert conn.in_transaction is True
        assert repo.count(str(session.root)) == 1
        conn.rollback()
        assert repo.count(str(session.root)) == 0
    finally:
        bootstrap.library_service.close()


def test_raw_repository_does_not_commit_existing_caller_transaction(tmp_path, schema_db):
    library = tmp_path / "library"
    library.mkdir()
    schema_db.execute("CREATE TABLE caller_data (value TEXT NOT NULL)")
    schema_db.commit()
    schema_db.execute("BEGIN")
    schema_db.execute("INSERT INTO caller_data VALUES ('keep-me')")

    repo = AssetIndexRepository(schema_db)
    repo.replace_parent_entries(
        str(library), str(library), [_entry(library)], clear_existing=True
    )

    assert schema_db.in_transaction is True
    assert schema_db.execute("SELECT * FROM caller_data").fetchall() == [
        ("keep-me",)
    ]
    schema_db.rollback()
    assert schema_db.execute("SELECT * FROM caller_data").fetchall() == []
    assert repo.current_revision(library) == 0
    assert repo.count(str(library)) == 0


def test_raw_delete_rejects_without_bound_root(tmp_path, schema_db):
    library = tmp_path / "library"
    library.mkdir()
    bound = AssetIndexRepository(schema_db, library_root=library)
    unbound = AssetIndexRepository(schema_db)

    bound.replace_parent_entries(
        str(library), str(library), [_entry(library)], clear_existing=True
    )
    assert bound.current_revision(library) == 1

    # M9-Bug9: a root-less raw delete would span every indexed library; it is
    # rejected instead.  The bound delete advances the matching root revision.
    with pytest.raises(ValueError, match="library_root"):
        unbound.delete_entry(library / "asset.txt")
    with pytest.raises(ValueError, match="library_root"):
        unbound.delete_path(str(library))
    assert bound.get_entry(library / "asset.txt") is not None

    assert bound.delete_entry(library / "asset.txt") == 1
    assert bound.current_revision(library) == 2


def test_bound_repository_revision_cas_rejects_stale_writer(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        repo = AssetIndexRepository.for_session(session)
        root = session.root
        first = _entry(root, "first.txt")
        second = _entry(root, "second.txt")

        assert repo.current_revision(root) == 0
        repo.replace_parent_entries(
            str(root), str(root), [first], clear_existing=True, expected_revision=0
        )
        assert repo.current_revision(root) == 1

        with pytest.raises(AssetIndexRevisionConflict, match="expected 0, found 1"):
            repo.replace_parent_entries(
                str(root), str(root), [second], clear_existing=True, expected_revision=0
            )

        assert repo.current_revision(root) == 1
        assert repo.get_entry(root / "first.txt") is not None
        assert repo.get_entry(root / "second.txt") is None

        repo.delete_entry(root / "first.txt")
        assert repo.current_revision(root) == 2
    finally:
        bootstrap.library_service.close()


def test_closed_session_rejects_bound_repository_operations(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    repo = AssetIndexRepository.for_session(session)
    session.close()
    try:
        with pytest.raises(RuntimeError, match="closed LibrarySession"):
            repo.count(str(session.root))
    finally:
        bootstrap.library_service.close()
