"""Tag source partition isolation (migration v36).

``file_tags`` stays the human-curated catalog; ``ai_asset_tags`` and
``plugin_derived_fields`` are physical mirrors reserved for non-human
sources.  Rows written through one source must never appear in another
source's queries, and the human default path must behave exactly as before
v36.
"""
import sqlite3
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from AssetsManager.repositories.tag_repository import TagRepository


def _migrated_conn() -> sqlite3.Connection:
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(database._SCHEMA)
    migrate(conn)
    return conn


def _library_with_asset(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    asset = library / "asset.txt"
    asset.write_text("asset", encoding="utf-8")
    return library, asset


# ── Repository level ──────────────────────────────────────────


def test_repository_source_partitions_are_isolated(tmp_path):
    from AssetsManager.core.schema_defs import validate_schema_objects

    library, asset = _library_with_asset(tmp_path)
    conn = _migrated_conn()
    try:
        repo = TagRepository(conn, library_root=library)
        validate_schema_objects(conn, ("ai_asset_tags", "plugin_derived_fields"))

        repo.add_tag(asset, "ai-tag", source="ai")
        repo.add_tag(asset, "plugin-tag", source="plugin")
        repo.add_tag(asset, "human-tag")

        # Per-source reads only see their own rows.
        assert repo.get_tags(asset) == ["human-tag"]
        assert repo.get_tags(asset, source="ai") == ["ai-tag"]
        assert repo.get_tags(asset, source="plugin") == ["plugin-tag"]

        assert repo.get_all_tags() == ["human-tag"]
        assert repo.get_all_tags(source="ai") == ["ai-tag"]
        assert repo.get_all_tags(source="plugin") == ["plugin-tag"]

        assert repo.get_files_by_tag("ai-tag") == []
        assert repo.get_files_by_tag("ai-tag", source="ai") == [str(asset.resolve())]
        assert repo.get_files_by_tag("human-tag", source="plugin") == []

        assert repo.list_tags_with_counts() == [{"name": "human-tag", "count": 1}]
        assert repo.list_tags_with_counts(source="ai") == [
            {"name": "ai-tag", "count": 1}
        ]
        assert repo.list_tags_with_counts(source="plugin") == [
            {"name": "plugin-tag", "count": 1}
        ]

        # Physical placement: exactly one row per partition.
        assert conn.execute("SELECT COUNT(*) FROM file_tags").fetchone() == (1,)
        assert conn.execute("SELECT COUNT(*) FROM ai_asset_tags").fetchone() == (1,)
        assert conn.execute(
            "SELECT COUNT(*) FROM plugin_derived_fields"
        ).fetchone() == (1,)

        # Removal through one source leaves the other partitions untouched.
        repo.remove_tag(asset, "ai-tag", source="ai")
        assert repo.get_tags(asset, source="ai") == []
        assert repo.get_tags(asset) == ["human-tag"]
    finally:
        conn.close()


def test_repository_same_tag_name_coexists_across_sources(tmp_path):
    library, asset = _library_with_asset(tmp_path)
    conn = _migrated_conn()
    try:
        repo = TagRepository(conn, library_root=library)
        repo.add_tag(asset, "hero")
        repo.add_tag(asset, "hero", source="ai")

        assert repo.get_tags(asset) == ["hero"]
        assert repo.get_tags(asset, source="ai") == ["hero"]
        assert repo.get_files_by_tag("hero", source="ai") == [str(asset.resolve())]

        # Human removal does not touch the AI partition row.
        repo.remove_tag(asset, "hero")
        assert repo.get_tags(asset) == []
        assert repo.get_tags(asset, source="ai") == ["hero"]
    finally:
        conn.close()


def test_repository_rejects_unknown_source(tmp_path):
    library, asset = _library_with_asset(tmp_path)
    conn = _migrated_conn()
    try:
        repo = TagRepository(conn, library_root=library)
        with pytest.raises(ValueError, match="unknown tag source"):
            repo.get_tags(asset, source="alien")  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="unknown tag source"):
            repo.add_tag(asset, "tag", source="alien")  # type: ignore[arg-type]
        # Nothing was written anywhere.
        assert conn.execute("SELECT COUNT(*) FROM file_tags").fetchone() == (0,)
        assert conn.execute("SELECT COUNT(*) FROM ai_asset_tags").fetchone() == (0,)
    finally:
        conn.close()


# ── Service level ─────────────────────────────────────────────


def test_service_ai_source_add_and_remove_isolated_from_human(tmp_path):
    from AssetsManager.application import TagService

    library, asset = _library_with_asset(tmp_path)
    conn = _migrated_conn()
    try:
        service = TagService(connection_provider=lambda _root: conn)

        service.add_tag(library, asset, "human-tag")
        service.add_tag(library, asset, "ai-tag", source="ai")

        assert service.get_tags(library, asset) == ["human-tag"]
        assert service.get_tags(library, asset, source="ai") == ["ai-tag"]
        assert service.list_tags(library) == [{"name": "human-tag", "count": 1}]
        assert service.list_tags(library, source="ai") == [
            {"name": "ai-tag", "count": 1}
        ]
        assert service.get_all_tags(library) == ["human-tag"]
        assert service.get_all_tags(library, source="ai") == ["ai-tag"]
        assert service.get_files_by_tag(library, "ai-tag") == set()
        assert service.get_files_by_tag(library, "ai-tag", source="ai") == {
            str(asset.resolve())
        }

        # Same tag name is allowed per source (isolation, not a duplicate).
        service.add_tag(library, asset, "shared-tag", source="ai")
        assert service.get_tags(library, asset, source="ai") == [
            "ai-tag", "shared-tag",
        ]

        service.remove_tag(library, asset, "AI-TAG", source="ai")
        assert service.get_tags(library, asset, source="ai") == ["shared-tag"]
        assert service.get_tags(library, asset) == ["human-tag"]
    finally:
        conn.close()


def test_service_non_human_write_publishes_asset_event_but_not_catalog_event(
    tmp_path, monkeypatch
):
    from AssetsManager.application import TagService
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import AssetTagsChanged, TagCatalogChanged

    bus = EventBus()
    asset_events = []
    catalog_events = []
    bus.subscribe(AssetTagsChanged, asset_events.append)
    bus.subscribe(TagCatalogChanged, catalog_events.append)
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)

    library, asset = _library_with_asset(tmp_path)
    conn = _migrated_conn()
    try:
        session = SimpleNamespace(
            root=library,
            root_str=str(library.resolve()),
            event_token="token-test",
            operation=nullcontext,
        )
        service = TagService(
            connection_provider=lambda _root: conn, session=session
        )

        service.add_tag(library, asset, "ai-tag", source="ai")

        assert len(asset_events) == 1
        assert asset_events[0].new_tags == ("ai-tag",)
        assert catalog_events == []

        # Human writes keep the historical both-events behavior.
        service.add_tag(library, asset, "human-tag")
        assert len(asset_events) == 2
        assert len(catalog_events) == 1
    finally:
        conn.close()
