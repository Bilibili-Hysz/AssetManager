from __future__ import annotations

from AssetsManager.application.bootstrap import ApplicationBootstrap
from AssetsManager.repositories.favorite_repository import FavoriteRepository


def _runtime(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    runtime = bootstrap.runtime_for(session)
    return bootstrap, session, runtime, library


def test_move_migrates_favorites_for_all_owners_and_descendants(tmp_path):
    bootstrap, session, runtime, library = _runtime(tmp_path)
    source = library / "source"
    artwork = source / "nested" / "art.png"
    artwork.parent.mkdir(parents=True)
    artwork.write_bytes(b"image")
    destination = library / "renamed"
    favorites = runtime.services.lan_services.favorite_service
    assert favorites is not None
    try:
        favorites.add(library, "user:1", source)
        favorites.add(library, "user:1", artwork)
        favorites.add(library, "user:2", artwork)

        runtime.services.file_operation_service.move(source, destination)

        assert set(favorites.list_paths(library, "user:1")) == {
            "renamed",
            "renamed/nested/art.png",
        }
        assert favorites.list_paths(library, "user:2") == [
            "renamed/nested/art.png"
        ]
    finally:
        runtime.close()
        bootstrap.library_service.close()


def test_delete_clears_favorites_for_target_and_descendants(tmp_path):
    bootstrap, session, runtime, library = _runtime(tmp_path)
    target = library / "target"
    artwork = target / "nested" / "art.png"
    sibling = library / "target-sibling"
    artwork.parent.mkdir(parents=True)
    artwork.write_bytes(b"image")
    sibling.mkdir()
    favorites = runtime.services.lan_services.favorite_service
    assert favorites is not None
    conn = session.connection_for(library)
    repo = FavoriteRepository(conn)
    try:
        for owner in ("user:1", "user:2"):
            favorites.add(library, owner, target)
            favorites.add(library, owner, artwork)
            favorites.add(library, owner, sibling)

        result = runtime.services.file_operation_service.delete_permanent([target])

        assert result.ok is True
        assert result.changed_paths == (target,)
        for owner in ("user:1", "user:2"):
            assert favorites.list_paths(library, owner) == ["target-sibling"]
            assert repo.contains(owner, str(target.resolve())) is False
            assert repo.contains(owner, str(artwork.resolve())) is False
            assert repo.contains(owner, str(sibling.resolve())) is True
    finally:
        runtime.close()
        bootstrap.library_service.close()
