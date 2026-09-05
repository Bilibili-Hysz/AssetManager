from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from PIL import Image

from AssetsManager.application.gallery_service import (
    GalleryService,
    GalleryTraversalLimitError,
    GalleryTraversalLimits,
)
from AssetsManager.domain.errors import MissingPathError, PathEscapeError


def _image(path: Path, size: tuple[int, int] = (32, 16), color: tuple[int, int, int] = (20, 80, 180)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


def test_gallery_home_projects_collections_and_recent_projection(tmp_path, schema_db):
    _image(tmp_path / "collection" / "cover.jpg", (40, 40))
    _image(tmp_path / "collection" / "project" / "wide.png", (120, 60))
    (tmp_path / "collection" / "project" / "source.psd").write_bytes(b"source")
    (tmp_path / "empty").mkdir()

    service = GalleryService(connection_provider=lambda _root: schema_db)
    response = service.get_home(tmp_path).to_response()

    assert response["featured"]["path"] == "collection"
    assert [entry["path"] for entry in response["collections"]] == ["collection"]
    assert [entry["path"] for entry in response["projects"]] == []
    assert response["stats"] == {
        "collections": 1,
        "projects": 1,
        "artworks": 2,
        "total_size_fmt": response["stats"]["total_size_fmt"],
    }
    assert {entry["path"] for entry in response["recent"]} == {
        "collection/cover.jpg",
        "collection/project/wide.png",
    }
    project = response["collections"][0]["path"]
    assert project == "collection"
    assert response["collections"][0]["artwork_count"] == 2
    assert response["collections"][0]["file_count"] == 3
    # The service is transport-free: it exposes cover_path only; URL assembly
    # is the LAN route layer's job (see test_url_projection_contract.py).
    assert response["collections"][0]["cover_path"] == "collection/cover.jpg"
    assert "cover_url" not in response["collections"][0]


def test_gallery_collection_returns_child_summaries_and_filtered_entries(tmp_path, schema_db):
    _image(tmp_path / "set" / "first.png", (10, 20))
    _image(tmp_path / "set" / "second.jpg", (20, 10))
    _image(tmp_path / "set" / "nested" / "third.webp")

    service = GalleryService(connection_provider=lambda _root: schema_db)
    all_entries = service.get_collection(tmp_path, "set", sort="name", kind="all")
    assert all_entries is not None
    assert [entry["name"] for entry in all_entries.entries] == ["first.png", "second.jpg"]
    assert [entry["path"] for entry in all_entries.children] == ["set/nested"]
    assert all_entries.collection["kind"] == "collection"

    artwork_entries = service.get_collection(tmp_path, "set", sort="updated", kind="artwork")
    assert artwork_entries is not None
    assert len(artwork_entries.entries) == 2
    assert all(entry["kind"] == "artwork" for entry in artwork_entries.entries)
    assert all_entries.next_cursor is None


def test_gallery_resolve_uses_library_relative_contexts(tmp_path, schema_db):
    _image(tmp_path / "folder" / "art.png", (80, 40))
    (tmp_path / "folder" / "notes.txt").write_text("notes", encoding="utf-8")

    service = GalleryService(connection_provider=lambda _root: schema_db)
    artwork = service.resolve(tmp_path, "folder/art.png").to_response()
    project = service.resolve(tmp_path, "folder").to_response()

    assert artwork == {
        "kind": "artwork",
        "path": "folder/art.png",
        "gallery_context": "folder",
        "workspace_context": "folder",
    }
    assert project["kind"] == "project"
    assert project["path"] == "folder"
    assert project["gallery_context"] == "folder"
    assert project["workspace_context"] == "folder"

    with pytest.raises(MissingPathError):
        service.resolve(tmp_path, "missing")
    with pytest.raises(ValueError, match="path escape"):
        service.resolve(tmp_path, "../outside")


def test_gallery_tag_projection_is_batched_and_relative_paths_are_not_exposed(tmp_path, schema_db):
    artwork = tmp_path / "collection" / "art.png"
    _image(artwork)
    schema_db.execute(
        "INSERT INTO file_tags (file_path, tag) VALUES (?, ?)",
        (str(artwork.resolve()), "featured"),
    )
    schema_db.commit()

    service = GalleryService(connection_provider=lambda _root: schema_db)
    response = service.get_collection(tmp_path, "collection")
    assert response is not None
    assert response.entries[0]["tags"] == ["featured"]
    assert all(not value.startswith(str(tmp_path)) for value in response.entries[0].values() if isinstance(value, str))


def test_gallery_traversal_budget_is_enforced(tmp_path, schema_db):
    _image(tmp_path / "set" / "one.png")
    service = GalleryService(
        connection_provider=lambda _root: schema_db,
        limits=GalleryTraversalLimits(max_entries=0),
    )

    with pytest.raises(GalleryTraversalLimitError):
        service.get_home(tmp_path)


def test_gallery_service_emits_no_transport_urls(tmp_path, schema_db):
    _image(tmp_path / "套件" / "hero image.png")

    service = GalleryService(connection_provider=lambda _root: schema_db)
    response = service.get_collection(tmp_path, "套件")

    assert response is not None
    entry = response.entries[0]
    # The service keeps the library-relative path only; the LAN route layer
    # is the single owner of thumbnail/image URL projection.
    assert entry["path"] == "套件/hero image.png"
    assert "thumbnail_url" not in entry
    assert "image_url" not in entry
    assert all(
        not (isinstance(value, str) and value.startswith("/api/"))
        for value in entry.values()
    )


def test_gallery_skips_external_symlink_and_rejects_symlink_path(tmp_path, schema_db):
    # The outside directory lives next to tmp_path (it must be outside the
    # library root) under a per-test name: a fixed name leaks across test
    # runs and workers, and symlink skips would leave it behind.
    outside = tmp_path.parent / f"gallery-outside-{tmp_path.name}"
    outside.mkdir()
    _image(outside / "secret.png")
    link = tmp_path / "external-link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        shutil.rmtree(outside, ignore_errors=True)
        pytest.skip(f"symlinks are unavailable: {exc}")

    try:
        service = GalleryService(connection_provider=lambda _root: schema_db)
        response = service.get_home(tmp_path).to_response()
        assert all(entry["path"] != "external-link" for entry in response["collections"])
        with pytest.raises(MissingPathError):
            service.get_collection(tmp_path, "external-link")

        # Rejecting an outside path is the contract; the error type differs by
        # platform because gallery entry paths are library-relative by
        # construction: on Windows a drive-absolute string keeps its root and
        # fails containment (PathEscapeError), while on POSIX the leading "/"
        # is dropped by _normalize_relative_path and the coerced in-root
        # candidate is rejected as missing/reparse (MissingPathError). Both
        # are fail-closed and never serve the outside file.
        with pytest.raises((PathEscapeError, MissingPathError)):
            service.resolve(tmp_path, str(outside / "secret.png"))
    finally:
        link.unlink(missing_ok=True)
        shutil.rmtree(outside, ignore_errors=True)


def test_gallery_skips_windows_junction_or_reparse_directory(tmp_path, schema_db):
    if not hasattr(Path, "is_junction") and os.name != "nt":
        pytest.skip("Windows junction/reparse points are unavailable on this platform")
    outside = tmp_path.parent / f"gallery-junction-outside-{tmp_path.name}"
    outside.mkdir()
    _image(outside / "secret.png")
    junction = tmp_path / "junction"
    if os.name == "nt":
        import subprocess

        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
            capture_output=True,
            text=True,
            # cmd.exe emits OEM-codepage text (e.g. GBK on a Chinese
            # locale); decoding it strictly as UTF-8 can raise
            # UnicodeDecodeError in subprocess's reader thread. The output
            # is only used for a skip message, so replace undecodable
            # bytes instead of failing the probe.
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode != 0:
            shutil.rmtree(outside, ignore_errors=True)
            pytest.skip(f"junction creation unavailable: {result.stderr or result.stdout}")
    else:
        shutil.rmtree(outside, ignore_errors=True)
        pytest.skip("Windows junction/reparse points are unavailable on this platform")

    try:
        service = GalleryService(connection_provider=lambda _root: schema_db)
        response = service.get_home(tmp_path).to_response()
        assert all(entry["path"] != "junction" for entry in response["collections"])
        with pytest.raises(MissingPathError):
            service.get_collection(tmp_path, "junction")
    finally:
        shutil.rmtree(outside, ignore_errors=True)


def test_gallery_enforces_entry_budget_while_scanning_one_directory(tmp_path, schema_db):
    for index in range(5):
        _image(tmp_path / "set" / f"{index}.png")
    service = GalleryService(
        connection_provider=lambda _root: schema_db,
        limits=GalleryTraversalLimits(max_entries=2),
    )

    with pytest.raises(GalleryTraversalLimitError, match="entry budget"):
        service.get_collection(tmp_path, "set")


def test_gallery_skips_svg_from_image_projection(tmp_path, schema_db):
    svg = tmp_path / "set" / "vector.svg"
    svg.parent.mkdir(parents=True)
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10"></svg>',
        encoding="utf-8",
    )
    _image(tmp_path / "set" / "raster.png")

    service = GalleryService(connection_provider=lambda _root: schema_db)
    response = service.get_collection(tmp_path, "set")

    assert response is not None
    assert [entry["name"] for entry in response.entries] == ["raster.png"]
    assert all("svg" not in entry["path"].lower() for entry in response.entries)
    assert service.resolve(tmp_path, "set/vector.svg").kind != "artwork"


def test_gallery_home_cache_hits_within_ttl_and_refreshes_after(tmp_path, schema_db, monkeypatch):
    """Repeated loads within the TTL skip the traversal; a later load rebuilds."""
    _image(tmp_path / "project" / "cover.jpg", (40, 40))

    service = GalleryService(connection_provider=lambda _root: schema_db)
    first = service.get_home(tmp_path)

    # Second call within the TTL must return the cached object (no rebuild).
    original_build = service._build_node
    monkeypatch.setattr(service, "_build_node", lambda *a, **k: (_ for _ in ()).throw(AssertionError("traversal must not rerun")))
    second = service.get_home(tmp_path)
    assert second is first

    # Expire the cache: the next call rebuilds and reflects new content.
    monkeypatch.setattr(service, "_build_node", original_build)
    monkeypatch.setattr(service, "_home_cache_ttl", 0.0)
    _image(tmp_path / "project" / "new.png", (20, 20))
    refreshed = service.get_home(tmp_path)
    assert refreshed is not first


def test_get_home_cached_builds_in_background_and_serves_cache(tmp_path, schema_db):
    """A cache miss returns None (the route answers 202) while a background
    build fills the cache; subsequent reads return the projection instantly."""
    import time

    _image(tmp_path / "collection" / "cover.jpg", (40, 40))
    service = GalleryService(connection_provider=lambda _root: schema_db)
    try:
        assert service.get_home_cached(tmp_path) is None
        deadline = time.monotonic() + 10.0
        cached = None
        while time.monotonic() < deadline:
            cached = service.get_home_cached(tmp_path)
            if cached is not None:
                break
            time.sleep(0.05)
        assert cached is not None
        assert cached.projects  # a single-level folder projects as 'project'
        # Second read is a cache hit and returns immediately.
        assert service.get_home_cached(tmp_path) is cached
    finally:
        service.close()


def test_home_cache_updates_incrementally_on_file_system_changes(tmp_path, schema_db, monkeypatch):
    """A supported file event is applied incrementally: the cached home
    reflects the change after the short debounce instead of being dropped."""
    import time

    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import FileSystemChanged

    _image(tmp_path / "set" / "one.png")
    service = GalleryService(connection_provider=lambda _root: schema_db)
    monkeypatch.setattr(service, "_incremental_debounce", 0.05)
    try:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and service.get_home_cached(tmp_path) is None:
            time.sleep(0.05)
        before = service.get_home_cached(tmp_path)
        assert before is not None and before.stats["artworks"] == 1

        applied_before, fallbacks_before = service.incremental_stats
        _image(tmp_path / "set" / "two.png")
        get_event_bus().publish(FileSystemChanged(
            library_root=str(tmp_path), session_token="test", kind="created",
            paths=(str(tmp_path / "set" / "two.png"),),
        ))
        deadline = time.monotonic() + 10.0
        after = None
        while time.monotonic() < deadline:
            after = service.get_home_cached(tmp_path)
            if after is not None and after.stats["artworks"] == 2:
                break
            time.sleep(0.05)
        assert after is not None and after.stats["artworks"] == 2
        # Verify incremental application: exactly 1 event applied, 0 fallbacks.
        applied_after, fallbacks_after = service.incremental_stats
        assert applied_after == applied_before + 1
        assert fallbacks_after == fallbacks_before
    finally:
        service.close()


def test_home_projection_persists_to_database_and_survives_restart(tmp_path, schema_db):
    """A built projection is written to the library database; a fresh service
    instance (simulating an app restart) loads it instead of rebuilding."""
    import time

    _image(tmp_path / "collection" / "art.png", (40, 40))

    first = GalleryService(connection_provider=lambda _root: schema_db)
    try:
        # The persisted database row is the only reliable commit signal here:
        # the builder publishes the memory cache before it writes the row, so
        # a cache hit does not imply the row exists yet. Under parallel-test
        # CPU contention the two moments separate and a cache-based assertion
        # races the commit. Poll the row (with a generous deadline) instead;
        # each get_home_cached miss arms the background build.
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            first.get_home_cached(tmp_path)
            row = schema_db.execute(
                "SELECT saved_at, projection FROM gallery_home WHERE id = 1"
            ).fetchone()
            if row is not None and row[1]:
                break
            time.sleep(0.05)
        else:
            pytest.fail(
                "home projection was not persisted to gallery_home within "
                "10.0s: the background build never committed a non-empty row"
            )
        assert first.get_home_cached(tmp_path) is not None
    finally:
        first.close()

    # A brand-new instance has no memory cache and must load the database
    # copy instead of answering building/None.
    second = GalleryService(connection_provider=lambda _root: schema_db)
    try:
        restored = second.get_home_cached(tmp_path)
        assert restored is not None
        assert restored.stats["artworks"] == 1
    finally:
        second.close()


def test_file_system_change_rewrites_persisted_projection(tmp_path, schema_db, monkeypatch):
    """A supported event rewrites (not deletes) the persisted projection so
    a restart serves the updated view; unsupported kinds delete it and fall
    back to the full rebuild semantics."""
    import time

    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import FileSystemChanged

    _image(tmp_path / "set" / "one.png")
    service = GalleryService(connection_provider=lambda _root: schema_db)
    monkeypatch.setattr(service, "_incremental_debounce", 0.05)
    try:
        # The persisted database row is the only reliable commit signal here:
        # the builder publishes the memory cache before it writes the row, so
        # a cache hit does not imply the row exists yet. Under parallel-test
        # CPU contention the two moments separate and a row-based assertion
        # must poll (see test_home_projection_persists_to_database_and_survives)
        # — each get_home_cached miss re-arms the background build.
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            service.get_home_cached(tmp_path)
            if schema_db.execute(
                "SELECT 1 FROM gallery_home WHERE id = 1"
            ).fetchone() is not None:
                break
            time.sleep(0.05)
        else:
            pytest.fail("background build never persisted gallery_home within 10.0s")

        applied_before, fallbacks_before = service.incremental_stats
        _image(tmp_path / "set" / "two.png")
        get_event_bus().publish(FileSystemChanged(
            library_root=str(tmp_path), session_token="test", kind="created",
            paths=(str(tmp_path / "set" / "two.png"),),
        ))

        def persisted_reflects_two():
            row = schema_db.execute(
                "SELECT projection FROM gallery_home WHERE id = 1"
            ).fetchone()
            return row is not None and '"artworks": 2' in row[0]

        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and not persisted_reflects_two():
            time.sleep(0.05)
        assert persisted_reflects_two()
        # Verify incremental application succeeded, no fallback.
        applied_after, fallbacks_after = service.incremental_stats
        assert applied_after == applied_before + 1
        assert fallbacks_after == fallbacks_before

        # Unsupported kinds fall back: the persisted row is deleted (the
        # full rebuild is scheduled separately).
        get_event_bus().publish(FileSystemChanged(
            library_root=str(tmp_path), session_token="test", kind="files", paths=(),
        ))
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and schema_db.execute(
            "SELECT 1 FROM gallery_home WHERE id = 1"
        ).fetchone() is not None:
            time.sleep(0.05)
        assert schema_db.execute(
            "SELECT 1 FROM gallery_home WHERE id = 1"
        ).fetchone() is None
        assert service.get_home_cached(tmp_path) is None
    finally:
        service.close()


def test_expired_persisted_projection_is_ignored(tmp_path, schema_db, monkeypatch):
    """A persisted row older than the TTL is not served; the cache misses
    (the route answers building) while a background build repopulates it."""
    import time

    _image(tmp_path / "set" / "one.png")
    schema_db.execute(
        "INSERT OR REPLACE INTO gallery_home (id, saved_at, projection) "
        "VALUES (1, ?, ?)",
        (time.time() - 7200.0, '{"projects": []}'),
    )
    schema_db.commit()
    service = GalleryService(connection_provider=lambda _root: schema_db)
    monkeypatch.setattr(service, "_ensure_home_building", lambda _root_key: None)
    try:
        assert service.get_home_cached(tmp_path) is None
        # The stale row must not be resurrected on the next read either.
        assert service.get_home_cached(tmp_path) is None
    finally:
        service.close()


def test_corrupted_persisted_projection_is_ignored(tmp_path, schema_db, monkeypatch):
    """A non-JSON or non-dict persisted row is treated as absent instead of
    crashing the home route."""
    import time

    _image(tmp_path / "set" / "one.png")
    schema_db.execute(
        "INSERT OR REPLACE INTO gallery_home (id, saved_at, projection) "
        "VALUES (1, ?, ?)",
        (time.time(), "{not valid json"),
    )
    schema_db.commit()
    service = GalleryService(connection_provider=lambda _root: schema_db)
    monkeypatch.setattr(service, "_ensure_home_building", lambda _root_key: None)
    try:
        assert service.get_home_cached(tmp_path) is None
    finally:
        service.close()

    # A non-dict JSON payload is equally ignored.
    schema_db.execute(
        "INSERT OR REPLACE INTO gallery_home (id, saved_at, projection) "
        "VALUES (1, ?, ?)",
        (time.time(), '["a", "list"]'),
    )
    schema_db.commit()
    service = GalleryService(connection_provider=lambda _root: schema_db)
    monkeypatch.setattr(service, "_ensure_home_building", lambda _root_key: None)
    try:
        assert service.get_home_cached(tmp_path) is None
    finally:
        service.close()


def test_legacy_persisted_projection_urls_are_stripped_on_load(tmp_path, schema_db, monkeypatch):
    """A pre-separation persisted row carries URL keys; the restored home is
    served URL-free and re-projected at the route layer instead."""
    import json
    import time

    legacy = {
        "featured": {
            "name": "set", "path": "set", "kind": "project", "parent_path": "",
            "cover_path": "set/cover.png",
            "cover_url": "/api/thumbnails/set/cover.png?size=512",
            "width": 40, "height": 40, "aspect_ratio": 1.0, "modified": 1,
            "size": 1, "size_fmt": "1 B", "file_count": 1, "artwork_count": 1,
            "child_count": 0, "tags": [],
        },
        "collections": [],
        "projects": [
            {
                "name": "set", "path": "set", "kind": "project", "parent_path": "",
                "cover_path": "set/cover.png",
                "cover_url": "/api/thumbnails/set/cover.png?size=512",
                "width": 40, "height": 40, "aspect_ratio": 1.0, "modified": 1,
                "size": 1, "size_fmt": "1 B", "file_count": 1, "artwork_count": 1,
                "child_count": 0, "tags": [],
            },
        ],
        "recent": [
            {
                "name": "cover.png", "path": "set/cover.png", "kind": "artwork",
                "parent_path": "set",
                "thumbnail_url": "/api/thumbnails/set/cover.png?size=512",
                "image_url": "/api/image?path=set%2Fcover.png",
                "width": 40, "height": 40, "aspect_ratio": 1.0, "modified": 1,
                "size": 1, "size_fmt": "1 B", "extension": ".png", "tags": [],
            },
        ],
        "stats": {"collections": 0, "projects": 1, "artworks": 1, "total_size_fmt": "1 B"},
    }
    schema_db.execute(
        "INSERT OR REPLACE INTO gallery_home (id, saved_at, projection) "
        "VALUES (1, ?, ?)",
        (time.time(), json.dumps(legacy, ensure_ascii=False)),
    )
    schema_db.commit()

    service = GalleryService(connection_provider=lambda _root: schema_db)
    monkeypatch.setattr(service, "_ensure_home_building", lambda _root_key: None)
    try:
        home = service.get_home_cached(tmp_path)
        assert home is not None
        restored = home.to_response()

        def collect(values):
            for value in values:
                if isinstance(value, dict):
                    yield from collect(value.values())
                elif isinstance(value, list):
                    yield from collect(value)

        assert not any(
            isinstance(value, str) and value.startswith("/api/")
            for value in collect(restored.values())
        )
        assert "cover_url" not in restored["projects"][0]
        assert "thumbnail_url" not in restored["recent"][0]
        assert "image_url" not in restored["recent"][0]
        assert restored["projects"][0]["cover_path"] == "set/cover.png"
    finally:
        service.close()


def test_home_build_captures_incremental_state(tmp_path, schema_db):
    """Every full home build records the node/refs snapshot with a
    generation watermark equal to the seq counter value captured before the
    walk; the incremental applier consumes it."""
    _image(tmp_path / "set" / "one.png", (40, 40))

    service = GalleryService(connection_provider=lambda _root: schema_db)
    try:
        home = service.get_home(tmp_path)
        assert home is not None
        state = service._home_states[str(tmp_path.resolve())]
        # Watermark semantics: no event has been issued yet, so the
        # snapshot covers seqs up to the (untouched) counter value 0. The
        # counter itself must not have been bumped by the build — it only
        # issues seqs to queued events.
        assert state.generation == 0
        assert service._home_generation == 0
        assert state.node is not None
        assert state.node["artwork_count"] == 1
        assert any(ref.path.endswith("one.png") for ref in state.refs)
    finally:
        service.close()


def test_cover_dimensions_skipped_past_decode_soft_budget(tmp_path, schema_db):
    """Once the walk passes its decode soft budget, covers keep their paths
    but skip the per-image dimension decode so huge libraries still finish
    the build instead of failing the hard time budget."""
    _image(tmp_path / "set" / "cover.jpg", (40, 40))

    service = GalleryService(
        connection_provider=lambda _root: schema_db,
        limits=GalleryTraversalLimits(decode_soft_seconds=0),
    )
    try:
        response = service.get_home(tmp_path).to_response()
        project = response["projects"][0]
        assert project["cover_path"] == "set/cover.jpg"
        assert project["width"] is None
        assert project["height"] is None
        # The recent post-pass (a fixed 24-item list) sits outside the soft
        # budget and still carries decoded dimensions.
        assert response["recent"][0]["width"] == 40
        assert response["recent"][0]["height"] == 40
    finally:
        service.close()


def test_failed_background_build_backs_off_before_retry(tmp_path, schema_db, monkeypatch):
    """A failed background build stamps a backoff: polls inside the backoff
    must not restart the expensive full walk (they re-arm a single retry
    timer instead), and the build resumes once the backoff elapses."""
    import time

    _image(tmp_path / "set" / "one.png")
    service = GalleryService(connection_provider=lambda _root: schema_db)
    monkeypatch.setattr(service, "_build_backoff", 60.0)

    def fail_build(_root_key):
        raise RuntimeError("simulated build failure")

    monkeypatch.setattr(service, "_compute_home", fail_build)
    retry_delays: list[float] = []
    monkeypatch.setattr(
        service, "_schedule_retry",
        lambda _root_key, delay: retry_delays.append(delay),
    )

    root_key = str(tmp_path.resolve())
    try:
        assert service.get_home_cached(tmp_path) is None  # starts the failing build
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and root_key not in service._build_failures:
            time.sleep(0.05)
        assert root_key in service._build_failures

        # A new poll within the backoff must not start another build thread.
        service._ensure_home_building(root_key)
        assert root_key not in service._building
        assert retry_delays and 0 < retry_delays[-1] <= 60.0

        # Once the backoff elapses the build runs again and clears the stamp.
        monkeypatch.setattr(service, "_compute_home", lambda _root_key: None)
        service._build_failures[root_key] = time.monotonic() - 120.0
        service._ensure_home_building(root_key)
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and root_key in service._building:
            time.sleep(0.05)
        assert root_key not in service._building
        assert root_key not in service._build_failures
    finally:
        service.close()


def test_prewarm_wait_hook_runs_on_build_thread_before_walk(tmp_path, schema_db):
    """prewarm_home runs its pre_wait hook on the build thread before the
    walk, so the LAN server can serialize the gallery build behind its
    scanner — concurrent full-library traversals with per-file stats fight
    for disk I/O on Windows and push each other past the time budget."""
    import threading
    import time

    _image(tmp_path / "set" / "one.png")
    service = GalleryService(connection_provider=lambda _root: schema_db)
    root_key = str(tmp_path.resolve())
    hook_called = threading.Event()

    def wait_hook():
        # Runs on the build thread: the root is already marked as building
        # (so polls stay no-ops), and the walk has not started yet.
        assert root_key in service._building
        hook_called.set()

    service.prewarm_home(tmp_path, pre_wait=wait_hook)
    try:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and not hook_called.is_set():
            time.sleep(0.05)
        assert hook_called.is_set()
        # The build then completes and fills the cache.
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and service.get_home_cached(tmp_path) is None:
            time.sleep(0.05)
        assert service.get_home_cached(tmp_path) is not None
    finally:
        service.close()


def test_gallery_projects_follow_project_depth_and_aggregate_inside(tmp_path, schema_db):
    """Directories at the configured project depth are display leaves:
    their whole subtree aggregates into one project node (stats, artwork
    list, cover), and nothing deeper is projected as a node."""
    from AssetsManager.application.project_service import ProjectDepthConfig

    _image(tmp_path / "branch" / "proj" / "textures" / "t.png", (16, 16))
    _image(tmp_path / "branch" / "proj" / "cover.png", (40, 40))
    (tmp_path / "branch" / "proj" / "readme.txt").write_text("notes")
    _image(tmp_path / "branch" / "other" / "x.png", (20, 20))

    service = GalleryService(
        connection_provider=lambda _root: schema_db,
        depth_config=ProjectDepthConfig(global_depth=2),
    )
    try:
        response = service.get_home(tmp_path).to_response()
        # branch (depth 1 < 2) projects as a collection; the two depth-2
        # directories are projects whose inner folders are not projected.
        assert [entry["path"] for entry in response["collections"]] == ["branch"]
        assert [entry["path"] for entry in response["projects"]] == []
        assert response["stats"] == {
            "collections": 1,
            "projects": 2,
            "artworks": 3,
            "total_size_fmt": response["stats"]["total_size_fmt"],
        }
        assert {entry["path"] for entry in response["recent"]} == {
            "branch/proj/cover.png",
            "branch/proj/textures/t.png",
            "branch/other/x.png",
        }

        # The branch lists the projects as its children, one node each.
        branch = service.get_collection(tmp_path, "branch")
        assert branch is not None
        assert {child["path"] for child in branch.children} == {
            "branch/other", "branch/proj",
        }
        proj = next(child for child in branch.children if child["path"] == "branch/proj")
        assert proj["kind"] == "project"
        assert proj["file_count"] == 3  # t.png + cover.png + readme.txt
        assert proj["artwork_count"] == 2
        assert proj["cover_path"] == "branch/proj/cover.png"  # sorted first

        # The project's own page lists every artwork inside it.
        proj_page = service.get_collection(tmp_path, "branch/proj")
        assert proj_page is not None
        assert proj_page.children == []
        assert [entry["path"] for entry in proj_page.entries] == [
            "branch/proj/cover.png", "branch/proj/textures/t.png",
        ]

        # Paths deeper than the project floor are not part of the projection.
        assert service.get_collection(tmp_path, "branch/proj/textures") is None
    finally:
        service.close()


def test_gallery_branch_depth_override_makes_top_level_directories_projects(tmp_path, schema_db):
    """branch_depths can lower a branch's floor so its first-level
    directories are projects (matching the sidebar's per-branch config)."""
    from AssetsManager.application.project_service import ProjectDepthConfig

    _image(tmp_path / "flat" / "leaf" / "inner" / "a.png", (16, 16))

    service = GalleryService(
        connection_provider=lambda _root: schema_db,
        depth_config=ProjectDepthConfig(global_depth=3, branch_depths={"flat": 1}),
    )
    try:
        response = service.get_home(tmp_path).to_response()
        assert [entry["path"] for entry in response["projects"]] == ["flat"]
        flat = service.get_collection(tmp_path, "flat")
        assert flat is not None
        # leaf is inside the flat project and not projected as a node.
        assert flat.children == []
        assert [entry["path"] for entry in flat.entries] == ["flat/leaf/inner/a.png"]
    finally:
        service.close()


def test_file_change_inside_project_updates_incrementally(tmp_path, schema_db, monkeypatch):
    """File events inside a project keep working incrementally: the project
    node is the parent, so stats/covers update without a full rebuild."""
    import time

    from AssetsManager.application.project_service import ProjectDepthConfig
    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import FileSystemChanged

    _image(tmp_path / "branch" / "proj" / "textures" / "one.png", (16, 16))
    service = GalleryService(
        connection_provider=lambda _root: schema_db,
        depth_config=ProjectDepthConfig(global_depth=2),
    )
    monkeypatch.setattr(service, "_incremental_debounce", 0.05)
    try:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and service.get_home_cached(tmp_path) is None:
            time.sleep(0.05)
        before = service.get_home_cached(tmp_path)
        assert before is not None and before.stats["artworks"] == 1

        _image(tmp_path / "branch" / "proj" / "textures" / "two.png", (16, 16))
        get_event_bus().publish(FileSystemChanged(
            library_root=str(tmp_path), session_token="test", kind="created",
            paths=(str(tmp_path / "branch" / "proj" / "textures" / "two.png"),),
        ))
        deadline = time.monotonic() + 10.0
        after = None
        while time.monotonic() < deadline:
            after = service.get_home_cached(tmp_path)
            if after is not None and after.stats["artworks"] == 2:
                break
            time.sleep(0.05)
        assert after is not None and after.stats["artworks"] == 2
    finally:
        service.close()


# ── Bounded close / cancel-event contract ──────────────────────────


def test_close_bounded_by_timeout_keeps_straggler_handle(tmp_path, schema_db, caplog):
    """A worker stuck past the deadline makes close() return False quickly:
    the handle is retained, a warning is logged, and the thread is not
    force-killed (the database gated close is the hard safety boundary)."""
    import threading
    import time

    service = GalleryService(connection_provider=lambda _root: schema_db)
    release = threading.Event()
    worker = threading.Thread(target=release.wait, name="gallery-stuck")
    worker.start()
    with service._build_lock:
        service._worker_threads.add(worker)
    try:
        started = time.monotonic()
        drained = service.close(timeout=0.2)
        elapsed = time.monotonic() - started
        assert drained is False
        assert elapsed < 2.0  # bounded: nowhere near an unbounded join
        assert worker.is_alive()
        with service._build_lock:
            assert worker in service._worker_threads  # handle retained
        assert any(
            "still running" in record.getMessage() for record in caplog.records
        )
    finally:
        release.set()
        worker.join(timeout=5.0)


def test_close_joins_normal_worker_then_is_idempotent(tmp_path, schema_db):
    """close() drains a finishing worker (True) and later calls on the
    already-closed service stay True and harmless."""
    import threading
    import time

    service = GalleryService(connection_provider=lambda _root: schema_db)
    worker = threading.Thread(target=lambda: time.sleep(0.1))
    worker.start()
    with service._build_lock:
        service._worker_threads.add(worker)
    assert service.close(timeout=5.0) is True
    assert not worker.is_alive()
    # A real worker removes its own handle on exit; an injected one stays in
    # the set, but a second close (and a default-deadline close) drain
    # cleanly instead of raising.
    assert service.close(timeout=5.0) is True
    assert service.close() is True


def test_concurrent_double_close_is_safe(tmp_path, schema_db):
    """Two threads closing the same service concurrently both drain the
    worker without raising or deadlocking (LAN _shutdown + runtime teardown
    may overlap)."""
    import threading
    import time

    service = GalleryService(connection_provider=lambda _root: schema_db)
    worker = threading.Thread(target=lambda: time.sleep(0.2))
    worker.start()
    with service._build_lock:
        service._worker_threads.add(worker)
    results: list[bool] = []
    errors: list[Exception] = []

    def do_close() -> None:
        try:
            results.append(service.close(timeout=5.0))
        except Exception as exc:
            errors.append(exc)

    first = threading.Thread(target=do_close)
    second = threading.Thread(target=do_close)
    first.start()
    second.start()
    first.join(timeout=10.0)
    second.join(timeout=10.0)
    assert errors == []
    assert results == [True, True]
    assert not worker.is_alive()


def test_prewarm_pre_wait_observes_cancel_event_and_skips_compute(tmp_path, schema_db, monkeypatch):
    """close() sets the read-only cancel event: a pre_wait hook waiting on
    it returns promptly and the worker never enters the compute path."""
    import threading

    service = GalleryService(connection_provider=lambda _root: schema_db)
    entered = threading.Event()
    computed: list[str] = []
    monkeypatch.setattr(service, "_compute_home", lambda root_key: computed.append(root_key))

    def pre_wait() -> None:
        entered.set()
        service.cancel_event.wait(timeout=10.0)

    service.prewarm_home(tmp_path, pre_wait=pre_wait)
    try:
        assert entered.wait(timeout=5.0)
        # close() returns True only after joining the worker, and the worker
        # returns right after its pre_wait observes the cancel event.
        assert service.close(timeout=2.0) is True
        assert computed == []
    finally:
        service.close()


def test_close_skips_self_and_unstarted_workers(tmp_path, schema_db):
    """close() never joins the calling thread (self-join deadlocks) and
    never joins a registered-but-unstarted thread (Thread.join raises
    RuntimeError there); both count as already safe."""
    import threading

    service = GalleryService(connection_provider=lambda _root: schema_db)
    current = threading.current_thread()
    unstarted = threading.Thread(target=lambda: None, name="never-started")
    with service._build_lock:
        service._worker_threads.add(current)
        service._worker_threads.add(unstarted)
    assert service.close(timeout=1.0) is True
    assert unstarted.ident is None  # never started, never joined


def test_incremental_delete_updates_artwork_count(tmp_path, schema_db, monkeypatch):
    """A delete event removes the artwork from the cached home incrementally
    rather than falling back to a full rebuild."""
    import os
    import time

    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import FileSystemChanged

    one = tmp_path / "set" / "one.png"
    two = tmp_path / "set" / "two.png"
    _image(one)
    time.sleep(0.01)  # Ensure different mtimes
    _image(two)
    # Make 'two.png' newer so deleting 'one.png' doesn't carry the max mtime
    now = time.time()
    os.utime(one, (now - 10, now - 10))
    os.utime(two, (now, now))
    service = GalleryService(connection_provider=lambda _root: schema_db)
    monkeypatch.setattr(service, "_incremental_debounce", 0.05)
    try:
        # Wait for cache to be populated
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and service.get_home_cached(tmp_path) is None:
            time.sleep(0.05)
        before = service.get_home_cached(tmp_path)
        assert before is not None and before.stats["artworks"] == 2

        # Wait for background build to complete (required for incremental to work)
        root_key = str(tmp_path.resolve())
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            with service._build_lock:
                building = root_key in service._building
            with service._home_cache_lock:
                has_state = root_key in service._home_states
            # Build must be complete (not in _building) AND state must be populated
            if not building and has_state:
                break
            time.sleep(0.05)
        assert root_key not in service._building, "Background build did not complete"
        assert root_key in service._home_states, "Background build did not populate state"

        applied_before, fallbacks_before = service.incremental_stats
        one.unlink()
        get_event_bus().publish(FileSystemChanged(
            library_root=str(tmp_path), session_token="test", kind="deleted",
            paths=(str(one),),
        ))
        deadline = time.monotonic() + 10.0
        after = None
        while time.monotonic() < deadline:
            after = service.get_home_cached(tmp_path)
            applied_after, fallbacks_after = service.incremental_stats
            if after is not None and after.stats["artworks"] == 1 and applied_after > applied_before:
                break
            time.sleep(0.05)
        assert after is not None and after.stats["artworks"] == 1
        # Verify incremental: exactly 1 applied, 0 fallbacks.
        applied_after, fallbacks_after = service.incremental_stats
        assert applied_after == applied_before + 1
        assert fallbacks_after == fallbacks_before
    finally:
        service.close()


def test_incremental_move_preserves_artwork_count(tmp_path, schema_db, monkeypatch):
    """A move event within the same directory updates the cached home without
    changing artwork count or triggering a fallback."""
    import os
    import time

    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import FileSystemChanged

    old_path = tmp_path / "set" / "one.png"
    new_path = tmp_path / "set" / "renamed.png"
    other = tmp_path / "set" / "other.png"
    _image(old_path)
    _image(other)  # Need at least 2 files for "set" to be a collection node
    # Make 'other.png' newer so moving 'one.png' doesn't carry the max mtime
    now = time.time()
    os.utime(old_path, (now - 10, now - 10))
    os.utime(other, (now, now))
    service = GalleryService(connection_provider=lambda _root: schema_db)
    monkeypatch.setattr(service, "_incremental_debounce", 0.05)
    try:
        # Wait for cache to be populated
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and service.get_home_cached(tmp_path) is None:
            time.sleep(0.05)
        before = service.get_home_cached(tmp_path)
        assert before is not None and before.stats["artworks"] == 2

        # Wait for background build to complete (required for incremental to work)
        root_key = str(tmp_path.resolve())
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            with service._build_lock:
                building = root_key in service._building
            with service._home_cache_lock:
                has_state = root_key in service._home_states
            # Build must be complete (not in _building) AND state must be populated
            if not building and has_state:
                break
            time.sleep(0.05)
        assert root_key not in service._building, "Background build did not complete"
        assert root_key in service._home_states, "Background build did not populate state"

        applied_before, fallbacks_before = service.incremental_stats
        old_path.rename(new_path)
        get_event_bus().publish(FileSystemChanged(
            library_root=str(tmp_path), session_token="test", kind="moved",
            paths=(str(new_path),), old_paths=(str(old_path),),
        ))
        # Wait for incremental apply (debounce + processing).
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            applied_after, _ = service.incremental_stats
            if applied_after > applied_before:
                break
            time.sleep(0.05)
        after = service.get_home_cached(tmp_path)
        assert after is not None and after.stats["artworks"] == 2
        # Verify incremental: exactly 1 applied, 0 fallbacks.
        applied_after, fallbacks_after = service.incremental_stats
        assert applied_after == applied_before + 1
        assert fallbacks_after == fallbacks_before
    finally:
        service.close()
