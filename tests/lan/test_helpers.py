import logging
import builtins
import os
from pathlib import Path
from types import SimpleNamespace

from AssetsManager.lan.routes._helpers import find_first_image, sanitize_filename, get_auth_token


class _OSWithScandir:
    """Proxy the real ``os`` module with only ``scandir`` overridden.

    Patching ``AssetsManager.lan.routes._helpers.os.scandir`` would mutate
    the global ``os`` module (``_helpers.os`` *is* ``os``) and leak into
    stdlib teardown paths such as ``shutil.rmtree``'s directory walk.
    """

    def __init__(self, scandir):
        self._scandir = scandir

    def __getattr__(self, name):
        return getattr(os, name)

    def scandir(self, path):
        return self._scandir(path)


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


def test_find_first_image_does_not_sort_all_candidates(tmp_path: Path, monkeypatch):
    expected = tmp_path / "Apple.PNG"
    expected.write_bytes(b"a")
    (tmp_path / "zebra.jpg").write_bytes(b"z")
    (tmp_path / "middle.webp").write_bytes(b"m")

    def fail_sorted(*_args, **_kwargs):
        raise AssertionError("find_first_image must not sort candidates")

    monkeypatch.setattr(builtins, "sorted", fail_sorted)

    assert find_first_image(tmp_path) == str(expected)


def test_find_first_image_uses_case_insensitive_filename_order(tmp_path: Path):
    (tmp_path / "zebra.jpg").write_bytes(b"z")
    expected = tmp_path / "Apple.PNG"
    expected.write_bytes(b"a")
    (tmp_path / "middle.webp").write_bytes(b"m")
    (tmp_path / "not-an-image.txt").write_text("ignore")

    assert find_first_image(tmp_path) == str(expected)


def test_find_first_image_ignores_nested_images_and_returns_none_without_direct_images(tmp_path: Path):
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "inside.jpg").write_bytes(b"image")

    assert find_first_image(tmp_path) is None


def test_find_first_image_preserves_first_scanned_entry_when_names_normalize_equally(monkeypatch, tmp_path: Path):
    first = SimpleNamespace(name="Alpha.jpg", path=str(tmp_path / "Alpha.jpg"), is_file=lambda: True)
    second = SimpleNamespace(name="alpha.JPG", path=str(tmp_path / "alpha.JPG"), is_file=lambda: True)
    monkeypatch.setattr(
        "AssetsManager.lan.routes._helpers.os", _OSWithScandir(lambda _path: [first, second])
    )

    assert find_first_image(tmp_path) == first.path


def test_find_first_image_returns_none_when_scandir_raises_os_error(monkeypatch, tmp_path: Path):
    def raise_os_error(_path):
        raise OSError("unavailable")

    monkeypatch.setattr("AssetsManager.lan.routes._helpers.os", _OSWithScandir(raise_os_error))

    assert find_first_image(tmp_path) is None


# ── get_auth_token auth tests ──

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


def test_get_auth_token_rejects_query_token(caplog):
    req = _MockRequest(query={"token": "qt-tok"})
    with caplog.at_level(logging.WARNING):
        result = get_auth_token(req)
    assert result == ""
    assert "DEPRECATED" not in caplog.text


def test_get_auth_token_rejects_query_key(caplog):
    req = _MockRequest(query={"key": "qk-tok"})
    with caplog.at_level(logging.WARNING):
        result = get_auth_token(req)
    assert result == ""
    assert "DEPRECATED" not in caplog.text


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
