"""H2-a2: thumbnail disk-cache capacity cap (access-ordered eviction).

Exercises ``ThumbnailService.enforce_cache_capacity`` against a real bootstrapped
library — the same shape as the existing ``evict_cache`` integration tests, on
top of the real ``thumbnail_cache`` schema.
"""
import pytest

from AssetsManager.application.bootstrap import ApplicationBootstrap


@pytest.fixture
def scoped(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    service = bootstrap.runtime_for(session).services.thumbnail_service
    try:
        yield service, session, library, thumbs
    finally:
        bootstrap.library_service.close()


def _seed_cache(scoped, sizes=(100, 100, 100)):
    """Insert three artifacts with staggered last_access (old, mid, new)."""
    service, session, library, thumbs = scoped
    for index, key in enumerate(("old", "mid", "new")):
        size = sizes[index % len(sizes)]
        service.upsert_cache_metadata(
            library, key, library / f"{key}.png", 1.0, 1, 1, size)
        (thumbs / f"{key}.webp").write_bytes(b"x" * size)
    session.connection_for(library).execute(
        "UPDATE thumbnail_cache SET last_access=CASE cache_key "
        "WHEN 'old' THEN 1 WHEN 'mid' THEN 2 ELSE 3 END"
    )
    session.connection_for(library).commit()


def test_enforce_capacity_evicts_to_cap_preserving_recent(scoped):
    service, _session, library, thumbs = scoped
    _seed_cache(scoped)

    # 300 tracked bytes vs a 250-byte cap: evict exactly the oldest-access
    # artifact (300 -> 200) and stop; the recently viewed artifacts remain.
    evicted, reclaimed = service.enforce_cache_capacity(
        library, thumbs, max_bytes=250)

    assert (evicted, reclaimed) == (1, 100)
    assert not (thumbs / "old.webp").exists()
    assert (thumbs / "mid.webp").exists()
    assert (thumbs / "new.webp").exists()
    assert service.get_cache_metadata(library, "old") is None
    assert service.get_cache_metadata(library, "mid") is not None
    assert service.get_cache_metadata(library, "new") is not None


def test_enforce_capacity_noop_under_cap(scoped):
    service, _session, library, thumbs = scoped
    _seed_cache(scoped)

    assert service.enforce_cache_capacity(
        library, thumbs, max_bytes=10 ** 9) == (0, 0)
    for key in ("old", "mid", "new"):
        assert (thumbs / f"{key}.webp").exists()
        assert service.get_cache_metadata(library, key) is not None


def test_enforce_capacity_rejects_negative_cap(scoped):
    service, _session, library, thumbs = scoped
    with pytest.raises(ValueError):
        service.enforce_cache_capacity(library, thumbs, max_bytes=-1)
