from __future__ import annotations

import os
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
    assert response["collections"][0]["cover_url"] == "/api/thumbnails/collection/cover.jpg?size=512"


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


def test_gallery_image_url_points_to_uri_encoded_original_preview(tmp_path, schema_db):
    _image(tmp_path / "套件" / "hero image.png")

    service = GalleryService(connection_provider=lambda _root: schema_db)
    response = service.get_collection(tmp_path, "套件")

    assert response is not None
    entry = response.entries[0]
    assert entry["thumbnail_url"] == "/api/thumbnails/%E5%A5%97%E4%BB%B6/hero%20image.png?size=512"
    assert entry["image_url"] == (
        "/api/image?path=%E5%A5%97%E4%BB%B6%2Fhero%20image.png"
    )


def test_gallery_skips_external_symlink_and_rejects_symlink_path(tmp_path, schema_db):
    outside = tmp_path.parent / "gallery-outside"
    outside.mkdir()
    _image(outside / "secret.png")
    link = tmp_path / "external-link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")

    service = GalleryService(connection_provider=lambda _root: schema_db)
    response = service.get_home(tmp_path).to_response()
    assert all(entry["path"] != "external-link" for entry in response["collections"])
    with pytest.raises(MissingPathError):
        service.get_collection(tmp_path, "external-link")

    with pytest.raises(PathEscapeError, match="escapes root"):
        service.resolve(tmp_path, str(outside / "secret.png"))


def test_gallery_skips_windows_junction_or_reparse_directory(tmp_path, schema_db):
    if not hasattr(Path, "is_junction") and os.name != "nt":
        pytest.skip("Windows junction/reparse points are unavailable on this platform")
    outside = tmp_path.parent / "gallery-junction-outside"
    outside.mkdir()
    _image(outside / "secret.png")
    junction = tmp_path / "junction"
    if os.name == "nt":
        import subprocess

        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            pytest.skip(f"junction creation unavailable: {result.stderr or result.stdout}")
    else:
        pytest.skip("Windows junction/reparse points are unavailable on this platform")

    service = GalleryService(connection_provider=lambda _root: schema_db)
    response = service.get_home(tmp_path).to_response()
    assert all(entry["path"] != "junction" for entry in response["collections"])
    with pytest.raises(MissingPathError):
        service.get_collection(tmp_path, "junction")


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


def test_home_cache_invalidated_on_file_system_changes(tmp_path, schema_db):
    """A FileSystemChanged event clears the cached projection so the next
    read triggers a background rebuild."""
    import time

    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import FileSystemChanged

    _image(tmp_path / "set" / "one.png")
    service = GalleryService(connection_provider=lambda _root: schema_db)
    try:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and service.get_home_cached(tmp_path) is None:
            time.sleep(0.05)
        assert service.get_home_cached(tmp_path) is not None

        get_event_bus().publish(FileSystemChanged(
            library_root=str(tmp_path), session_token="test", kind="files", paths=(),
        ))
        # Cache cleared synchronously by the event handler.
        assert service.get_home_cached(tmp_path) is None
    finally:
        service.close()


def test_home_projection_persists_to_database_and_survives_restart(tmp_path, schema_db):
    """A built projection is written to the library database; a fresh service
    instance (simulating an app restart) loads it instead of rebuilding."""
    import time

    _image(tmp_path / "collection" / "art.png", (40, 40))

    first = GalleryService(connection_provider=lambda _root: schema_db)
    try:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and first.get_home_cached(tmp_path) is None:
            time.sleep(0.05)
        assert first.get_home_cached(tmp_path) is not None
        row = schema_db.execute(
            "SELECT saved_at, projection FROM gallery_home WHERE id = 1"
        ).fetchone()
        assert row is not None and row[1]
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


def test_file_system_change_deletes_persisted_projection(tmp_path, schema_db):
    """The persisted gallery_home row is removed on library changes so a
    restart cannot resurrect the pre-change view."""
    import time

    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import FileSystemChanged

    _image(tmp_path / "set" / "one.png")
    service = GalleryService(connection_provider=lambda _root: schema_db)
    try:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and service.get_home_cached(tmp_path) is None:
            time.sleep(0.05)
        assert schema_db.execute(
            "SELECT 1 FROM gallery_home WHERE id = 1"
        ).fetchone() is not None

        get_event_bus().publish(FileSystemChanged(
            library_root=str(tmp_path), session_token="test", kind="files", paths=(),
        ))
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


def test_home_build_captures_incremental_state(tmp_path, schema_db):
    """Every full home build records the node/refs snapshot with a fresh
    generation; the incremental applier (a later phase) consumes it."""
    _image(tmp_path / "set" / "one.png", (40, 40))

    service = GalleryService(connection_provider=lambda _root: schema_db)
    try:
        home = service.get_home(tmp_path)
        assert home is not None
        state = service._home_states[str(tmp_path.resolve())]
        assert state.generation > 0
        assert state.node is not None
        assert state.node["artwork_count"] == 1
        assert any(ref.path.endswith("one.png") for ref in state.refs)
    finally:
        service.close()
