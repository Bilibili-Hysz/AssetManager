"""Error-contract regression tests for share persistence and service entry points."""
from __future__ import annotations

import sqlite3

import pytest

from AssetsManager.application.share_service import ShareService
from AssetsManager.repositories.share_repository import ShareRepository


def _repository() -> tuple[sqlite3.Connection, ShareRepository]:
    conn = sqlite3.connect(":memory:")
    repo = ShareRepository(conn)
    repo.init_table()
    return conn, repo


def _insert_args(share_id: str = "share-1") -> tuple:
    return (share_id, ["project"], None, None, None, True, None)


def test_duplicate_insert_remains_a_business_failure() -> None:
    conn, repo = _repository()
    try:
        assert repo.insert(*_insert_args()) is True
        assert conn.in_transaction is False
        assert repo.insert(*_insert_args()) is False
        assert conn.in_transaction is False
    finally:
        conn.close()


def test_duplicate_insert_inside_outer_transaction_preserves_prior_writes() -> None:
    conn, repo = _repository()
    try:
        assert repo.insert(*_insert_args()) is True
        conn.execute("CREATE TABLE caller_data (value TEXT NOT NULL)")
        conn.commit()

        conn.execute("BEGIN")
        conn.execute("INSERT INTO caller_data VALUES ('keep-me')")
        assert conn.in_transaction is True

        assert repo.insert(*_insert_args()) is False

        assert conn.in_transaction is True
        assert conn.execute("SELECT value FROM caller_data").fetchall() == [
            ("keep-me",)
        ]
        assert conn.execute(
            "SELECT COUNT(*) FROM share_links WHERE id=?", ("share-1",)
        ).fetchone() == (1,)
    finally:
        conn.close()


def test_corrupted_paths_json_reads_as_empty_list() -> None:
    conn, repo = _repository()
    try:
        assert repo.insert(*_insert_args()) is True
        conn.execute("UPDATE share_links SET paths='{not-json' WHERE id='share-1'")
        conn.commit()

        share = repo.get("share-1")
        assert share is not None
        assert share["paths"] == []

        listed = repo.list_all()
        assert len(listed) == 1
        assert listed[0]["paths"] == []
    finally:
        conn.close()


def test_non_list_paths_json_reads_as_empty_list() -> None:
    conn, repo = _repository()
    try:
        assert repo.insert(*_insert_args()) is True
        conn.execute("UPDATE share_links SET paths='\"just-a-string\"' WHERE id='share-1'")
        conn.commit()

        assert repo.get("share-1")["paths"] == []
    finally:
        conn.close()


class _CleanupFailingConnection(sqlite3.Connection):
    fail_next_savepoint_rollback = False

    def execute(self, sql, parameters=()):
        if (
            self.fail_next_savepoint_rollback
            and sql.startswith("ROLLBACK TO SAVEPOINT")
        ):
            self.fail_next_savepoint_rollback = False
            raise sqlite3.OperationalError("simulated savepoint cleanup failure")
        return super().execute(sql, parameters)


def test_duplicate_insert_does_not_hide_savepoint_cleanup_failure() -> None:
    conn = sqlite3.connect(":memory:", factory=_CleanupFailingConnection)
    repo = ShareRepository(conn)
    repo.init_table()
    try:
        assert repo.insert(*_insert_args()) is True
        conn.fail_next_savepoint_rollback = True

        with pytest.raises(RuntimeError, match="restore the share insert transaction"):
            repo.insert(*_insert_args())

        assert conn.in_transaction is False
    finally:
        conn.close()


@pytest.mark.parametrize(
    "operation,expected",
    [
        (lambda repo: repo.get("missing"), sqlite3.ProgrammingError),
        (lambda repo: repo.list_all(), sqlite3.ProgrammingError),
        (lambda repo: repo.insert(*_insert_args()), RuntimeError),
        (lambda repo: repo.delete("missing"), RuntimeError),
        (lambda repo: repo.increment_download("missing"), RuntimeError),
        (lambda repo: repo.get_password_hash("missing"), sqlite3.ProgrammingError),
    ],
    ids=["get", "list", "insert", "delete", "increment", "password"],
)
def test_closed_connection_errors_are_not_converted_to_business_values(operation, expected) -> None:
    conn, repo = _repository()
    conn.close()

    with pytest.raises(expected):
        operation(repo)


@pytest.mark.parametrize(
    "operation",
    [
        lambda repo: repo.get("missing"),
        lambda repo: repo.list_all(),
        lambda repo: repo.insert(*_insert_args()),
        lambda repo: repo.delete("missing"),
        lambda repo: repo.increment_download("missing"),
        lambda repo: repo.get_password_hash("missing"),
    ],
    ids=["get", "list", "insert", "delete", "increment", "password"],
)
def test_schema_operational_errors_are_not_converted_to_business_values(operation) -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE share_links (id TEXT PRIMARY KEY)")
    conn.commit()
    repo = ShareRepository(conn)

    try:
        with pytest.raises(sqlite3.OperationalError):
            operation(repo)
    finally:
        conn.close()


@pytest.mark.parametrize(
    "method,args,expected",
    [
        ("create_share", (["project"],), sqlite3.ProgrammingError),
        ("get_share", ("missing",), sqlite3.ProgrammingError),
        ("get_share_record", ("missing",), sqlite3.ProgrammingError),
        ("list_shares", (), sqlite3.ProgrammingError),
        ("delete_share", ("missing",), RuntimeError),
        ("verify_password", ("missing", "password"), sqlite3.ProgrammingError),
        ("increment_download", ("missing",), RuntimeError),
        ("validate_access", ("missing", "project/file.txt"), sqlite3.ProgrammingError),
    ],
)
def test_share_service_propagates_closed_connection_errors(
    method: str, args: tuple, expected
) -> None:
    conn, _repo = _repository()
    service = ShareService(conn, "test-secret")
    conn.close()

    with pytest.raises(expected):
        getattr(service, method)(*args)
