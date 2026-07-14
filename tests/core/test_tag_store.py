"""Tests for TagStore."""
import os
from AssetsManager.core.tag_store import TagStore


def _clean(s: TagStore, *paths):
    for p in paths:
        s.remove_file(p)


def test_add_get_tags():
    s = TagStore("/test/library")
    _clean(s, "/test/library/file1.png")
    s.add_tag("/test/library/file1.png", "hero")
    s.add_tag("/test/library/file1.png", "villain")
    tags = s.get_tags("/test/library/file1.png")
    assert "hero" in tags
    assert "villain" in tags
    _clean(s, "/test/library/file1.png")


def test_get_tags_for_files():
    s = TagStore("/test/library")
    a = os.path.abspath("/test/library/batch_a.png")
    b = os.path.abspath("/test/library/batch_b.png")
    _clean(s, a, b)
    s.add_tag(a, "hero")
    s.add_tag(b, "villain")

    tags = s.get_tags_for_files([a, b])

    assert tags[a] == ["hero"]
    assert tags[b] == ["villain"]
    _clean(s, a, b)


def test_remove_tag():
    s = TagStore("/test/library")
    _clean(s, "/test/library/file1.png")
    s.add_tag("/test/library/file1.png", "temp")
    s.remove_tag("/test/library/file1.png", "temp")
    assert "temp" not in s.get_tags("/test/library/file1.png")
    _clean(s, "/test/library/file1.png")


def test_get_files_by_tag():
    s = TagStore("/test/library")
    a = os.path.abspath("/test/library/a.png")
    b = os.path.abspath("/test/library/b.png")
    c = os.path.abspath("/test/library/c.png")
    _clean(s, a, b, c)
    s.add_tag(a, "shared")
    s.add_tag(b, "shared")
    s.add_tag(c, "other")
    shared = s.get_files_by_tag("shared")
    assert a in shared
    assert b in shared
    assert c not in shared
    _clean(s, a, b, c)


def test_get_all_tags():
    s = TagStore("/test/library")
    _clean(s, "/test/library/a.png", "/test/library/b.png")
    s.add_tag("/test/library/a.png", "Zebra")
    s.add_tag("/test/library/b.png", "alpha")
    tags = [t.lower() for t in s.get_all_tags()]
    assert "alpha" in tags
    assert "zebra" in tags
    _clean(s, "/test/library/a.png", "/test/library/b.png")


def test_normalize():
    s = TagStore("/test/library")
    _clean(s, "/test/library/f.png")
    s.add_tag("/test/library/f.png", "  Dupe  ")
    s.add_tag("/test/library/f.png", "DUPE")
    assert len(s.get_tags("/test/library/f.png")) == 1
    _clean(s, "/test/library/f.png")


def test_remove_file():
    s = TagStore("/test/library")
    _clean(s, "/test/library/g.png")
    s.add_tag("/test/library/g.png", "label")
    s.remove_file("/test/library/g.png")
    assert "/test/library/g.png" not in s.get_all_tagged_files()
    _clean(s, "/test/library/g.png")
