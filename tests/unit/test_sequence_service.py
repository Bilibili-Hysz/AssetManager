"""Unit tests for the frame-sequence recognition service (media stack N-C)."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from AssetsManager.application import sequence_service
from AssetsManager.application.sequence_service import (
    MIN_SEQUENCE_FRAMES,
    find_neighbors,
    group_sequences,
)


@pytest.fixture(autouse=True)
def _fresh_cache():
    sequence_service.clear_sequence_cache()
    yield
    sequence_service.clear_sequence_cache()


# ── group_sequences: grouping boundaries ─────────────────────────


def test_minimum_three_frames_qualifies_as_sequence():
    two = group_sequences(["render.001.png", "render.002.png"])
    assert two == []  # 1-2 frames are never a sequence
    three = group_sequences(["render.001.png", "render.002.png", "render.003.png"])
    assert len(three) == 1
    group = three[0]
    assert group.prefix == "render."
    assert group.ext == ".png"
    assert group.frames == ("render.001.png", "render.002.png", "render.003.png")
    assert group.start == 1 and group.end == 3 and group.count == 3


def test_files_without_numbers_never_group():
    assert group_sequences(["readme.png", "a.png", "b.png", "c.png"]) == []


def test_digit_boundary_keeps_shot1_and_shot11_apart():
    names = [
        "shot1_001.png", "shot1_002.png", "shot1_003.png",
        "shot11_001.png", "shot11_002.png",
    ]
    groups = group_sequences(names)
    assert [g.prefix for g in groups] == ["shot1_"]
    assert groups[0].count == 3
    # The bare form "shot100.png" splits the number at the digit boundary:
    # "shot1"+"00" must never happen.
    bare = group_sequences(["shot100.png", "shot101.png", "shot102.png"])
    assert bare[0].prefix == "shot" and bare[0].start == 100


def test_mixed_extensions_split_and_same_number_conflicts_split_by_ext():
    names = [
        "img001.jpg", "img002.jpg", "img003.jpg",
        "img001.png", "img002.png",
        "case001.PNG", "case002.PNG", "case003.png",
    ]
    groups = group_sequences(names)
    by_ext = {(g.prefix, g.ext): g for g in groups}
    # jpg has 3 frames; png only 2 -> not a sequence.
    assert set(by_ext) == {("img", ".jpg"), ("case", ".png")}
    assert by_ext[("img", ".jpg")].count == 3
    # ".PNG" and ".png" are the same extension for grouping purposes.
    assert by_ext[("case", ".png")].count == 3


def test_leading_zero_padding_is_ignored_for_frame_numbers():
    names = ["a006.png", "a6.png", "a7.png", "a08.png", "a9.png"]
    groups = group_sequences(names)
    assert len(groups) == 1
    group = groups[0]
    # 6 appears twice ("a006.png"/"a6.png"): one frame, padded spelling wins.
    assert group.frames == ("a006.png", "a7.png", "a08.png", "a9.png")
    assert group.start == 6 and group.end == 9 and group.count == 4


def test_out_of_order_input_still_yields_ascending_frames():
    groups = group_sequences(["f003.png", "f001.png", "f010.png", "f002.png"])
    assert len(groups) == 1
    assert groups[0].frames == ("f001.png", "f002.png", "f003.png", "f010.png")
    assert (groups[0].start, groups[0].end) == (1, 10)


def test_number_must_sit_between_prefix_and_extension():
    # Digits not adjacent to the extension ("abc123def.png") carry no frame
    # number; extension-less names never group either.
    assert group_sequences(["abc123def.png", "abc124def.png", "abc125def.png"]) == []
    assert group_sequences(["img001", "img002", "img003"]) == []


def test_frame_number_gaps_are_tolerated():
    groups = group_sequences(["g001.png", "g002.png", "g007.png"])
    assert len(groups) == 1
    assert groups[0].frames == ("g001.png", "g002.png", "g007.png")


def test_grouping_is_deterministic_across_runs():
    names = ["b001.png", "b002.png", "b003.png", "a001.png", "a002.png", "a003.png"]
    first = [g.prefix for g in group_sequences(names)]
    assert first == sorted(first) == ["a", "b"]
    assert [g.prefix for g in group_sequences(list(reversed(names)))] == first


# ── find_neighbors: directory detection + cache ──────────────────


def _write_frames(directory: Path, names: list[str]) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in names:
        path = directory / name
        path.write_bytes(b"frame")
        paths.append(path)
    return paths


def test_find_neighbors_returns_adjacent_frames_and_bounds(tmp_path):
    frames = _write_frames(tmp_path, [f"seq.{i:04d}.png" for i in range(1, 6)])
    mid = find_neighbors(tmp_path, "seq.0003.png")
    assert mid is not None
    assert (mid.index, mid.count) == (2, 5)
    assert mid.prev_path == str(frames[1])
    assert mid.next_path == str(frames[3])
    assert mid.fps is None
    assert mid.frames == tuple(str(p) for p in frames)

    first = find_neighbors(tmp_path, "seq.0001.png")
    assert first is not None and first.prev_path is None
    assert first.next_path == str(frames[1])
    last = find_neighbors(tmp_path, "seq.0005.png")
    assert last is not None and last.next_path is None
    assert last.prev_path == str(frames[3])


def test_find_neighbors_none_for_non_member_and_missing_directory(tmp_path):
    _write_frames(tmp_path, ["seq.0001.png", "seq.0002.png", "seq.0003.png"])
    (tmp_path / "solo.png").write_bytes(b"x")
    # Standalone file: fewer than MIN_SEQUENCE_FRAMES siblings share its shape.
    assert find_neighbors(tmp_path, "solo.png") is None
    # Wrong name / missing directory.
    assert find_neighbors(tmp_path, "seq.9999.png") is None
    assert find_neighbors(tmp_path / "nope", "seq.0001.png") is None


def test_directory_scan_cache_avoids_rescans_until_mtime_changes(tmp_path, monkeypatch):
    _write_frames(tmp_path, ["seq.0001.png", "seq.0002.png", "seq.0003.png"])
    calls = []
    real_listdir = os.listdir

    def counting_listdir(path):
        calls.append(path)
        return real_listdir(path)

    monkeypatch.setattr(sequence_service.os, "listdir", counting_listdir)
    assert find_neighbors(tmp_path, "seq.0001.png") is not None
    assert len(calls) == 1
    # Same directory mtime: served from the LRU, no rescan.
    assert find_neighbors(tmp_path, "seq.0003.png") is not None
    assert len(calls) == 1
    # Directory content changes -> mtime moves -> one rescan picks up frame 4.
    _write_frames(tmp_path, ["seq.0004.png"])
    future = time.time() + 10
    os.utime(tmp_path, (future, future))
    neighbors = find_neighbors(tmp_path, "seq.0004.png")
    assert len(calls) == 2
    assert neighbors is not None
    assert neighbors.count == 4 and neighbors.index == 3
    assert neighbors.prev_path == str(tmp_path / "seq.0003.png")
    assert neighbors.next_path is None


def test_scan_cache_is_bounded(tmp_path):
    for i in range(sequence_service._SCAN_CACHE_MAX + 2):
        directory = tmp_path / f"dir{i}"
        _write_frames(directory, ["seq.001.png", "seq.002.png", "seq.003.png"])
        assert find_neighbors(directory, "seq.001.png") is not None
    assert len(sequence_service._SCAN_CACHE) <= sequence_service._SCAN_CACHE_MAX


def test_find_neighbors_accepts_path_and_string_inputs(tmp_path):
    _write_frames(tmp_path, ["seq.0001.png", "seq.0002.png", "seq.0003.png"])
    by_str = find_neighbors(str(tmp_path), "seq.0002.png")
    by_path = find_neighbors(Path(tmp_path), "seq.0002.png")
    assert by_str == by_path


# ── performance ──────────────────────────────────────────────────


def test_thousand_frame_grouping_is_fast():
    names = [f"render.{i:04d}.png" for i in range(1000)]
    start = time.perf_counter()
    groups = group_sequences(names)
    elapsed = time.perf_counter() - start
    assert len(groups) == 1 and groups[0].count == 1000
    # Relaxed CI-friendly bound for what is an O(n) regex pass.
    assert elapsed < 0.5, f"grouping 1000 frames took {elapsed:.3f}s"


def test_min_sequence_frames_matches_architecture_contract():
    assert MIN_SEQUENCE_FRAMES == 3
