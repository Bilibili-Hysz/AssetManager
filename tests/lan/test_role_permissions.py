from AssetsManager.lan.routes._helpers import (
    ROLE_ADMIN,
    ROLE_GUEST,
    ROLE_USER,
    get_user_permissions,
    require_admin,
    require_role,
)
from AssetsManager.lan.principal import principal_for_request


def _make_request(user_data=None):
    req = {}
    if user_data is not None:
        kind = "guest" if user_data.get("role") == ROLE_GUEST else "user"
        req["principal"] = principal_for_request(kind, user=user_data if kind == "user" else None)
    return req


def test_require_admin_with_admin():
    req = _make_request({"id": 1, "username": "admin", "role": ROLE_ADMIN})
    result = require_admin(req)
    assert result is not None
    assert result.role == ROLE_ADMIN


def test_require_admin_with_user():
    req = _make_request({"id": 2, "username": "alice", "role": ROLE_USER})
    result = require_admin(req)
    assert result is None


def test_require_admin_with_guest():
    req = _make_request({"id": 0, "username": "guest", "role": ROLE_GUEST})
    result = require_admin(req)
    assert result is None


def test_require_admin_no_user():
    req = _make_request()
    result = require_admin(req)
    assert result is None


def test_require_role_with_matching_role():
    req = _make_request({"id": 1, "username": "admin", "role": ROLE_ADMIN})
    result = require_role(req, ROLE_ADMIN, ROLE_USER)
    assert result is not None
    assert result.role == ROLE_ADMIN


def test_require_role_with_non_matching_role():
    req = _make_request({"id": 0, "username": "guest", "role": ROLE_GUEST})
    result = require_role(req, ROLE_ADMIN, ROLE_USER)
    assert result is None


def test_get_user_permissions_admin():
    perms = get_user_permissions({"role": ROLE_ADMIN})
    assert perms["browse"] is True
    assert perms["download"] is True
    assert perms["upload"] is True
    assert perms["manage_links"] is True
    assert perms["manage_users"] is True
    assert perms["settings"] is True


def test_get_user_permissions_user():
    perms = get_user_permissions({"role": ROLE_USER})
    assert perms["browse"] is True
    assert perms["download"] is True
    assert perms["upload"] is False
    assert perms["manage_links"] is False
    assert perms["manage_users"] is False
    assert perms["settings"] is False


def test_get_user_permissions_guest():
    perms = get_user_permissions(None)
    assert perms["browse"] is True
    assert perms["download"] is False
    assert perms["upload"] is False
    assert perms["manage_links"] is False
    assert perms["manage_users"] is False
    assert perms["settings"] is False


def test_get_user_permissions_unknown_role():
    perms = get_user_permissions({"role": "unknown"})
    assert perms["browse"] is True
    assert perms["download"] is False
