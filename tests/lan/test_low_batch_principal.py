from AssetsManager.lan.principal import principal_for_request


def test_viewer_role_no_download():
    principal = principal_for_request(
        "user", user={"id": 1, "username": "v", "role": "viewer"})
    assert principal.authenticated is True
    assert principal.role == "user"
    assert principal.capabilities.download is False
    assert principal.capabilities.browse is True
    assert principal.capabilities.preview is True
    assert principal.capabilities.realtime is True


def test_explicit_user_role_keeps_download():
    principal = principal_for_request(
        "user", user={"id": 2, "username": "u", "role": "user"})
    assert principal.authenticated is True
    assert principal.role == "user"
    assert principal.capabilities.download is True


def test_admin_unchanged():
    principal = principal_for_request(
        "user", user={"id": 3, "username": "a", "role": "admin"})
    assert principal.authenticated is True
    assert principal.role == "admin"
    assert principal.capabilities.download is True


def test_unknown_role_matches_viewer():
    principal = principal_for_request(
        "user", user={"id": 4, "username": "x", "role": "unknown"})
    assert principal.authenticated is True
    assert principal.role == "user"
    assert principal.capabilities.download is False
    assert principal.capabilities.browse is True
    assert principal.capabilities.preview is True
    assert principal.capabilities.realtime is True


def test_malformed_user_record_falls_back_to_safe_defaults():
    user = {"id": None, "username": None, "role": None,
            "is_active": None, "created_at": None}
    principal = principal_for_request("user", user=user)
    assert principal.authenticated is True
    assert principal.user_profile is not None
    assert principal.user_profile["id"] == 0
    assert principal.user_profile["created_at"] == 0


def test_missing_fields_no_exception():
    principal = principal_for_request("user", user={"username": "x"})
    assert principal.authenticated is True
    assert principal.user_profile is not None


def test_guest_branch_unaffected():
    principal = principal_for_request("guest")
    assert principal.authenticated is False
    assert principal.capabilities.download is False
