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
    # Flush to disk so concurrent gallery background threads never read a
    # partial write (which surfaces as UnicodeDecodeError 0xb4 under -n auto
    # when Image.open() hits RGB data before the PNG header is committed).
    try:
        with open(path, "rb") as f:
            f.flush()
            import os
            os.fsync(f.fileno())
    except (OSError, AttributeError):
        pass


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


def _emit(service: GalleryService, root: Path, kind: str, paths, old_paths=()) -> None:
    """Feed one event straight into the service handler.

    Unlike ``_publish`` this bypasses the event bus: it is fully
    synchronous, so the issued seq can be asserted deterministically.
    """
    service._on_file_system_changed(FileSystemChanged(
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
        # Telemetry: the two-path created batch applied as one incremental
        # event (a silent full-rebuild fallback would match the oracle too).
        applied, fallbacks = service.incremental_stats
        assert applied == 1 and fallbacks == 0
    finally:
        service.close()


def _wait_state(service: GalleryService, root: Path, before, predicate, deadline: float = 10.0):
    """Poll until the incremental apply commits and *predicate* holds.

    The apply mutates the private snapshot before it atomically publishes
    the rebuilt home to the cache; observing the snapshot mutation alone is
    not a commit signal — the cache still holds the pre-event home at that
    point, and comparing it against a fresh oracle would race the commit.
    ``before`` is the cached home response captured immediately before the
    event was published; the wait only ends once the cached response has
    moved past it *and* the predicate holds on the snapshot.
    """
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        state = service._home_states.get(_root_key(root))
        home = service.get_home_cached(root)
        committed = home is not None and home.to_response() != before
        if state is not None and committed and predicate(state):
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
        before = service.get_home_cached(tmp_path).to_response()
        _publish(tmp_path, "deleted", [tmp_path / "a" / "note.txt"])
        _wait_state(service, tmp_path, before, lambda state: "a/note.txt" not in state.files)
        incremental = service.get_home_cached(tmp_path)
        oracle = _oracle(service, tmp_path)
        assert incremental is not None and incremental.to_response() == oracle.to_response()

        # Deleting the cover recomputes it from the remaining direct images.
        (tmp_path / "a" / "one.png").unlink()
        before = service.get_home_cached(tmp_path).to_response()
        _publish(tmp_path, "deleted", [tmp_path / "a" / "one.png"])
        _wait_state(service, tmp_path, before, lambda state: "a/one.png" not in state.files)
        incremental = service.get_home_cached(tmp_path)
        oracle = _oracle(service, tmp_path)
        assert incremental is not None and incremental.to_response() == oracle.to_response()
        # Telemetry: both deletions applied incrementally (the mtime setup
        # keeps each deleted file off the parent's max, so neither needs a
        # fallback rebuild).
        applied, fallbacks = service.incremental_stats
        assert applied == 2 and fallbacks == 0
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
        before = service.get_home_cached(tmp_path).to_response()
        _publish(tmp_path, "moved", [renamed], [tmp_path / "a" / "one.png"])
        _wait_state(service, tmp_path, before, lambda state: "a/renamed.png" in state.files)
        incremental = service.get_home_cached(tmp_path)
        oracle = _oracle(service, tmp_path)
        assert incremental is not None and incremental.to_response() == oracle.to_response()

        moved = tmp_path / "a" / "moved.png"
        (tmp_path / "b" / "other.png").rename(moved)
        before = service.get_home_cached(tmp_path).to_response()
        _publish(tmp_path, "moved", [moved], [tmp_path / "b" / "other.png"])
        _wait_state(
            service, tmp_path, before,
            lambda state: "a/moved.png" in state.files and "b/other.png" not in state.files,
        )
        incremental = service.get_home_cached(tmp_path)
        oracle = _oracle(service, tmp_path)
        assert incremental is not None and incremental.to_response() == oracle.to_response()
        # Telemetry: both moves (same-parent rename and cross-parent move)
        # applied incrementally; the extra newer files in each source parent
        # keep the moved files off the max mtime so no fallback is needed.
        applied, fallbacks = service.incremental_stats
        assert applied == 2 and fallbacks == 0
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
        home = _wait_artworks(service, tmp_path, 2)
        oracle = _oracle(service, tmp_path)
        assert home.to_response() == oracle.to_response()
        # Telemetry: the replay was consumed by the incremental path's
        # idempotent guard (it counts as an applied event) instead of
        # falling back to a full rebuild.
        applied, fallbacks = service.incremental_stats
        assert applied == 2 and fallbacks == 0
    finally:
        service.close()


def test_incremental_directory_created_matches_full_rebuild(tmp_path, schema_db, monkeypatch):
    _image(tmp_path / "a" / "one.png", (40, 40))
    service = _make_service(schema_db, monkeypatch)
    try:
        assert _settle(service, tmp_path) is not None
        new_dir = tmp_path / "newdir"
        new_dir.mkdir()
        _image(new_dir / "art.png", (15, 15))
        before = service.get_home_cached(tmp_path).to_response()
        _publish(tmp_path, "created", [new_dir])
        _wait_state(service, tmp_path, before, lambda state: "newdir" in state.nodes)
        incremental = service.get_home_cached(tmp_path)
        oracle = _oracle(service, tmp_path)
        assert incremental is not None and incremental.to_response() == oracle.to_response()
        # Telemetry: the directory creation sub-walked incrementally.
        applied, fallbacks = service.incremental_stats
        assert applied == 1 and fallbacks == 0
    finally:
        service.close()


def test_empty_directory_created_is_a_noop(tmp_path, schema_db, monkeypatch):
    """Empty directories are pruned from the projection: creating one is a
    net no-op (the state stays valid and the oracle still matches)."""
    _image(tmp_path / "a" / "one.png", (40, 40))
    service = _make_service(schema_db, monkeypatch)
    try:
        assert _settle(service, tmp_path) is not None
        empty_dir = tmp_path / "a" / "empty"
        empty_dir.mkdir()
        _publish(tmp_path, "created", [empty_dir])
        time.sleep(0.5)
        assert _root_key(tmp_path) in service._home_states
        cached = service.get_home_cached(tmp_path)
        oracle = _oracle(service, tmp_path)
        assert cached is not None and cached.to_response() == oracle.to_response()
        # Telemetry: the empty directory was handled by the incremental
        # path as a pruned no-op, not by a fallback rebuild.
        applied, fallbacks = service.incremental_stats
        assert applied == 1 and fallbacks == 0
    finally:
        service.close()


def test_incremental_directory_deleted_prunes_and_matches_full_rebuild(tmp_path, schema_db, monkeypatch):
    import os
    import shutil

    base = time.time()
    _image(tmp_path / "a" / "keep.png", (40, 40))
    os.utime(tmp_path / "a" / "keep.png", (base - 3600, base - 3600))
    (tmp_path / "b").mkdir()
    _image(tmp_path / "b" / "nested" / "gone.png", (15, 15))
    # The deleted subtree must not carry the root's max mtime (that case
    # deliberately falls back to a full rebuild).
    os.utime(tmp_path / "b" / "nested" / "gone.png", (base - 7200, base - 7200))
    service = _make_service(schema_db, monkeypatch)
    try:
        assert _settle(service, tmp_path) is not None
        shutil.rmtree(tmp_path / "b")
        before = service.get_home_cached(tmp_path).to_response()
        _publish(tmp_path, "deleted", [tmp_path / "b"])
        _wait_state(service, tmp_path, before, lambda state: "b" not in state.nodes)
        incremental = service.get_home_cached(tmp_path)
        oracle = _oracle(service, tmp_path)
        assert incremental is not None and incremental.to_response() == oracle.to_response()
        # Telemetry: the subtree deletion pruned incrementally (the deleted
        # subtree does not carry the root's max mtime).
        applied, fallbacks = service.incremental_stats
        assert applied == 1 and fallbacks == 0
    finally:
        service.close()


def test_incremental_directory_rename_matches_full_rebuild(tmp_path, schema_db, monkeypatch):
    _image(tmp_path / "a" / "sub" / "art.png", (15, 15))
    service = _make_service(schema_db, monkeypatch)
    try:
        assert _settle(service, tmp_path) is not None
        renamed = tmp_path / "a" / "renamed-sub"
        (tmp_path / "a" / "sub").rename(renamed)
        before = service.get_home_cached(tmp_path).to_response()
        _publish(tmp_path, "moved", [renamed], [tmp_path / "a" / "sub"])
        _wait_state(service, tmp_path, before, lambda state: "a/renamed-sub" in state.nodes)
        incremental = service.get_home_cached(tmp_path)
        oracle = _oracle(service, tmp_path)
        assert incremental is not None and incremental.to_response() == oracle.to_response()
        # Telemetry: the same-parent directory rename applied incrementally.
        applied, fallbacks = service.incremental_stats
        assert applied == 1 and fallbacks == 0
    finally:
        service.close()


def test_incremental_directory_cross_parent_move_matches_full_rebuild(tmp_path, schema_db, monkeypatch):
    import os

    base = time.time()
    (tmp_path / "a").mkdir()
    _image(tmp_path / "a" / "keep.png", (40, 40))
    os.utime(tmp_path / "a" / "keep.png", (base - 3600, base - 3600))
    (tmp_path / "b").mkdir()
    _image(tmp_path / "b" / "sub" / "art.png", (15, 15))
    os.utime(tmp_path / "b", (base - 7200, base - 7200))
    service = _make_service(schema_db, monkeypatch)
    try:
        assert _settle(service, tmp_path) is not None
        moved = tmp_path / "a" / "sub"
        (tmp_path / "b" / "sub").rename(moved)
        before = service.get_home_cached(tmp_path).to_response()
        _publish(tmp_path, "moved", [moved], [tmp_path / "b" / "sub"])
        _wait_state(service, tmp_path, before, lambda state: "a/sub" in state.nodes)
        incremental = service.get_home_cached(tmp_path)
        oracle = _oracle(service, tmp_path)
        assert incremental is not None and incremental.to_response() == oracle.to_response()
        # Telemetry: the cross-parent directory move applied as one
        # incremental event (delete + sub-walk internally, no fallback).
        applied, fallbacks = service.incremental_stats
        assert applied == 1 and fallbacks == 0
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
        # Telemetry: this event can never be applied incrementally — the
        # snapshot has no "fresh" node to attach the new file to (its parent
        # directory was created empty and pruned). Two legitimate rebuild
        # routes exist and both keep applied == 0:
        #   * the apply raises "unknown parent" and counts a fallback, or
        #   * the shortened cache TTL (0.05s) triggers a stale-cache full
        #     rebuild first, which advances the generation and silently
        #     supersedes the queued event (no fallback counted).
        # fallbacks is therefore intentionally not pinned; the eventual
        # oracle match above is the correctness signal for this scenario.
        applied, _fallbacks = service.incremental_stats
        assert applied == 0
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
        # Telemetry: the opposing events cancelled out inside the debounce
        # window — zero events applied, zero fallbacks, snapshot intact.
        applied, fallbacks = service.incremental_stats
        assert applied == 0 and fallbacks == 0
    finally:
        service.close()


def test_incremental_telemetry_counts_applied_and_fallbacks(tmp_path, schema_db, monkeypatch):
    """incremental_stats reports applied events and fallback rebuilds."""
    _image(tmp_path / "a" / "one.png", (40, 40))
    service = _make_service(schema_db, monkeypatch)
    try:
        assert _settle(service, tmp_path) is not None
        _image(tmp_path / "a" / "two.png", (20, 20))
        before = service.get_home_cached(tmp_path).to_response()
        _publish(tmp_path, "created", [tmp_path / "a" / "two.png"])
        _wait_state(service, tmp_path, before, lambda state: "a/two.png" in state.files)
        applied, fallbacks = service.incremental_stats
        assert applied == 1 and fallbacks == 0

        # Unsupported kinds (e.g. the generic "files" batch signal) fall back.
        _publish(tmp_path, "files", [tmp_path / "a" / "two.png"])
        end = time.monotonic() + 10
        while time.monotonic() < end and service.incremental_stats[1] < 1:
            time.sleep(0.05)
        assert service.incremental_stats[1] >= 1
    finally:
        service.close()


def test_incremental_project_created_at_floor_matches_full_rebuild(tmp_path, schema_db, monkeypatch):
    """A directory created exactly at the project floor aggregates its whole
    subtree incrementally (regression for the H-G1 deep review finding: the
    created side used to drop nested content and project a truncated node)."""
    import os

    base = time.time()
    _image(tmp_path / "branch" / "proj" / "one.png", (20, 20))
    os.utime(tmp_path / "branch" / "proj" / "one.png", (base - 7200, base - 7200))
    service = _make_service(schema_db, monkeypatch)
    try:
        assert _settle(service, tmp_path) is not None

        # Create a new project at the floor with nested content (directory
        # event arrives after the files exist on disk).
        _image(tmp_path / "branch" / "newproj" / "inner" / "a.png", (16, 16))
        _image(tmp_path / "branch" / "newproj" / "cover.png", (40, 40))
        (tmp_path / "branch" / "newproj" / "readme.txt").write_text("x")
        _publish(tmp_path, "created", [tmp_path / "branch" / "newproj"])

        _wait_artworks(service, tmp_path, 3)
        incremental = service.get_home_cached(tmp_path)
        oracle = _oracle(service, tmp_path)
        assert incremental is not None and incremental.to_response() == oracle.to_response()
        # The new project is a leaf node aggregating its whole subtree.
        state = service._home_states[_root_key(tmp_path)]
        newproj = state.nodes["branch/newproj"]
        assert newproj.summary["artwork_count"] == 2
        assert newproj.summary["file_count"] == 3
        assert newproj.children == []
        # Telemetry: the floor-level directory event aggregated its subtree
        # incrementally (a full-rebuild fallback would match the oracle too).
        applied, fallbacks = service.incremental_stats
        assert applied == 1 and fallbacks == 0
    finally:
        service.close()


# ── Seq/generation watermark semantics ──────────────────────────────
#
# The seq counter only issues seqs to queued events; a snapshot's
# generation is the watermark of events it covers (the counter value
# captured before a full walk, or the max seq applied by a window).
# Historically the build/apply bumped the counter again at publish time,
# which tracked over (and silently dropped) every event queued while the
# walk/apply was running.


def test_event_queued_during_apply_window_is_applied_next_window(
    tmp_path, schema_db, monkeypatch
):
    """An event that arrives while an incremental apply window is open must
    survive to the next window instead of being filtered out by the publish
    bumping the seq counter past its seq."""
    _image(tmp_path / "a" / "one.png", (40, 40))
    service = _make_service(schema_db, monkeypatch)
    # Drive the apply windows manually for determinism.
    monkeypatch.setattr(service, "_schedule_incremental_apply", lambda _root: None)
    try:
        service.get_home(tmp_path)
        root_key = _root_key(tmp_path)
        state = service._home_states[root_key]
        assert state.generation == 0

        # Window 1 applies two.png; while the window is still open (inside
        # the recompose pass) three.png arrives and is queued.
        _image(tmp_path / "a" / "two.png", (20, 20))
        _emit(service, tmp_path, "created", [tmp_path / "a" / "two.png"])
        published: dict[str, int] = {}
        real_recompose = service._recompose_home

        def recompose_and_queue(root, state_, conn):
            if "seq" not in published:
                _image(tmp_path / "a" / "three.png", (14, 14))
                _emit(service, tmp_path, "created", [tmp_path / "a" / "three.png"])
                published["seq"] = service._home_generation
            return real_recompose(root, state_, conn)

        monkeypatch.setattr(service, "_recompose_home", recompose_and_queue)

        service._apply_pending_home_impl(root_key)
        # The window's watermark is the max applied seq (1), NOT a freshly
        # issued counter value; the counter only issued the two seqs.
        assert state.generation == 1
        assert published["seq"] == 2
        assert service._home_generation == 2

        # Next window: the mid-window event passes the seq > generation
        # filter and is applied (the pre-fix behavior dropped it forever).
        service._apply_pending_home_impl(root_key)
        assert "a/three.png" in state.files
        assert state.generation == 2
        cached = service.get_home_cached(tmp_path)
        assert cached is not None and cached.stats["artworks"] == 3
        applied, fallbacks = service.incremental_stats
        assert applied == 2 and fallbacks == 0
    finally:
        service.close()


def test_event_queued_during_full_walk_is_not_dropped(tmp_path, schema_db, monkeypatch):
    """An event queued while a full home rebuild walks the library gets a
    seq above the captured start watermark, so the next apply window picks
    it up instead of the publish advancing past it."""
    _image(tmp_path / "a" / "one.png", (40, 40))
    service = _make_service(schema_db, monkeypatch)
    monkeypatch.setattr(service, "_schedule_incremental_apply", lambda _root: None)
    try:
        service.get_home(tmp_path)  # initial snapshot so events queue

        # During the second full walk, once the "a" subtree has been
        # scanned, create a file and queue its event.
        published: dict[str, int] = {}
        real_build_node = service._build_node

        def build_node_and_queue(root, rel, target, **kwargs):
            node = real_build_node(root, rel, target, **kwargs)
            if rel == "a" and "seq" not in published:
                _image(tmp_path / "a" / "mid.png", (12, 12))
                _emit(service, tmp_path, "created", [tmp_path / "a" / "mid.png"])
                published["seq"] = service._home_generation
            return node

        monkeypatch.setattr(service, "_build_node", build_node_and_queue)
        service._compute_home(str(tmp_path))

        root_key = _root_key(tmp_path)
        state = service._home_states[root_key]
        # The published watermark is the counter value captured before the
        # walk started; the mid-walk event's seq is strictly above it.
        assert state.generation == 0
        assert published["seq"] == 1
        assert state.generation < published["seq"]

        service._apply_pending_home_impl(root_key)
        assert "a/mid.png" in state.files
        cached = service.get_home_cached(tmp_path)
        assert cached is not None and cached.stats["artworks"] == 2
        applied, fallbacks = service.incremental_stats
        assert applied == 1 and fallbacks == 0
    finally:
        service.close()


# ── Full-rebuild timer: fixed deadline under sustained events ───────


def test_full_rebuild_timer_survives_repeated_invalidates(
    tmp_path, schema_db, monkeypatch
):
    """In the no-snapshot window every event invalidates, but only the
    first one arms the rebuild timer: later invalidates for the same root
    must keep the pending fixed deadline instead of restarting the TTL."""
    _image(tmp_path / "a" / "one.png", (32, 16))
    service = _make_service(schema_db, monkeypatch)
    monkeypatch.setattr(service, "_home_cache_ttl", 0.25)
    root_key = _root_key(tmp_path)
    try:
        _emit(service, tmp_path, "created", [tmp_path / "a" / "one.png"])
        timer1 = service._refresh_timer
        assert timer1 is not None
        assert service._refresh_timer_root == root_key

        for _ in range(5):
            _emit(service, tmp_path, "created", [tmp_path / "a" / "one.png"])
            # Fixed deadline: the pending timer is never replaced.
            assert service._refresh_timer is timer1

        # The rebuild fires on the original deadline even though events
        # kept invalidating. Poll the private cache: get_home_cached would
        # itself kick a build on a miss and mask the timer's work.
        end = time.monotonic() + 10.0
        while time.monotonic() < end:
            with service._home_cache_lock:
                if root_key in service._home_cache:
                    break
            time.sleep(0.05)
        with service._home_cache_lock:
            assert root_key in service._home_cache
        assert service._refresh_timer_root is None
    finally:
        service.close()


def test_rebuild_fires_while_event_stream_continues(tmp_path, schema_db, monkeypatch):
    """Behavioral: while events keep arriving in the no-snapshot window,
    the full rebuild still happens (at the first fixed deadline) instead of
    being pushed out indefinitely by the stream."""
    _image(tmp_path / "a" / "one.png", (32, 16))
    service = _make_service(schema_db, monkeypatch)
    monkeypatch.setattr(service, "_home_cache_ttl", 0.3)
    root_key = _root_key(tmp_path)
    try:
        end = time.monotonic() + 3.0
        filled = False
        while time.monotonic() < end:
            _emit(service, tmp_path, "created", [tmp_path / "a" / "one.png"])
            time.sleep(0.05)
            with service._home_cache_lock:
                if root_key in service._home_cache:
                    filled = True
                    break
        assert filled, "full rebuild never fired while the event stream continued"
    finally:
        service.close()
