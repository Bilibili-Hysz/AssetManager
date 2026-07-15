import logging
from AssetsManager.lan.routes._helpers import sanitize_filename, get_auth_token


def test_sanitize_filename_normal():
    assert sanitize_filename("document.pdf") == "document.pdf"


def test_sanitize_filename_strips_control_chars():
    assert sanitize_filename("file\x00name\x01.txt") == "filename.txt"


def test_sanitize_filename_strips_newlines():
    assert sanitize_filename("file\nname\r.txt") == "filename.txt"


def test_sanitize_filename_strips_path_separators():
    assert sanitize_filename("../../etc/passwd") == "....etcpasswd"
    assert sanitize_filename("path\\to\\file.txt") == "pathtofile.txt"


def test_sanitize_filename_limits_length():
    long_name = "a" * 300
    assert len(sanitize_filename(long_name)) == 200


def test_sanitize_filename_fallback_to_download():
    assert sanitize_filename("") == "download"
    assert sanitize_filename("\x00\x01\x02") == "download"
    assert sanitize_filename("/") == "download"
    assert sanitize_filename("\\") == "download"


# ── get_auth_token deprecation tests ──

class _MockRequest:
    def __init__(self, *, cookies=None, headers=None, query=None):
        self.cookies = cookies or {}
        self.headers = headers or {}
        self.query = query or {}


def test_get_auth_token_uses_cookie(caplog):
    req = _MockRequest(cookies={"lan_token": "ck-tok"})
    with caplog.at_level(logging.WARNING):
        result = get_auth_token(req)
    assert result == "ck-tok"
    assert "DEPRECATED" not in caplog.text


def test_get_auth_token_uses_bearer_header(caplog):
    req = _MockRequest(headers={"Authorization": "Bearer bh-tok"})
    with caplog.at_level(logging.WARNING):
        result = get_auth_token(req)
    assert result == "bh-tok"
    assert "DEPRECATED" not in caplog.text


def test_get_auth_token_prefers_bearer_header_over_stale_cookie(caplog):
    req = _MockRequest(
        cookies={"lan_token": "stale-cookie"},
        headers={"Authorization": "Bearer current-token"},
    )
    with caplog.at_level(logging.WARNING):
        result = get_auth_token(req)
    assert result == "current-token"
    assert "DEPRECATED" not in caplog.text


def test_get_auth_token_deprecates_query_token(caplog):
    req = _MockRequest(query={"token": "qt-tok"})
    with caplog.at_level(logging.WARNING):
        result = get_auth_token(req)
    assert result == "qt-tok"
    assert "DEPRECATED" in caplog.text
    assert "?token=" in caplog.text


def test_get_auth_token_deprecates_query_key(caplog):
    req = _MockRequest(query={"key": "qk-tok"})
    with caplog.at_level(logging.WARNING):
        result = get_auth_token(req)
    assert result == "qk-tok"
    assert "DEPRECATED" in caplog.text
    assert "?key=" in caplog.text


def test_get_auth_token_prefers_cookie_over_query(caplog):
    req = _MockRequest(cookies={"lan_token": "ck-tok"}, query={"token": "qt-tok"})
    with caplog.at_level(logging.WARNING):
        result = get_auth_token(req)
    assert result == "ck-tok"
    assert "DEPRECATED" not in caplog.text


def test_get_auth_token_prefers_bearer_over_query(caplog):
    req = _MockRequest(headers={"Authorization": "Bearer bh-tok"}, query={"token": "qt-tok"})
    with caplog.at_level(logging.WARNING):
        result = get_auth_token(req)
    assert result == "bh-tok"
    assert "DEPRECATED" not in caplog.text
