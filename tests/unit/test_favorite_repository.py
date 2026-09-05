from __future__ import annotations

import pytest

from AssetsManager.repositories.favorite_repository import FavoriteRepository


def test_favorite_repository_scopes_owners_and_is_idempotent(tmp_path, schema_db):
    repo = FavoriteRepository(schema_db)
    target = str((tmp_path / "collection").resolve())

    assert repo.add("user:1", target) is True
    assert repo.add("user:1", target) is False
    assert repo.add("user:2", target) is True

    assert repo.contains("user:1", target) is True
    assert repo.contains("user:2", target) is True
    assert repo.list_paths("user:1") == [target]
    assert repo.list_paths("user:2") == [target]

    assert repo.remove("user:1", target) is True
    assert repo.remove("user:1", target) is False
    assert repo.contains("user:1", target) is False
    assert repo.contains("user:2", target) is True


def test_favorite_repository_enforces_limit_per_owner(tmp_path, schema_db):
    repo = FavoriteRepository(schema_db)
    first = str((tmp_path / "first").resolve())
    second = str((tmp_path / "second").resolve())

    assert repo.add("user:1", first, max_items=1) is True
    try:
        repo.add("user:1", second, max_items=1)
    except OverflowError as exc:
        assert str(exc) == "favorite limit reached"
    else:
        raise AssertionError("expected the per-owner favorite limit")

    assert repo.add("user:2", second, max_items=1) is True


def test_favorite_repository_limit_boundaries(tmp_path, schema_db):
    repo = FavoriteRepository(schema_db)
    target = str((tmp_path / "target").resolve())

    # A zero limit never admits an insert (count < 0 is never true) and
    # keeps the OverflowError contract instead of a silent no-op.
    with pytest.raises(OverflowError):
        repo.add("user:1", target, max_items=0)
    assert repo.contains("user:1", target) is False

    # Exactly at the limit: the last permitted insert succeeds, the next
    # identical one is a duplicate, and a new one trips the limit.
    assert repo.add("user:1", target, max_items=1) is True
    assert repo.add("user:1", target, max_items=1) is False
    with pytest.raises(OverflowError):
        repo.add("user:1", str((tmp_path / "other").resolve()), max_items=1)
    assert repo.list_paths("user:1") == [target]


def test_favorite_repository_delete_path_is_boundary_safe(tmp_path, schema_db):
    repo = FavoriteRepository(schema_db)
    target = str((tmp_path / "set%_one").resolve())
    child = str((tmp_path / "set%_one" / "child.png").resolve())
    sibling = str((tmp_path / "set%_one-extra").resolve())

    for owner in ("user:1", "user:2"):
        assert repo.add(owner, target) is True
        assert repo.add(owner, child) is True
        assert repo.add(owner, sibling) is True

    assert repo.delete_path(target) == 4
    for owner in ("user:1", "user:2"):
        assert repo.list_paths(owner) == [sibling]


def test_favorite_repository_migrates_subtrees_across_owners(tmp_path, schema_db):
    repo = FavoriteRepository(schema_db)
    old = str((tmp_path / "old").resolve())
    old_child = str((tmp_path / "old" / "nested" / "art.png").resolve())
    new = str((tmp_path / "new").resolve())
    new_child = str((tmp_path / "new" / "nested" / "art.png").resolve())
    unrelated = str((tmp_path / "old-sibling").resolve())

    assert repo.add("user:1", old) is True
    assert repo.add("user:1", old_child) is True
    assert repo.add("user:1", new) is True
    assert repo.add("user:1", unrelated) is True
    assert repo.add("user:2", old_child) is True

    assert repo.migrate_path(old, new) == 3
    assert set(repo.list_paths("user:1")) == {new, new_child, unrelated}
    assert repo.list_paths("user:2") == [new_child]
    assert repo.contains("user:1", old) is False
    assert repo.contains("user:1", old_child) is False


def test_favorite_limit_constants_stay_in_sync():
    """D11: the repository ceiling mirrors the service cap by value.

    Importing across the layer boundary was rejected in favor_repository,
    so this equality test is the mechanical guard the comment asked for:
    if either constant drifts, this fails instead of silently truncating
    favorite lists below the per-owner cap.
    """
    from AssetsManager.application.favorite_service import (
        MAX_FAVORITES_PER_OWNER,
    )

    assert FavoriteRepository.LIMIT_CEILING == MAX_FAVORITES_PER_OWNER
