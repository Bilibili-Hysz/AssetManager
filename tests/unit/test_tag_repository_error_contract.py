from __future__ import annotations

import sqlite3

import pytest

from AssetsManager.core import database
from AssetsManager.core.db_migrations import migrate
from AssetsManager.repositories.tag_repository import TagRepository


def _repository_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(database._SCHEMA)
    migrate(conn)
    return conn


def test_duplicate_and_missing_tag_operations_keep_idempotent_semantics() -> None:
    conn = _repository_connection()
    try:
        repo = TagRepository(conn)

        assert repo.add_tag("/asset.png", "hero") is True
        assert repo.add_tag("/asset.png", "hero") is True
        assert repo.remove_tag("/asset.png", "missing") is True
        assert repo.remove_tag("/asset.png", "hero") is True
        assert repo.get_tags("/asset.png") == []
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("method_name", "args"),
    [
        ("get_tags", ("/asset.png",)),
        ("list_tags_with_counts", ()),
        ("get_tags_for_files", (["/asset.png"],)),
        ("list_file_tags", ()),
        ("get_all_tags", ()),
        ("get_files_by_tag", ("hero",)),
        ("get_files_by_tag_case_insensitive", ("hero",)),
        ("get_tags_for_tree", ("/",)),
        ("get_tag_metadata", ("hero",)),
        ("get_tags_with_metadata", ()),
    ],
)
def test_closed_connection_read_operations_propagate_programming_error(
    method_name: str, args: tuple[object, ...]
) -> None:
    conn = _repository_connection()
    repo = TagRepository(conn)
    conn.close()

    with pytest.raises(sqlite3.ProgrammingError):
        getattr(repo, method_name)(*args)


@pytest.mark.parametrize(
    ("method_name", "args"),
    [
        ("add_tag", ("/asset.png", "hero")),
        ("remove_tag", ("/asset.png", "hero")),
        ("remove_file", ("/asset.png",)),
        ("delete_path", ("/asset.png",)),
        ("rename_tag", ("hero", "villain")),
        ("delete_tag", ("hero",)),
        ("migrate_path", ("/old", "/new")),
        ("set_tag_metadata", ("hero",)),
        ("delete_tag_metadata", ("hero",)),
    ],
)
def test_closed_connection_write_operations_do_not_return_business_failure(
    method_name: str, args: tuple[object, ...]
) -> None:
    conn = _repository_connection()
    repo = TagRepository(conn)
    conn.close()

    with pytest.raises((sqlite3.ProgrammingError, RuntimeError)):
        getattr(repo, method_name)(*args)


def test_missing_schema_propagates_operational_error_for_tag_and_metadata_operations() -> None:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    try:
        repo = TagRepository(conn)
        operations = [
            (repo.get_tags, ("/asset.png",)),
            (repo.list_tags_with_counts, ()),
            (repo.get_tags_for_files, (["/asset.png"],)),
            (repo.get_all_tags, ()),
            (repo.get_tag_metadata, ("hero",)),
            (repo.get_tags_with_metadata, ()),
            (repo.add_tag, ("/asset.png", "hero")),
            (repo.remove_tag, ("/asset.png", "hero")),
            (repo.set_tag_metadata, ("hero",)),
        ]
        for operation, args in operations:
            with pytest.raises(sqlite3.OperationalError):
                operation(*args)
    finally:
        conn.close()


def test_malformed_tag_schema_propagates_operational_error() -> None:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    try:
        conn.execute("CREATE TABLE file_tags (file_path TEXT, wrong_column TEXT)")
        repo = TagRepository(conn)

        with pytest.raises(sqlite3.OperationalError):
            repo.get_tags("/asset.png")
        with pytest.raises(sqlite3.OperationalError):
            repo.add_tag("/asset.png", "hero")
        with pytest.raises(sqlite3.OperationalError):
            repo.list_tags_with_counts()
    finally:
        conn.close()


def test_rename_tag_migrates_tag_metadata() -> None:
    conn = _repository_connection()
    try:
        repo = TagRepository(conn)
        repo.add_tag("/asset.png", "hero")
        repo.set_tag_metadata("hero", color="red", icon="star", category="work")

        assert repo.rename_tag("hero", "villain") == 1
        assert repo.get_tags("/asset.png") == ["villain"]
        assert repo.get_tag_metadata("villain") == {
            "color": "red", "icon": "star", "category": "work",
        }
        assert repo.get_tag_metadata("hero") is None
    finally:
        conn.close()


def test_rename_tag_keeps_existing_target_metadata() -> None:
    conn = _repository_connection()
    try:
        repo = TagRepository(conn)
        repo.set_tag_metadata("hero", color="blue")
        repo.set_tag_metadata("villain", color="red")

        assert repo.rename_tag("hero", "villain") == 0
        # The target row wins; the old row is dropped, not duplicated.
        assert repo.get_tag_metadata("villain") == {
            "color": "red", "icon": "", "category": "",
        }
        assert repo.get_tag_metadata("hero") is None
    finally:
        conn.close()


def test_rename_tag_onto_existing_file_tag_raises_business_error() -> None:
    from AssetsManager.domain.errors import DuplicateError

    conn = _repository_connection()
    try:
        repo = TagRepository(conn)
        repo.add_tag("/asset.png", "hero")
        repo.add_tag("/asset.png", "villain")

        with pytest.raises(DuplicateError):
            repo.rename_tag("hero", "villain")
        # No partial update: both tags remain on the file.
        assert repo.get_tags("/asset.png") == ["hero", "villain"]
    finally:
        conn.close()


def test_rename_tag_same_name_is_a_no_op() -> None:
    conn = _repository_connection()
    try:
        repo = TagRepository(conn)
        repo.add_tag("/asset.png", "hero")
        repo.set_tag_metadata("hero", color="red")

        assert repo.rename_tag("hero", "hero") == 0
        assert repo.get_tags("/asset.png") == ["hero"]
        assert repo.get_tag_metadata("hero") == {
            "color": "red", "icon": "", "category": "",
        }
    finally:
        conn.close()
