"""Tests for AuthService."""


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
    assert "share_links" not in tables


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
