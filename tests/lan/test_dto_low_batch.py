"""Low-severity regression tests for LAN response DTO hardening.

Covers:
- D3: TreeItemResponse recursion depth cap + non-list ``children`` degradation.
- D4: unknown/"file" tree ``type`` is rejected; missing defaults to "dir".
- D5: StatsResponse tolerates explicit ``None`` transfer fields.
- D6: timestamp timezone contract is documentation-only -- the module
  docstring and class docstrings state "Unix epoch seconds, UTC"; there is
  no behavior to test.
"""
import pytest

from AssetsManager.lan.dto import StatsResponse, TreeItemResponse


def _deep_record(depth: int) -> dict:
    node: dict = {"name": "n", "path": "/n", "type": "dir", "is_leaf": False,
                  "children": []}
    for _ in range(depth):
        node = {"name": "n", "path": "/n", "type": "dir", "is_leaf": False,
                "children": [node]}
    return node


def _walk_depth(dumped: dict) -> int:
    levels = 0
    node = dumped
    while node["children"]:
        node = node["children"][0]
        levels += 1
    return levels


# --- D3: recursion depth cap and children degradation ----------------------


def test_tree_to_dict_truncates_deeply_nested_children():
    item = TreeItemResponse.from_record(_deep_record(100))
    dumped = item.to_dict()  # must not raise RecursionError
    assert _walk_depth(dumped) <= 32
    node = dumped
    for _ in range(32):
        node = node["children"][0]
    assert node["children"] == []


def test_tree_from_record_does_not_recurse_forever_on_deep_input():
    item = TreeItemResponse.from_record(_deep_record(200))
    assert item.children  # parse completed, subtree truncated


def test_tree_from_record_degrades_string_children():
    item = TreeItemResponse.from_record({
        "name": "a", "path": "/a", "type": "dir", "is_leaf": False,
        "children": "not-a-list",
    })
    assert item.children == ()
    assert item.to_dict()["children"] == []


def test_tree_from_record_degrades_non_iterable_children():
    item = TreeItemResponse.from_record({
        "name": "a", "path": "/a", "type": "dir", "is_leaf": False,
        "children": 42,
    })
    assert item.children == ()


def test_tree_to_dict_degrades_non_list_children_on_direct_construction():
    item = TreeItemResponse("a", "/a", "dir", False, "not-a-list")
    assert item.to_dict()["children"] == []


def test_tree_to_dict_truncates_deep_direct_construction():
    node = TreeItemResponse("n", "/n", "dir", False, ())
    for _ in range(100):
        node = TreeItemResponse("n", "/n", "dir", False, (node,))
    dumped = node.to_dict()  # must not raise RecursionError
    assert _walk_depth(dumped) <= 32


def test_tree_to_dict_shallow_structure_unchanged():
    item = TreeItemResponse.from_record({
        "name": "a", "path": "/a", "type": "dir", "is_leaf": True, "children": [],
    })
    assert item.to_dict() == {
        "name": "a", "path": "/a", "type": "dir", "is_leaf": True, "children": [],
    }


# --- D4: unknown tree type is rejected (public contract) ---------------------


def test_tree_unknown_type_is_rejected():
    with pytest.raises(ValueError, match="tree type"):
        TreeItemResponse.from_record({
            "name": "a", "path": "/a", "type": "weird", "is_leaf": True,
        })


def test_tree_non_string_type_is_rejected():
    with pytest.raises(ValueError, match="tree type"):
        TreeItemResponse.from_record({
            "name": "a", "path": "/a", "type": 123, "is_leaf": True,
        })


def test_tree_missing_type_defaults_to_dir():
    item = TreeItemResponse.from_record({"name": "a", "path": "/a", "is_leaf": True})
    assert item.type == "dir"


def test_tree_explicit_file_type_is_rejected():
    with pytest.raises(ValueError, match="tree type"):
        TreeItemResponse.from_record({
            "name": "a", "path": "/a", "type": "file", "is_leaf": True,
        })


# --- D5: StatsResponse tolerates explicit None fields ----------------------


def test_stats_from_record_accepts_none_bytes_transferred():
    stats = StatsResponse.from_record({
        "connections": 1,
        "requests": 2,
        "bytes_transferred": None,
        "bytes_transferred_fmt": None,
        "uptime": 3.5,
    })
    assert stats.bytes_transferred is None
    assert stats.bytes_transferred_fmt is None
    assert stats.to_dict()["bytes_transferred"] is None


def test_stats_from_record_with_missing_transfer_fields():
    stats = StatsResponse.from_record({"connections": 0, "requests": 0, "uptime": 0})
    assert stats.bytes_transferred is None
    assert stats.bytes_transferred_fmt is None


def test_stats_from_record_with_value_keeps_fmt():
    stats = StatsResponse.from_record({
        "connections": 1,
        "requests": 2,
        "bytes_transferred": 2048,
        "bytes_transferred_fmt": "2.0 KB",
        "uptime": 1,
    })
    assert stats.bytes_transferred == 2048
    assert stats.bytes_transferred_fmt == "2.0 KB"
