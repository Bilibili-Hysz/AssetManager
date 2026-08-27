"""Tests for core/format_utils.py."""
from AssetsManager.core.format_utils import CATEGORY_MAP, format_size


class TestFormatSize:

    def test_bytes(self):
        assert format_size(0) == "0.0 B"
        assert format_size(500) == "500.0 B"

    def test_kilobytes(self):
        assert format_size(1024) == "1.0 KB"
        assert format_size(1536) == "1.5 KB"

    def test_megabytes(self):
        assert format_size(1048576) == "1.0 MB"

    def test_gigabytes(self):
        assert format_size(1073741824) == "1.0 GB"

    def test_terabytes(self):
        assert format_size(1099511627776) == "1.0 TB"


class TestCategoryMap:

    def test_image_extensions(self):
        assert CATEGORY_MAP[".png"] == "images"
        assert CATEGORY_MAP[".jpg"] == "images"
        assert CATEGORY_MAP[".svg"] == "images"

    def test_3d_extensions(self):
        assert CATEGORY_MAP[".blend"] == "3d"
        assert CATEGORY_MAP[".fbx"] == "3d"
        assert CATEGORY_MAP[".obj"] == "3d"

    def test_video_extensions(self):
        assert CATEGORY_MAP[".mp4"] == "videos"
        assert CATEGORY_MAP[".mov"] == "videos"

    def test_document_extensions(self):
        assert CATEGORY_MAP[".txt"] == "documents"
        assert CATEGORY_MAP[".pdf"] == "documents"
        assert CATEGORY_MAP[".json"] == "documents"

    def test_archive_extensions(self):
        assert CATEGORY_MAP[".zip"] == "archives"
        assert CATEGORY_MAP[".rar"] == "archives"
        assert CATEGORY_MAP[".bz2"] == "archives"

    def test_live_mapping_uses_snapshot_for_complete_dict_api(self):
        from AssetsManager.core.format_utils import LiveCategoryMap

        mapping = LiveCategoryMap({"a": "first", "b": "second"})
        assert repr(mapping) == "{'a': 'first', 'b': 'second'}"
        assert mapping == {"a": "first", "b": "second"}
        assert mapping != {"a": "other"}
        assert not (mapping != {"a": "first", "b": "second"})
        assert mapping | {"c": "third"} == {"a": "first", "b": "second", "c": "third"}
        assert {"zero": "zeroth"} | mapping == {
            "zero": "zeroth", "a": "first", "b": "second",
        }
        mapping |= {"c": "third"}
        assert mapping.snapshot() == {"a": "first", "b": "second", "c": "third"}
        assert mapping.popitem() == ("c", "third")
        assert mapping.snapshot() == {"a": "first", "b": "second"}
        assert LiveCategoryMap.fromkeys(("x", "y"), "value") == {
            "x": "value", "y": "value",
        }
        assert type(LiveCategoryMap.fromkeys(("x",))) is dict

    def test_unknown_extension(self):
        assert CATEGORY_MAP.get(".xyz") is None
