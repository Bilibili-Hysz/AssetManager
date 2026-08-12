"""Incremental gallery home update tests.

The core assertion strategy is oracle comparison: after incremental events
are applied, the cached home must be byte-identical to a fresh full
rebuild of the same library. Scenarios that must fall back (directory
events, max-mtime deletions, unknown parents) assert eventual consistency
instead.
"""
from __future__ import annotations

import time
from pathlib import Path

from PIL import Image

from AssetsManager.application.gallery_service import GalleryService
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import FileSystemChanged


def _image(path: Path, size: tuple[int, int] = (32, 16), color: tuple[int, int, int] = (20, 80, 180)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


def _root_key(root: Path) -> str:
    return str(Path(root).resolve())


def _settle(service: GalleryService, root: Path, deadline: float = 10.0):
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        cached = service.get_home_cached(root)
        if cached is not None:
            return cached
        time.sleep(0.05)
    return None


def _publish(root: Path, kind: str, paths, old_paths=()):
    get_event_bus().publish(FileSystemChanged(
        library_root=str(root), session_token="test", kind=kind,
        paths=tuple(str(path) for path in paths),
        old_paths=tuple(str(path) for path in old_paths),
    ))


def _wait_artworks(service: GalleryService, root: Path, expected: int, deadline: float = 10.0):
    """Poll the cached home until its artwork count reaches *expected*."""
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        home = service.get_home_cached(root)
        if home is not None and home.stats["artworks"] == expected:
            return home
        time.sleep(0.05)
    home = service.get_home_cached(root)
    raise AssertionError(
        f"artwork count never reached {expected}; got {home.stats if home else None}"
    )


def _oracle(service: GalleryService, root: Path):
    """Force a fresh full rebuild and return it as the reference."""
    with service._home_cache_lock:
        service._home_cache.pop(_root_key(root), None)
        service._home_states.pop(_root_key(root), None)
    return service.get_home(root)


def _make_service(schema_db, monkeypatch) -> GalleryService:
    service = GalleryService(connection_provider=lambda _root: schema_db)
    monkeypatch.setattr(service, "_incremental_debounce", 0.05)
    return service


def test_incremental_created_files_match_full_rebuild(tmp_path, schema_db, monkeypatch):
    _image(tmp_path / "a" / "one.png", (40, 40))
    _image(tmp_path / "a" / "sub" / "seed.png", (10, 10))
    service = _make_service(schema_db, monkeypatch)
    try:
        assert _settle(service, tmp_path) is not None
        _image(tmp_path / "a" / "two.png", (20, 20))
        _image(tmp_path / "a" / "sub" / "deep.png", (30, 30))
        _publish(tmp_path, "created", [
            tmp_path / "a" / "two.png", tmp_path / "a" / "sub" / "deep.png",
        ])
        _wait_artworks(service, tmp_path, 4)
        incremental = service.get_home_cached(tmp_path)
        oracle = _oracle(service, tmp_path)
        assert incremental is not None and incremental.to_response() == oracle.to_response()
    finally:
        service.close()


def _wait_state(service: GalleryService, root: Path, predicate, deadline: float = 10.0):
    """Poll until the incremental state satisfies *predicate*."""
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        state = service._home_states.get(_root_key(root))
        if state is not None and predicate(state):
            return state
        time.sleep(0.05)
    raise AssertionError("incremental state never satisfied the condition")


def test_incremental_delete_of_cover_and_plain_file(tmp_path, schema_db, monkeypatch):
    import os

    base = time.time()
    _image(tmp_path / "a" / "one.png", (40, 40))  # cover (path-sorted first)
    os.utime(tmp_path / "a" / "one.png", (base - 7200, base - 7200))
    _image(tmp_path / "a" / "two.png", (20, 20))
    os.utime(tmp_path / "a" / "two.png", (base - 3600, base - 3600))
    with open(tmp_path / "a" / "note.txt", "wb") as fh:
        fh.write(b"x" * 64)
    # Distinct, older mtimes keep every deletion pure arithmetic (deleting
    # the max-mtime file deliberately falls back to a full rebuild).
    os.utime(tmp_path / "a" / "note.txt", (base - 10800, base - 10800))
    service = _make_service(schema_db, monkeypatch)
    try:
        assert _settle(service, tmp_path) is not None
        (tmp_path / "a" / "note.txt").unlink()
        _publish(tmp_path, "deleted", [tmp_path / "a" / "note.txt"])
        _wait_state(service, tmp_path, lambda state: "a/note.txt" not in state.files)
        incremental = service.get_home_cached(tmp_path)
        oracle = _oracle(service, tmp_path)
        assert incremental is not None and incremental.to_response() == oracle.to_response()

        # Deleting the cover recomputes it from the remaining direct images.
        (tmp_path / "a" / "one.png").unlink()
        _publish(tmp_path, "deleted", [tmp_path / "a" / "one.png"])
        _wait_state(service, tmp_path, lambda state: "a/one.png" not in state.files)
        incremental = service.get_home_cached(tmp_path)
        oracle = _oracle(service, tmp_path)
        assert incremental is not None and incremental.to_response() == oracle.to_response()
    finally:
        service.close()


def test_incremental_rename_and_cross_parent_move(tmp_path, schema_db, monkeypatch):
    import os

    base = time.time()
    _image(tmp_path / "a" / "one.png", (40, 40))
    os.utime(tmp_path / "a" / "one.png", (base - 7200, base - 7200))
    _image(tmp_path / "a" / "extra.png", (12, 12))  # newer: keeps one.png off the max
    os.utime(tmp_path / "a" / "extra.png", (base - 3600, base - 3600))
    _image(tmp_path / "b" / "other.png", (20, 20))
    os.utime(tmp_path / "b" / "other.png", (base - 7200, base - 7200))
    _image(tmp_path / "b" / "extra2.png", (14, 14))  # newer: keeps other.png off the max
    os.utime(tmp_path / "b" / "extra2.png", (base - 3600, base - 3600))
    service = _make_service(schema_db, monkeypatch)
    try:
        assert _settle(service, tmp_path) is not None
        renamed = tmp_path / "a" / "renamed.png"
        (tmp_path / "a" / "one.png").rename(renamed)
        _publish(tmp_path, "moved", [renamed], [tmp_path / "a" / "one.png"])
        _wait_state(service, tmp_path, lambda state: "a/renamed.png" in state.files)
        incremental = service.get_home_cached(tmp_path)
        oracle = _oracle(service, tmp_path)
        assert incremental is not None and incremental.to_response() == oracle.to_response()

        moved = tmp_path / "a" / "moved.png"
        (tmp_path / "b" / "other.png").rename(moved)
        _publish(tmp_path, "moved", [moved], [tmp_path / "b" / "other.png"])
        _wait_state(
            service, tmp_path,
            lambda state: "a/moved.png" in state.files and "b/other.png" not in state.files,
        )
        incremental = service.get_home_cached(tmp_path)
        oracle = _oracle(service, tmp_path)
        assert incremental is not None and incremental.to_response() == oracle.to_response()
    finally:
        service.close()


def test_incremental_apply_is_idempotent_for_replayed_events(tmp_path, schema_db, monkeypatch):
    _image(tmp_path / "a" / "one.png", (40, 40))
    service = _make_service(schema_db, monkeypatch)
    try:
        assert _settle(service, tmp_path) is not None
        _image(tmp_path / "a" / "two.png", (20, 20))
        _publish(tmp_path, "created", [tmp_path / "a" / "two.png"])
        _publish(tmp_path, "created", [tmp_path / "a" / "two.png"])  # replay
        time.sleep(0.5)
        home = service.get_home_cached(tmp_path)
        assert home is not None and home.stats["artworks"] == 2
        oracle = _oracle(service, tmp_path)
        assert home.to_response() == oracle.to_response()
    finally:
        service.close()


def test_directory_event_falls_back_to_full_rebuild(tmp_path, schema_db, monkeypatch):
    _image(tmp_path / "a" / "one.png", (40, 40))
    service = _make_service(schema_db, monkeypatch)
    monkeypatch.setattr(service, "_home_cache_ttl", 0.05)
    try:
        assert _settle(service, tmp_path) is not None
        new_dir = tmp_path / "newdir"
        new_dir.mkdir()
        _image(new_dir / "art.png", (15, 15))
        _publish(tmp_path, "created", [new_dir])
        # The directory event is not incrementally appliable; the state is
        # dropped and a full rebuild lands the new artwork.
        _wait_artworks(service, tmp_path, 2)
        assert _root_key(tmp_path) in service._home_states
    finally:
        service.close()


def test_unknown_parent_created_falls_back_to_full_rebuild(tmp_path, schema_db, monkeypatch):
    _image(tmp_path / "a" / "one.png", (40, 40))
    service = _make_service(schema_db, monkeypatch)
    monkeypatch.setattr(service, "_home_cache_ttl", 0.05)
    try:
        assert _settle(service, tmp_path) is not None
        fresh_dir = tmp_path / "fresh"
        fresh_dir.mkdir()  # not in the snapshot (empty dirs are pruned)
        _image(fresh_dir / "art.png", (15, 15))
        _publish(tmp_path, "created", [fresh_dir / "art.png"])
        _wait_artworks(service, tmp_path, 2)
        oracle = _oracle(service, tmp_path)
        cached = service.get_home_cached(tmp_path)
        assert cached is not None and cached.to_response() == oracle.to_response()
    finally:
        service.close()


def test_opposing_changes_cancel_and_fold():
    from AssetsManager.application.gallery_service import _QueuedChange

    cancel = GalleryService._cancel_opposing_changes

    def c(kind, paths, old_paths=()):
        return _QueuedChange(kind, tuple(paths), tuple(old_paths), 1)

    # created then deleted within one burst: net zero.
    assert cancel([c("created", ["a/x.png"]), c("deleted", ["a/x.png"])]) == []
    # deleted then created: the file was replaced; both events must apply.
    kept = cancel([c("deleted", ["a/x.png"]), c("created", ["a/x.png"])])
    assert [change.kind for change in kept] == ["deleted", "created"]
    # move round-trip A->B then B->A: net zero.
    assert cancel([c("moved", ["B"], ["A"]), c("moved", ["A"], ["B"])]) == []
    # move chain A->B then B->C folds to A->C.
    folded = cancel([c("moved", ["B"], ["A"]), c("moved", ["C"], ["B"])])
    assert len(folded) == 1
    assert folded[0].old_paths == ("A",)
    assert folded[0].paths == ("C",)
    # unrelated events pass through untouched.
    kept = cancel([c("created", ["a/1.png"]), c("created", ["a/2.png"])])
    assert len(kept) == 2


def test_create_then_delete_in_one_burst_is_a_net_noop(tmp_path, schema_db, monkeypatch):
    """A file created and deleted inside one debounce window cancels out:
    no fallback, the snapshot stays valid, and the oracle still matches."""
    _image(tmp_path / "a" / "one.png", (40, 40))
    service = _make_service(schema_db, monkeypatch)
    monkeypatch.setattr(service, "_incremental_debounce", 0.2)
    try:
        assert _settle(service, tmp_path) is not None
        temp_file = tmp_path / "a" / "temp.png"
        _image(temp_file, (8, 8))
        _publish(tmp_path, "created", [temp_file])
        temp_file.unlink()
        _publish(tmp_path, "deleted", [temp_file])
        time.sleep(0.6)
        state = service._home_states.get(_root_key(tmp_path))
        assert state is not None  # a fallback would have dropped the state
        assert "a/temp.png" not in state.files
        cached = service.get_home_cached(tmp_path)
        oracle = _oracle(service, tmp_path)
        assert cached is not None and cached.to_response() == oracle.to_response()
    finally:
        service.close()


def test_incremental_telemetry_counts_applied_and_fallbacks(tmp_path, schema_db, monkeypatch):
    """incremental_stats reports applied events and fallback rebuilds."""
    _image(tmp_path / "a" / "one.png", (40, 40))
    service = _make_service(schema_db, monkeypatch)
    try:
        assert _settle(service, tmp_path) is not None
        _image(tmp_path / "a" / "two.png", (20, 20))
        _publish(tmp_path, "created", [tmp_path / "a" / "two.png"])
        _wait_state(service, tmp_path, lambda state: "a/two.png" in state.files)
        applied, fallbacks = service.incremental_stats
        assert applied == 1 and fallbacks == 0

        new_dir = tmp_path / "newdir"
        new_dir.mkdir()
        _image(new_dir / "art.png", (15, 15))
        _publish(tmp_path, "created", [new_dir])
        end = time.monotonic() + 10
        while time.monotonic() < end and service.incremental_stats[1] < 1:
            time.sleep(0.05)
        assert service.incremental_stats[1] >= 1
    finally:
        service.close()
