from __future__ import annotations

from pathlib import Path

import pytest

from AssetsManager.application.favorite_service import FavoriteService
from AssetsManager.domain.errors import MissingPathError, PathEscapeError, ValidationError


def _service(schema_db) -> FavoriteService:
    return FavoriteService(connection_provider=lambda _root: schema_db)


def test_favorite_service_scopes_owners_and_returns_relative_paths(tmp_path, schema_db):
    collection = tmp_path / "collection"
    artwork = collection / "art.png"
    collection.mkdir()
    artwork.write_bytes(b"image")
    service = _service(schema_db)

    assert service.add(tmp_path, "user:1", "collection") == ("collection", True)
    assert service.add(tmp_path, "user:1", "collection") == ("collection", False)
    assert service.add(tmp_path, "user:1", artwork) == (
        "collection/art.png",
        True,
    )
    assert service.add(tmp_path, "user:2", "collection") == ("collection", True)

    assert set(service.list_paths(tmp_path, "user:1")) == {
        "collection",
        "collection/art.png",
    }
    assert service.list_paths(tmp_path, "user:2") == ["collection"]

    assert service.remove(tmp_path, "user:1", "collection") == ("collection", True)
    assert service.remove(tmp_path, "user:1", "collection") == ("collection", False)
    assert service.list_paths(tmp_path, "user:2") == ["collection"]


def test_favorite_service_accepts_directories_and_images_only(tmp_path, schema_db):
    directory = tmp_path / "folder"
    image = tmp_path / "preview.JPEG"
    text = tmp_path / "notes.txt"
    directory.mkdir()
    image.write_bytes(b"image")
    text.write_text("notes", encoding="utf-8")
    service = _service(schema_db)

    assert service.add(tmp_path, "principal:guest", directory)[0] == "folder"
    assert service.add(tmp_path, "principal:guest", image)[0] == "preview.JPEG"
    with pytest.raises(ValidationError, match="directory or image"):
        service.add(tmp_path, "principal:guest", text)


def test_favorite_service_rejects_root_missing_escape_and_invalid_owner(tmp_path, schema_db):
    service = _service(schema_db)

    with pytest.raises(ValidationError, match="root cannot be favorited"):
        service.add(tmp_path, "user:1", tmp_path)
    with pytest.raises(MissingPathError):
        service.add(tmp_path, "user:1", "missing")
    with pytest.raises(PathEscapeError):
        service.add(tmp_path, "user:1", Path("..") / "outside")
    with pytest.raises(ValidationError, match="must not be empty"):
        service.list_paths(tmp_path, "   ")


def test_favorite_service_hides_stale_rows_but_allows_removal(tmp_path, schema_db):
    artwork = tmp_path / "stale.png"
    artwork.write_bytes(b"image")
    service = _service(schema_db)

    assert service.add(tmp_path, "user:1", artwork) == ("stale.png", True)
    artwork.unlink()

    assert service.list_paths(tmp_path, "user:1") == []
    assert service.remove(tmp_path, "user:1", "stale.png") == ("stale.png", True)
    assert service.remove(tmp_path, "user:1", "stale.png") == ("stale.png", False)


def test_bound_favorite_service_publishes_session_scoped_changes(tmp_path):
    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import FavoritesChanged

    library = tmp_path / "library"
    target = library / "collection"
    target.mkdir(parents=True)
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    runtime = bootstrap.runtime_for(session)
    service = runtime.services.lan_services.favorite_service
    assert service is not None
    observed: list[FavoritesChanged] = []
    subscription = get_event_bus().subscribe(FavoritesChanged, observed.append)
    try:
        assert service.add(library, "user:7", target) == ("collection", True)
        assert service.add(library, "user:7", target) == ("collection", False)
        assert service.remove(library, "user:7", target) == ("collection", True)

        assert [(event.owner_key, event.paths) for event in observed] == [
            ("user:7", (str(target.resolve()),)),
            ("user:7", (str(target.resolve()),)),
        ]
        assert all(event.library_root == session.root_str for event in observed)
        assert all(event.session_token == session.event_token for event in observed)
    finally:
        subscription.close()
        runtime.close()
        bootstrap.library_service.close()
