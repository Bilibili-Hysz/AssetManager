"""Frame-sequence recognition (media stack N-C).

Groups same-directory filenames into frame sequences ("render.0001.png" …
"render.0120.png") and resolves the previous/next frame around a given file
so the desktop viewer and the LAN API can step through a sequence without
any import-time detection or database dependency (the v37 ``asset_sequences``
tables stay reserved for the later import-time scan).

Grouping rule (pure function): filenames sharing the same *prefix* (everything
before the final digit run), the same *extension* (compared case-insensitively),
and at least :data:`MIN_SEQUENCE_FRAMES` distinct frame numbers form one
sequence. The frame number is the complete digit run immediately before the
extension, so the prefix boundary always falls on a digit boundary:
``shot1_001`` (prefix ``shot1_``) never groups with ``shot11_001`` (prefix
``shot11_``), and the ``100`` in ``shot100.png`` is one unbroken number.
Leading zeros are ignored when comparing frame numbers (``006`` == ``6``);
when two spellings of the same number exist the more heavily padded one wins.
Frame-number gaps are tolerated — render outputs routinely drop frames, and
neighbor navigation simply skips to the next existing frame.

``find_neighbors`` lists the target directory on demand (cheap) and keeps a
small LRU keyed by directory whose entries are invalidated by the directory
mtime, so paging through a folder or playing a sequence never rescans.
"""
from __future__ import annotations

import os
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, replace
from pathlib import Path

__all__ = [
    "MIN_SEQUENCE_FRAMES",
    "SequenceGroup",
    "SequenceNeighbors",
    "clear_sequence_cache",
    "find_neighbors",
    "group_sequences",
]

# A prefix needs at least this many distinct frame numbers to count as a
# sequence (matches the architecture contract: 1-2 frames are not one).
MIN_SEQUENCE_FRAMES = 3

# Filename shape: <prefix><digits><ext> where the digit run is complete (the
# lazy prefix forces the match at the LAST full digit run before the extension)
# and the extension is a single dot-suffix. Names without both a digit run and
# an extension are never sequence members.
_FRAME_RE = re.compile(r"^(?P<prefix>.*?)(?P<num>\d+)(?P<ext>\.[^.]+)$")


@dataclass(frozen=True)
class SequenceGroup:
    """One detected frame sequence inside a single directory.

    ``frames`` holds the member filenames sorted by frame number ascending
    (one representative per distinct frame number); ``dir`` is empty for the
    pure :func:`group_sequences` input and filled in by directory scans.
    """

    prefix: str
    dir: str
    ext: str
    frames: tuple[str, ...]
    start: int
    end: int

    @property
    def count(self) -> int:
        return len(self.frames)


@dataclass(frozen=True)
class SequenceNeighbors:
    """Sequence position of one file, as returned by :func:`find_neighbors`.

    ``prev_path``/``next_path`` are ``None`` at the sequence boundaries;
    ``fps`` stays ``None`` because the service never guesses a frame rate.
    ``frames`` (full paths, ascending) is carried alongside the minimal
    prev/next payload so the viewer's playback can loop at the ends without
    a second scan.
    """

    prev_path: str | None
    next_path: str | None
    index: int
    count: int
    fps: int | None = None
    frames: tuple[str, ...] = ()


def _beats(candidate: tuple[str, str], incumbent: tuple[str, str]) -> bool:
    """True when *candidate* ``(name, digits)`` represents its frame number better.

    Prefer the more heavily zero-padded spelling (the canonical render-output
    form); break exact ties lexicographically so the choice is deterministic.
    """
    if len(candidate[1]) != len(incumbent[1]):
        return len(candidate[1]) > len(incumbent[1])
    return candidate[0] < incumbent[0]


def group_sequences(filenames: list[str]) -> list[SequenceGroup]:
    """Group same-directory *filenames* into qualifying sequence groups.

    Pure function: no I/O, deterministic order (groups sorted by
    ``(prefix, ext)``), only groups with at least
    :data:`MIN_SEQUENCE_FRAMES` distinct frame numbers are returned.
    """
    candidates: dict[tuple[str, str], dict[int, tuple[str, str]]] = {}
    for raw in filenames:
        name = os.path.basename(str(raw))
        match = _FRAME_RE.match(name)
        if match is None:
            continue
        prefix = match.group("prefix")
        # Extension grouping is case-insensitive so ".PNG" and ".png" renders
        # merge, but the reported ext keeps the canonical lowercase form.
        ext = match.group("ext").lower()
        digits = match.group("num")
        number = int(digits)
        bucket = candidates.setdefault((prefix, ext), {})
        existing = bucket.get(number)
        if existing is None or _beats((name, digits), existing):
            bucket[number] = (name, digits)

    groups: list[SequenceGroup] = []
    for (prefix, ext), bucket in sorted(candidates.items()):
        if len(bucket) < MIN_SEQUENCE_FRAMES:
            continue
        numbers = sorted(bucket)
        frames = tuple(bucket[number][0] for number in numbers)
        groups.append(SequenceGroup(
            prefix=prefix, dir="", ext=ext, frames=frames,
            start=numbers[0], end=numbers[-1],
        ))
    return groups


@dataclass(frozen=True)
class _DirScan:
    """Cached grouping of one directory snapshot."""

    mtime: float
    groups: tuple[SequenceGroup, ...]
    index: dict[str, tuple[int, int]]  # filename -> (group, frame) position


_SCAN_CACHE_MAX = 8
_SCAN_CACHE: "OrderedDict[str, _DirScan]" = OrderedDict()
_CACHE_LOCK = threading.Lock()


def _scan_directory(directory: Path) -> _DirScan | None:
    """List *directory* once and index every detected sequence member."""
    try:
        names = sorted(os.listdir(directory))
        mtime = os.path.getmtime(directory)
    except OSError:
        return None
    groups = tuple(
        replace(group, dir=str(directory)) for group in group_sequences(names)
    )
    index: dict[str, tuple[int, int]] = {}
    for group_pos, group in enumerate(groups):
        for frame_pos, name in enumerate(group.frames):
            index[name] = (group_pos, frame_pos)
    return _DirScan(mtime=mtime, groups=groups, index=index)


def _cached_scan(directory: Path) -> _DirScan | None:
    """Return the directory scan, re-listing only when the mtime moved on.

    A failed scan (missing/unreadable directory) is never cached so a
    transiently locked directory is retried on the next open.
    """
    key = str(directory)
    with _CACHE_LOCK:
        entry = _SCAN_CACHE.get(key)
    if entry is not None:
        try:
            if os.path.getmtime(directory) == entry.mtime:
                with _CACHE_LOCK:
                    _SCAN_CACHE.move_to_end(key)
                    return entry
        except OSError:
            pass
    scan = _scan_directory(directory)
    if scan is not None:
        with _CACHE_LOCK:
            _SCAN_CACHE[key] = scan
            _SCAN_CACHE.move_to_end(key)
            while len(_SCAN_CACHE) > _SCAN_CACHE_MAX:
                _SCAN_CACHE.popitem(last=False)
    return scan


def clear_sequence_cache() -> None:
    """Drop every cached directory scan (test and maintenance seam)."""
    with _CACHE_LOCK:
        _SCAN_CACHE.clear()


def find_neighbors(
    directory: str | Path, filename: str,
) -> SequenceNeighbors | None:
    """Locate *filename* inside its directory's frame sequences.

    Returns the previous/next frame paths (``None`` at the sequence ends),
    the 0-based frame index, the sequence frame count, and the full frame
    list for playback looping. Returns ``None`` when the file is not a
    sequence member (fewer than :data:`MIN_SEQUENCE_FRAMES` siblings share
    its prefix/extension) or the directory cannot be read.
    """
    folder = Path(directory)
    name = os.path.basename(str(filename))
    scan = _cached_scan(folder)
    if scan is None:
        return None
    hit = scan.index.get(name)
    if hit is None:
        return None
    group_pos, frame_pos = hit
    group = scan.groups[group_pos]
    prev_name = group.frames[frame_pos - 1] if frame_pos > 0 else None
    next_name = (
        group.frames[frame_pos + 1]
        if frame_pos + 1 < len(group.frames) else None
    )

    def full(member: str | None) -> str | None:
        return None if member is None else str(folder / member)

    return SequenceNeighbors(
        prev_path=full(prev_name),
        next_path=full(next_name),
        index=frame_pos,
        count=group.count,
        fps=None,
        frames=tuple(str(folder / member) for member in group.frames),
    )
