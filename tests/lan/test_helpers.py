from AssetsManager.lan.routes._helpers import sanitize_filename


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
