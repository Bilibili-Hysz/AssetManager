"""Tests for AuthService."""

import pytest


def test_init_tables(schema_db):
    from AssetsManager.application.auth_service import AuthService

    conn = schema_db
    svc = AuthService(conn, "test-secret")
    svc.init_tables()

    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "users" in tables
    assert "invite_codes" in tables
    assert "share_links" in tables


def test_password_hash_and_verify():
    from AssetsManager.application.auth_service import AuthService

    hashed = AuthService.hash_password("test123")
    assert AuthService.verify_password("test123", hashed) is True
    assert AuthService.verify_password("wrong", hashed) is False


def test_key_hash_and_verify():
    from AssetsManager.application.auth_service import AuthService

    hashed = AuthService.hash_key("mykey")
    assert AuthService.verify_key("mykey", hashed) is True
    assert AuthService.verify_key("wrong", hashed) is False


def test_generate_and_verify_token(schema_db):
    from AssetsManager.application.auth_service import AuthService

    conn = schema_db
    svc = AuthService(conn, "test-secret")
    password_hash = svc.hash_password("pass")
    token = svc.generate_token(password_hash)
    assert svc.verify_token(token, password_hash) is True


def test_register_and_authenticate_user(schema_db):
    from AssetsManager.application.auth_service import AuthService

    conn = schema_db
    svc = AuthService(conn, "test-secret")
    svc.init_tables()

    user_id, err = svc.register_user("testuser", "Test@1234")
    assert user_id is not None
    assert err == ""

    user, err = svc.authenticate_user("testuser", "Test@1234")
    assert user is not None
    assert user["username"] == "testuser"
    assert err == ""

    user, err = svc.authenticate_user("testuser", "wrong")
    assert user is None
    assert err != ""


def test_user_activate_deactivate(schema_db):
    from AssetsManager.application.auth_service import AuthService

    conn = schema_db
    svc = AuthService(conn, "test-secret")
    svc.init_tables()

    user_id, _ = svc.register_user("testuser", "Test@1234")
    assert user_id is not None
    assert svc.deactivate_user(user_id) is True
    assert svc.activate_user(user_id) is True


def test_invite_code_workflow(schema_db):
    from AssetsManager.application.auth_service import AuthService

    conn = schema_db
    svc = AuthService(conn, "test-secret")
    svc.init_tables()

    code = svc.generate_invite_code("admin")
    assert code != ""

    codes = svc.list_invite_codes()
    assert len(codes) == 1
    assert codes[0]["code"] == code

    assert svc.revoke_invite_code(code) is True
    codes = svc.list_invite_codes()
    assert not codes[0]["is_active"]


def test_invite_code_can_only_register_one_user(schema_db):
    from AssetsManager.application.auth_service import AuthService

    conn = schema_db
    svc = AuthService(conn, "test-secret")
    svc.init_tables()

    code = svc.generate_invite_code("admin")
    first_id, first_err = svc.register_user("first", "Test@1234", invite_code=code)
    second_id, second_err = svc.register_user("second", "Test@1234", invite_code=code)

    assert first_id is not None
    assert first_err == ""
    assert second_id is None
    assert second_err == "Invalid or already used invite code"
    assert svc.authenticate_user("second", "Test@1234")[0] is None

def test_register_requires_invite_when_active_codes_exist(schema_db):
    from AssetsManager.application.auth_service import AuthService

    svc = AuthService(schema_db, "test-secret")
    svc.init_tables()
    assert svc.generate_invite_code("admin")

    user_id, err = svc.register_user("needsinvite", "Test@1234")

    assert user_id is None
    assert err == "Invite code is required"


def test_register_does_not_fail_open_on_closed_connection():
    import sqlite3

    from AssetsManager.application.auth_service import AuthService
    from AssetsManager.repositories.auth_repository import InviteCodeLookupError

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE invite_codes ("
        "code TEXT PRIMARY KEY, created_by TEXT, created_at INTEGER, "
        "is_active INTEGER, used_by TEXT, used_at INTEGER)"
    )
    conn.execute(
        "CREATE TABLE users ("
        "id INTEGER PRIMARY KEY, username TEXT, password TEXT, email TEXT, "
        "role TEXT, is_active INTEGER, created_at INTEGER)"
    )
    conn.close()

    with pytest.raises(InviteCodeLookupError):
        AuthService(conn, "test-secret").register_user("closeddb", "Test@1234")


def test_register_does_not_fail_open_on_invite_schema_error():
    import sqlite3

    from AssetsManager.application.auth_service import AuthService
    from AssetsManager.repositories.auth_repository import InviteCodeLookupError

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE invite_codes (code TEXT PRIMARY KEY)")
    conn.execute(
        "CREATE TABLE users ("
        "id INTEGER PRIMARY KEY, username TEXT, password TEXT, email TEXT, "
        "role TEXT, is_active INTEGER, created_at INTEGER)"
    )

    with pytest.raises(InviteCodeLookupError):
        AuthService(conn, "test-secret").register_user("badschema", "Test@1234")


def test_has_active_users_does_not_fail_open_on_closed_connection():
    import sqlite3

    from AssetsManager.application.auth_service import AuthService

    conn = sqlite3.connect(":memory:")
    svc = AuthService(conn, "test-secret")
    svc.init_tables()
    conn.close()

    with pytest.raises(sqlite3.ProgrammingError):
        svc.has_active_users()


def test_register_does_not_fail_open_on_user_schema_error():
    import sqlite3

    from AssetsManager.application.auth_service import AuthService

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE invite_codes ("
        "code TEXT PRIMARY KEY, created_by TEXT, created_at INTEGER, "
        "is_active INTEGER, used_by TEXT, used_at INTEGER)"
    )
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")

    with pytest.raises(sqlite3.OperationalError):
        AuthService(conn, "test-secret").register_user("badschema", "Test@1234")


def test_verify_user_token_db_failure_returns_none_for_digit_nonce_token(
    schema_db, monkeypatch
):
    """A simple-password token ("ts.nonce.sig") whose nonce is all digits
    shares the three-part shape of a legacy user token.  The DB lookup must
    not propagate (e.g. on schemas without a users table); the token is
    simply treated as not a user token."""
    from AssetsManager.application.auth_service import AuthService

    conn = schema_db
    svc = AuthService(conn, "test-secret")
    token = f"{int(__import__('time').time())}.12345678.deadbeef"

    def boom(_user_id):
        raise Exception("no such table: users")

    monkeypatch.setattr(svc._repo, "get_user_by_id", boom)

    assert svc.verify_user_token(token) is None
