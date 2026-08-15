"""Unit tests for DirectoryScanner (low-severity fixes S2-S8)."""
import os
import time

from AssetsManager.lan.scanner import DirectoryScanner


def _make_tree(root, files_per_dir=60, depth=2):
    """Create a small tree of files; returns expected (non-hidden) count."""
    count = 0
    current = [root]
    for level in range(depth):
        nxt = []
        for d in current:
            for i in range(3):
                sub = os.path.join(d, f"dir-{level}-{i}")
                os.makedirs(sub, exist_ok=True)
                nxt.append(sub)
                for j in range(files_per_dir):
                    with open(os.path.join(sub, f"f{j}.txt"), "w", encoding="utf-8") as f:
                        f.write("x")
                    count += 1
        current = nxt
    # hidden entries must be skipped by the scanner
    os.makedirs(os.path.join(root, ".hidden"), exist_ok=True)
    with open(os.path.join(root, ".hidden", "skip.txt"), "w", encoding="utf-8") as f:
        f.write("x")
    return count


def _wait_scan_finished(scanner, timeout=5):
    deadline = time.monotonic() + timeout
    while scanner.is_scanning() and time.monotonic() < deadline:
        time.sleep(0.05)


def test_scanner_cancel_does_not_publish_partial_index(tmp_path):
    """S2: after stop(), a cancelled scan must not replace the index.

    The index starts empty, so a cancelled scan must leave file_count() at 0
    rather than publishing a partial result set.
    """
    root = tmp_path / "lib"
    root.mkdir()
    _make_tree(root, files_per_dir=60, depth=2)  # ~720 files to keep the walk busy

    scanner = DirectoryScanner(str(root), None)
    scanner.start_background_scan()
    # Cancel immediately — the walk may be mid-flight or not started yet.
    scanner.stop()
    _wait_scan_finished(scanner)
    assert scanner.is_scanning() is False
    # The partial scan must never have been published.
    assert scanner.file_count() == 0
    assert scanner.search("") == []


def test_scanner_is_scanning_false_after_completion(tmp_path):
    """S3: is_scanning() is False once a normal scan finishes."""
    root = tmp_path / "lib"
    root.mkdir()
    _make_tree(root)

    scanner = DirectoryScanner(str(root), None)
    assert scanner.is_scanning() is False
    scanner.start_background_scan()
    _wait_scan_finished(scanner)
    assert scanner.is_scanning() is False


def test_scanner_search_none_and_string_queries(tmp_path):
    """S6: search(None) returns [] fail-safe; string queries filter normally."""
    root = tmp_path / "lib"
    root.mkdir()
    expected = _make_tree(root)
    scanner = DirectoryScanner(str(root), None)
    scanner.start_background_scan()
    _wait_scan_finished(scanner)

    assert scanner.search(None) == []
    assert scanner.search(123) == []
    # Every indexed file matches the empty query (explicit limit bypasses
    # the default 200 cap).
    assert len(scanner.search("", limit=expected)) == expected
    # Substring filter works.
    res = scanner.search("f0.txt")
    assert res
    assert all("f0.txt" in f["name"] for f in res)


def test_scanner_search_returns_new_list_not_internal_index(tmp_path):
    """S4: search() must return a fresh list, never the internal _index."""
    root = tmp_path / "lib"
    root.mkdir()
    _make_tree(root)
    scanner = DirectoryScanner(str(root), None)
    scanner.start_background_scan()
    _wait_scan_finished(scanner)

    res = scanner.search("")
    with scanner._lock:
        internal = scanner._index
    assert res is not internal
    # Mutating the returned list must not corrupt the internal index.
    res.clear()
    assert scanner.file_count() == len(internal) > 0
    assert scanner.search("f1.txt") != []


def test_scanner_invalidate_drops_index(tmp_path):
    """S5: invalidate() clears the index so stale results are not served."""
    root = tmp_path / "lib"
    root.mkdir()
    expected = _make_tree(root)
    scanner = DirectoryScanner(str(root), None)
    scanner.start_background_scan()
    _wait_scan_finished(scanner)
    assert scanner.file_count() == expected

    scanner.invalidate()
    assert scanner.file_count() == 0
    assert scanner.search("") == []
    # Re-scanning repopulates the index.
    scanner.start_background_scan()
    _wait_scan_finished(scanner)
    assert scanner.file_count() == expected


def test_scanner_completes_and_indexes_correct_count(tmp_path):
    """S6: a full scan indexes exactly the non-hidden files."""
    root = tmp_path / "lib"
    root.mkdir()
    expected = _make_tree(root)

    scanner = DirectoryScanner(str(root), None)
    scanner.start_background_scan()
    _wait_scan_finished(scanner)
    assert scanner.is_scanning() is False
    assert scanner.file_count() == expected


def test_superseded_scan_generation_does_not_publish_or_clear_flag(tmp_path):
    """A stale worker finishing after a newer scan started must neither
    publish its partial index nor clear the new scan's _scanning flag
    (M-L1: stop() only joins for 2s, so superseded workers stay alive)."""
    root = tmp_path / "lib"
    root.mkdir()
    (root / "a.txt").write_text("a")
    (root / "b.txt").write_text("b")

    scanner = DirectoryScanner(str(root), None)
    scanner._scanning = True  # a newer scan is in progress
    scanner._generation = 2
    scanner._scan_all(1)  # the superseded worker finishes

    assert scanner._index == []  # partial index not published
    assert scanner._scanning is True  # newer scan's flag untouched
    assert scanner.is_scanning() is True

    # The current generation still publishes and clears normally.
    scanner._stop_event.clear()
    scanner._scan_all(2)
    assert scanner.file_count() == 2
    assert scanner._scanning is False
