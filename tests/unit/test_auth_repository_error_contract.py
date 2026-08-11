"""Error-contract tests for the authentication repository."""

from __future__ import annotations

import sqlite3

import pytest

from AssetsManager.repositories.auth_repository import AuthRepository
from AssetsManager.repositories.auth_repository import InviteCodeLookupError


def _ready_repo() -> tuple[sqlite3.Connection, AuthRepository]:
    conn = sqlite3.connect(":memory:")
    repo = AuthRepository(conn)
    repo.init_tables()
    return conn, repo


def test_reads_propagate_closed_connection_errors():
    conn, repo = _ready_repo()
    conn.close()

    with pytest.raises(sqlite3.ProgrammingError):
        repo.get_user_by_username("alice")
    with pytest.raises(sqlite3.ProgrammingError):
        repo.list_users()


def test_has_active_users_never_treats_database_failure_as_no_users():
    conn, repo = _ready_repo()
    conn.close()

    with pytest.raises(sqlite3.ProgrammingError):
        repo.has_active_users()
    with pytest.raises(sqlite3.ProgrammingError):
        repo.has_active_users(raise_on_error=False)


def test_has_active_users_rejects_schema_failure():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
    repo = AuthRepository(conn)

    with pytest.raises(sqlite3.OperationalError):
        repo.has_active_users()


def test_has_active_invite_codes_wraps_closed_connection_error():
    conn, repo = _ready_repo()
    conn.close()

    with pytest.raises(InviteCodeLookupError) as exc_info:
        repo.has_active_invite_codes()
    with pytest.raises(InviteCodeLookupError):
        repo.has_active_invite_codes(raise_on_error=False)

    assert isinstance(exc_info.value.__cause__, sqlite3.ProgrammingError)


def test_has_active_invite_codes_wraps_schema_failure():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE invite_codes (code TEXT PRIMARY KEY)")
    repo = AuthRepository(conn)

    with pytest.raises(InviteCodeLookupError) as exc_info:
        repo.has_active_invite_codes()

    assert isinstance(exc_info.value.__cause__, sqlite3.OperationalError)


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("insert_user", ("alice", "hash")),
        ("insert_user_with_invite", ("alice", "hash", "CODE")),
        ("insert_invite_code", ("CODE",)),
        ("consume_invite_code", ("CODE", "alice")),
    ],
)
def test_writes_propagate_closed_connection_errors(method: str, args: tuple[str, ...]):
    conn, repo = _ready_repo()
    conn.close()

    with pytest.raises((sqlite3.ProgrammingError, RuntimeError)):
        getattr(repo, method)(*args)


def test_insert_user_preserves_duplicate_username_business_failure():
    conn, repo = _ready_repo()
    assert repo.insert_user("alice", "hash") is not None

    assert repo.insert_user("alice", "different-hash") is None


def test_invite_business_failures_keep_boolean_contract():
    conn, repo = _ready_repo()
    assert repo.insert_invite_code("CODE") is True
    assert repo.insert_invite_code("CODE") is False
    assert repo.consume_invite_code("UNKNOWN", "alice") is False
    assert repo.consume_invite_code("CODE", "alice") is True
    assert repo.consume_invite_code("CODE", "bob") is False


class _NonSqliteFailingConnection(sqlite3.Connection):
    """Connection whose inserts fail with a non-sqlite programming error."""

    def execute(self, sql, parameters=()):
        if sql.lstrip().upper().startswith("INSERT"):
            raise ValueError("simulated non-sqlite failure")
        return super().execute(sql, parameters)


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("insert_user", ("alice", "hash")),
        ("insert_invite_code", ("CODE",)),
    ],
)
def test_unknown_write_failures_are_re_raised_not_swallowed(
    method: str, args: tuple[str, ...]
):
    conn = sqlite3.connect(":memory:", factory=_NonSqliteFailingConnection)
    repo = AuthRepository(conn)
    repo.init_tables()

    try:
        with pytest.raises(ValueError, match="simulated non-sqlite failure"):
            getattr(repo, method)(*args)
    finally:
        conn.close()
