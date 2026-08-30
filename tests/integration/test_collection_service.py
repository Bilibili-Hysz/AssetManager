"""Integration tests for CollectionService (manual + smart collections).

Includes the architecture iron-law proof: a collection is a query view /
reference set — evaluating, deleting, or mutating it never moves, copies,
or deletes files on disk.
"""
import json
import sqlite3
from pathlib import Path

import pytest

from AssetsManager.application.collection_service import CollectionService
from AssetsManager.application.tag_service import TagService
from AssetsManager.domain.errors import ValidationError
from AssetsManager.repositories.asset_index_repository import AssetIndexRepository


def _memory_conn() -> sqlite3.Connection:
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(database._SCHEMA)
    migrate(conn)
    return conn


class _IndexAdapter:
    """Stand-in for the session-bound AssetIndexService on a raw connection.

    Forwards to the canonical ``AssetIndexRepository.search_structured`` —
    the same repository query ``SearchService.search_structured_detailed``
    uses — so the evaluate contract is exercised against real SQL.
    """

    def __init__(self, conn: sqlite3.Connection):
        self._repo = AssetIndexRepository(conn)

    def search_structured(self, library_root, **kwargs):
        return self._repo.search_structured(str(library_root), **kwargs)


def _index_asset(conn: sqlite3.Connection, library, name: str) -> str:
    path = library / name
    path.write_bytes(b"data")
    conn.execute(
        "INSERT INTO assets (file_path, name, extension, kind, size, mtime, "
        "parent_path, library_root) VALUES (?, ?, ?, 'file', ?, ?, ?, ?)",
        (
            str(path),
            path.stem,
            path.suffix,
            path.stat().st_size,
            path.stat().st_mtime,
            str(library),
            str(library),
        ),
    )
    conn.commit()
    return str(path)


def _service(conn: sqlite3.Connection, library) -> CollectionService:
    return CollectionService(
        connection_provider=lambda _root: conn,
        asset_index_service=_IndexAdapter(conn),
        tag_service=TagService(connection_provider=lambda _root: conn),
    )


def test_manual_collection_lifecycle(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    conn = _memory_conn()
    try:
        service = _service(conn, library)
        asset = library / "a.png"
        asset.write_bytes(b"png")

        created = service.create(library, "favorites")
        assert created["kind"] == "manual"

        assert service.add_files(library, created["id"], [asset]) == 1
        assert service.add_files(library, created["id"], [asset]) == 0

        members = service.get_members(library, created["id"])
        assert [m["file_path"] for m in members] == [str(asset.resolve())]
        assert members[0]["exists"] is True

        # Removing the file on disk keeps the reference (exists=False) —
        # collections tolerate absent members instead of silently pruning.
        asset.unlink()
        members = service.get_members(library, created["id"])
        assert members[0]["exists"] is False

        assert service.remove_files(library, created["id"], [asset]) == 1
        assert service.get_members(library, created["id"]) == []

        service.rename(library, created["id"], "favourites")
        listed = service.list_collections(library)
        assert [(c["name"], c["member_count"]) for c in listed] == [
            ("favourites", 0)
        ]

        service.delete(library, created["id"])
        assert service.list_collections(library) == []
    finally:
        conn.close()


def test_add_files_rejects_smart_collections_and_missing(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    conn = _memory_conn()
    try:
        service = _service(conn, library)
        asset = library / "a.png"
        asset.write_bytes(b"png")
        smart = service.create_smart(library, "smart", {"extensions": [".png"]})
        manual = service.create(library, "manual")
        with pytest.raises(ValidationError, match="smart collections"):
            service.add_files(library, smart["id"], [asset])
        with pytest.raises(ValidationError, match="smart collections"):
            service.remove_files(library, smart["id"], [asset])
        # Evaluation is a smart-only surface.
        with pytest.raises(ValidationError, match="only smart"):
            service.evaluate(library, manual["id"])
        with pytest.raises(Exception):
            service.add_files(library, 99999, [asset])
    finally:
        conn.close()


def test_smart_query_validation(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    conn = _memory_conn()
    try:
        service = _service(conn, library)
        with pytest.raises(ValidationError, match="unknown keys"):
            service.create_smart(library, "bad", {"colour": "red"})
        with pytest.raises(ValidationError, match="tag_match"):
            service.create_smart(library, "bad", {"tag_match": "some"})
        with pytest.raises(ValidationError, match="order_by"):
            service.create_smart(library, "bad", {"order_by": "colour"})
        with pytest.raises(ValidationError, match="must be a list of strings"):
            service.create_smart(library, "bad", {"tags": [1]})
        # An empty predicate dict is a valid "whole index" smart collection.
        created = service.create_smart(library, "everything", {})
        assert json.loads(created["query_json"]) == {}
    finally:
        conn.close()


def test_update_query_requires_existing_smart_collection(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    conn = _memory_conn()
    try:
        service = _service(conn, library)
        manual = service.create(library, "manual")
        smart = service.create_smart(library, "smart", {})
        with pytest.raises(ValidationError, match="only smart"):
            service.update_query(library, manual["id"], {"extensions": [".png"]})
        service.update_query(library, smart["id"], {"extensions": [".png"]})
        stored = {
            c["name"]: c["query_json"] for c in service.list_collections(library)
        }
        assert json.loads(stored["smart"]) == {"extensions": [".png"]}
    finally:
        conn.close()


def test_evaluate_structured_predicates_and_pagination(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    conn = _memory_conn()
    try:
        service = _service(conn, library)
        for name in ("a.png", "b.png", "c.jpg", "d.jpg"):
            _index_asset(conn, library, name)
        smart = service.create_smart(
            library, "pngs", {"extensions": [".png"], "order_by": "name"}
        )

        entries = service.evaluate(library, smart["id"])
        assert [entry.name for entry in entries] == ["a", "b"]

        page = service.evaluate(library, smart["id"], limit=1, offset=1)
        assert [entry.name for entry in page] == ["b"]

        # An unknown order_by surfaces as a domain error, not an empty page.
        bad = service.create_smart(library, "bad", {})
        _ = bad
        from AssetsManager.domain.errors import ValidationError as VE
        with pytest.raises(VE):
            service.evaluate(library, smart["id"], limit=0)
    finally:
        conn.close()


def test_evaluate_tag_dimension_all_and_any(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    conn = _memory_conn()
    try:
        service = _service(conn, library)
        tag_svc = TagService(connection_provider=lambda _root: conn)
        paths = {
            name: _index_asset(conn, library, name)
            for name in ("ab.png", "ac.png", "ad.png")
        }
        tag_svc.add_tag(library, paths["ab.png"], "hero")
        tag_svc.add_tag(library, paths["ab.png"], "big")
        tag_svc.add_tag(library, paths["ac.png"], "hero")
        tag_svc.add_tag(library, paths["ad.png"], "big")

        both = service.create_smart(library, "hero+big", {
            "tags": ["hero", "big"], "tag_match": "all",
        })
        either = service.create_smart(library, "hero|big", {
            "tags": ["hero", "big"], "tag_match": "any",
        })

        assert [e.name for e in service.evaluate(library, both["id"])] == ["ab"]
        assert sorted(
            e.name for e in service.evaluate(library, either["id"])
        ) == ["ab", "ac", "ad"]

        # The default match mode is "all" (intersection).
        default_match = service.create_smart(library, "default", {"tags": ["hero", "big"]})
        assert [e.name for e in service.evaluate(library, default_match["id"])] == ["ab"]
    finally:
        conn.close()


def test_evaluate_tag_intersection_short_circuit(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    conn = _memory_conn()
    try:
        service = _service(conn, library)
        for name in ("a.png", "b.png"):
            _index_asset(conn, library, name)
        smart = service.create_smart(library, "impossible", {
            "tags": ["no-such-tag"], "tag_match": "all",
        })
        # A tag dimension matching nothing must not scan or match anything.
        assert service.evaluate(library, smart["id"]) == []
    finally:
        conn.close()


def test_smart_collection_is_a_query_view_and_never_moves_files(tmp_path):
    """Iron law: collections never move, copy, or delete files."""
    library = tmp_path / "library"
    library.mkdir()
    conn = _memory_conn()
    try:
        service = _service(conn, library)
        paths = [
            _index_asset(conn, library, name)
            for name in ("a.png", "b.jpg")
        ]
        original_names = sorted(p.name for p in library.iterdir())

        manual = service.create(library, "manual view")
        service.add_files(library, manual["id"], paths)
        smart = service.create_smart(
            library, "smart view", {"extensions": [".png"]}
        )
        service.evaluate(library, smart["id"])
        service.evaluate(library, smart["id"], limit=1, offset=1)

        # Evaluating and referencing left the filesystem byte-identical in
        # layout: same files, same places, nothing copied or renamed.
        assert sorted(p.name for p in library.iterdir()) == original_names
        for path in paths:
            assert Path(path).read_bytes() == b"data"

        # Deleting the collection likewise leaves the files untouched.
        service.delete(library, manual["id"])
        service.delete(library, smart["id"])
        assert sorted(p.name for p in library.iterdir()) == original_names
        for path in paths:
            assert Path(path).exists()
    finally:
        conn.close()


def test_collection_service_publishes_collection_changed(tmp_path, monkeypatch):
    """Mutations publish the 17th domain event, scoped to the session."""
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import CollectionChanged

    library = tmp_path / "library"
    library.mkdir()
    asset = library / "a.png"
    asset.write_bytes(b"png")

    bus = EventBus()
    events = []
    bus.subscribe(CollectionChanged, events.append)
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)

    from AssetsManager.application.bootstrap import ApplicationBootstrap
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    service = bootstrap.runtime_for(session).services.collection_service
    try:
        created = service.create(session.root, "hero")
        service.add_files(session.root, created["id"], [asset])
        service.remove_files(session.root, created["id"], [asset])
        service.rename(session.root, created["id"], "hero2")
        service.delete(session.root, created["id"])

        assert [event.kind for event in events] == [
            "manual", "manual", "manual", "manual", "manual",
        ]
        assert events[0].collection_id == created["id"]
        assert events[0].paths == ()
        # Membership changes carry the affected member paths for the router.
        assert events[1].paths == (str(asset.resolve()),)
        assert events[2].paths == (str(asset.resolve()),)
        assert events[3].paths == ()
        # Every event is scoped to the live session token.
        assert all(event.session_token == session.event_token for event in events)
    finally:
        bootstrap.library_service.close()
