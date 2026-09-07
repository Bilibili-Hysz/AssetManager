"""N2 recovery acceptance matrix — rows 1 and 2 (workpack 2026-09-14).

Row 1 — normal full backup/restore: a synthetic library with Chinese,
space and literal ``%`` paths is seeded with tags, notes, urls, rating
5 / 0 / NULL, favorites, a manual collection (with members) and a smart
collection (with a structured rule).  A complete RuntimeData backup ZIP is
created, validated, and restored into a NEW destination runtime domain
(fresh ``AM_RUNTIME_ROOT``, same library root path — the supported restore
target).  Assertions cover the ZIP manifest/digest gate, the raw-asset
contract (library-root files are NOT in the ZIP and are byte-identical
after restore), and the full DB projection round-trip.

Row 2 — metadata JSON export: the same seed is exported with
``export_metadata_json``.  Assertions pin the real contract observed in
``build_metadata_export``: exactly the stable-sorted relative path /
path_type / tags / notes / urls fields; Chinese and ``%`` paths intact;
rating/favorite/collection state explicitly NOT in the JSON contract;
atomic destination replacement.

Every scenario runs entirely inside ``tmp_path`` with a per-phase isolated
``AM_RUNTIME_ROOT``; user asset directories are never touched.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import zipfile

import pytest

import AssetsManager.application.library_export_io as export_io_module
from AssetsManager.application import ApplicationBootstrap
from AssetsManager.application.favorite_service import FavoriteService
from AssetsManager.core import path_resolver

# Raw assets under the library root.  The directory name carries Chinese
# characters, a space and a literal percent sign — the encodings that the
# workpack requires to survive both products untouched.
LIBRARY_FILES: dict[str, bytes] = {
    "中文 50%/hero.png": b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4,
    "普通/scene.txt": "场景说明：普通目录\n".encode("utf-8"),
    "未评分/unrated.png": b"\x89PNG\r\n\x1a\n" + b"unrated" * 20,
}
OWNER_KEY = "tester"
MANUAL_COLLECTION = "普通集合"
SMART_COLLECTION = "高分图片"
SMART_QUERY = {"extensions": [".png"], "rating_min": 4}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_raw_assets(root: Path) -> None:
    for relative, content in LIBRARY_FILES.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def _asset_paths(root: Path) -> dict[str, str]:
    """Relative POSIX path -> absolute path for the seeded raw assets."""
    return {relative: str(root / relative) for relative in LIBRARY_FILES}


def _walk_digests(root: Path) -> dict[str, str]:
    """Relative POSIX path -> SHA-256 for every file under *root*."""
    return {
        path.relative_to(root).as_posix(): _digest(path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _seed_runtime_data(services, session, root: Path) -> dict[str, object]:
    """Write the full RuntimeData projection through the service layer."""
    tag_service = services.tag_service
    metadata_service = services.metadata_service
    # Favorites are principal-scoped and not exposed on LibraryScopedServices;
    # tests construct the service directly on the live session.
    favorite_service = FavoriteService(session=session)
    collection_service = services.collection_service

    paths = _asset_paths(root)
    hero, scene, unrated = paths["中文 50%/hero.png"], paths["普通/scene.txt"], (
        paths["未评分/unrated.png"]
    )

    tag_service.add_tag(root, hero, "主角")
    tag_service.add_tag(root, hero, "Hero")
    tag_service.add_tag(root, scene, "场景")
    tag_service.add_tag(root, scene, "alpha")
    tag_service.add_tag(root, scene, "Beta")
    tag_service.add_tag(root, unrated, "draft")

    metadata_service.set_notes(root, hero, "主角备注：中文内容 ✓")
    metadata_service.set_notes(root, scene, "plain scene note")
    metadata_service.set_notes(root, unrated, "未评分说明")
    metadata_service.add_url(root, hero, "https://example.test/a")
    metadata_service.add_url(root, hero, "https://example.test/b")
    metadata_service.add_url(root, scene, "https://example.test/scene")

    # Rating 5 / rating 0 / rating NULL (row exists via notes, never rated).
    metadata_service.set_rating(root, hero, 5)
    metadata_service.set_rating(root, scene, 0)

    favorite_service.add(root, OWNER_KEY, hero)
    favorite_service.add(root, OWNER_KEY, scene)

    manual = collection_service.create(root, MANUAL_COLLECTION)
    collection_service.add_files(root, manual["id"], [hero, scene])
    smart = collection_service.create_smart(root, SMART_COLLECTION, SMART_QUERY)

    # Populate the assets index so the smart collection can be evaluated.
    services.asset_index_service.index_directory_tree(root)

    return {
        "manual_id": manual["id"],
        "smart_id": smart["id"],
        "hero": hero,
        "scene": scene,
        "unrated": unrated,
    }


def _projection(conn: sqlite3.Connection) -> dict:
    """Full DB projection snapshot straight from RuntimeData SQLite."""
    tags = {
        (row[0], row[1])
        for row in conn.execute("SELECT file_path, tag FROM file_tags")
    }
    meta = {
        row[0]: {"notes": row[1], "urls": json.loads(row[2]), "rating": row[3]}
        for row in conn.execute("SELECT file_path, notes, urls, rating FROM file_meta")
    }
    favorites = {
        (row[0], row[1])
        for row in conn.execute("SELECT owner_key, file_path FROM library_favorites")
    }
    collections: dict[str, dict] = {}
    for collection_id, name, kind, query_json in conn.execute(
        "SELECT id, name, kind, query_json FROM asset_collections"
    ):
        members = {
            row[0]
            for row in conn.execute(
                "SELECT file_path FROM asset_collection_members WHERE collection_id=?",
                (collection_id,),
            )
        }
        collections[name] = {
            "kind": kind,
            "query_json": query_json,
            "members": members,
        }
    return {
        "tags": tags,
        "meta": meta,
        "favorites": favorites,
        "collections": collections,
    }


@pytest.fixture()
def runtime_domain(tmp_path, monkeypatch):
    """Return a callable that re-points the process runtime domain.

    Each call installs a fresh isolated ``AM_RUNTIME_ROOT`` under tmp_path
    (env var + the resolver function used by every caller), so a test can
    move from a source runtime domain to a destination runtime domain
    without ever touching a real asset or user directory.
    """
    installed: list[Path] = []

    def install(name: str) -> Path:
        domain = tmp_path / f"runtime-{name}"
        domain.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("AM_RUNTIME_ROOT", str(domain))
        monkeypatch.setattr(path_resolver, "runtime_root", lambda: domain)
        installed.append(domain)
        return domain

    return install


def test_row1_full_backup_restore_round_trip(tmp_path, runtime_domain):
    library = tmp_path / "library"
    library.mkdir()
    _write_raw_assets(library)
    expected_assets = _walk_digests(library)

    # ── Source runtime domain: seed, snapshot the projection, back up ──
    runtime_domain("source")
    bootstrap = ApplicationBootstrap()
    try:
        session = bootstrap.library_service.open_session(library)
        services = bootstrap.runtime_for(session).services
        root = session.root
        ids = _seed_runtime_data(services, session, root)
        projection_before = _projection(session.connection_for())
        smart_before = [
            entry.file_path
            for entry in services.collection_service.evaluate(
                root, ids["smart_id"], limit=100
            )
        ]
        favorites_before = FavoriteService(session=session).list_paths(
            root, OWNER_KEY
        )

        # Non-vacuity guards: the seed actually landed before we compare.
        assert len(projection_before["tags"]) >= 6
        assert set(projection_before["meta"]) == set(_asset_paths(root).values())
        assert projection_before["favorites"]
        assert projection_before["collections"][MANUAL_COLLECTION]["members"]
        assert smart_before == [_asset_paths(root)["中文 50%/hero.png"]]

        archive = tmp_path / "artifacts" / "library_backup.assetbackup.zip"
        backup_result = services.export_service.create_backup(root, archive)
        archive_digest = _digest(archive.read_bytes())

        # ZIP manifest/digest gate on the generated archive.
        with zipfile.ZipFile(archive) as archive_file:
            names = set(archive_file.namelist())
            manifest = json.loads(archive_file.read("manifest.json"))
            for entry in manifest["files"]:
                member = archive_file.read(entry["path"])
                assert _digest(member) == entry["sha256"]
                assert len(member) == entry["size"]
        member_names = {entry["path"] for entry in manifest["files"]}
        assert names == member_names | {"manifest.json"}
        assert "data/assetmanager.db" in member_names
        # The raw-asset contract: library-root files are NOT backup members.
        assert not any(relative in names for relative in LIBRARY_FILES)

        validation = services.export_service.validate_backup(
            archive, expected_library_root=root
        )
        assert validation.valid
        assert validation.errors == ()
        assert validation.file_count == backup_result.file_count
        assert validation.database_quick_check == "ok"
    finally:
        bootstrap.library_service.close()

    # ── Destination runtime domain: restore and verify ──
    destination_runtime = runtime_domain("destination")
    bootstrap_b = ApplicationBootstrap()
    try:
        session_b = bootstrap_b.library_service.open_session(library)
        service_b = bootstrap_b.runtime_for(session_b).services.export_service
        # Fresh empty slot in the destination runtime domain.
        assert session_b.data_dir.is_relative_to(destination_runtime)
        bootstrap_b.library_service.close_session(session_b)

        restore_result = service_b.restore_backup(
            archive, library, overwrite_existing=True
        )
        assert restore_result.data_dir.is_relative_to(destination_runtime)
        assert restore_result.previous_data_dir is not None
        assert restore_result.previous_data_dir.is_dir()
        assert restore_result.file_count == backup_result.file_count
        # The archive itself was consumed read-only.
        assert _digest(archive.read_bytes()) == archive_digest

        reopened = bootstrap_b.library_service.open_session(library)
        services_b = bootstrap_b.runtime_for(reopened).services

        # Re-validation against the destination domain.
        revalidation = service_b.validate_backup(
            archive, expected_library_root=reopened.root
        )
        assert revalidation.valid
        assert revalidation.database_quick_check == "ok"

        # Raw-asset contract: same relative paths, byte-identical content.
        assert _walk_digests(library) == expected_assets
        for relative, content in LIBRARY_FILES.items():
            assert (library / relative).read_bytes() == content

        # Full DB projection round-trip: tags, notes, urls, ratings
        # (5 / 0 / NULL kept distinct), favorites, collections.
        projection_after = _projection(reopened.connection_for())
        assert projection_after == projection_before

        paths = _asset_paths(reopened.root)
        hero, scene, unrated = (
            paths["中文 50%/hero.png"],
            paths["普通/scene.txt"],
            paths["未评分/unrated.png"],
        )
        meta_after = projection_after["meta"]
        assert meta_after[hero]["rating"] == 5
        assert meta_after[scene]["rating"] == 0
        assert meta_after[scene]["rating"] is not None  # 0 is not falsy-loss
        assert meta_after[unrated]["rating"] is None  # NULL stays NULL
        assert meta_after[hero]["notes"] == "主角备注：中文内容 ✓"
        assert meta_after[hero]["urls"] == [
            "https://example.test/a",
            "https://example.test/b",
        ]
        assert meta_after[scene]["urls"] == ["https://example.test/scene"]

        favorites_after = FavoriteService(session=reopened).list_paths(
            reopened.root, OWNER_KEY
        )
        assert favorites_after == favorites_before

        # Manual collection members and smart collection rule survived.
        collections = projection_after["collections"]
        assert collections[MANUAL_COLLECTION]["members"] == {hero, scene}
        assert json.loads(collections[SMART_COLLECTION]["query_json"]) == SMART_QUERY

        # Smart collection re-evaluates to the same result after restore.
        smart_after = [
            entry.file_path
            for entry in services_b.collection_service.evaluate(
                reopened.root, ids["smart_id"], limit=100
            )
        ]
        assert smart_after == smart_before
        assert set(smart_before) == {hero}  # rating_min=4 keeps 0/NULL out

        # Restore intent marker consumed on success.
        assert not export_io_module.restore_intent_path(
            reopened.data_dir
        ).exists()
    finally:
        bootstrap_b.library_service.close()


def test_row2_metadata_json_export_contract(tmp_path, runtime_domain):
    library = tmp_path / "library"
    library.mkdir()
    _write_raw_assets(library)
    runtime_domain("main")
    bootstrap = ApplicationBootstrap()
    try:
        session = bootstrap.library_service.open_session(library)
        services = bootstrap.runtime_for(session).services
        root = session.root
        _seed_runtime_data(services, session, root)

        destination = tmp_path / "exports" / "nested" / "metadata.json"
        result = services.export_service.export_metadata_json(root, destination)

        assert result.destination == destination
        assert result.bytes_written == destination.stat().st_size
        raw = destination.read_bytes()
        payload = json.loads(raw.decode("utf-8"))

        # Top-level contract keys, exactly as implemented.
        assert set(payload) == {
            "format",
            "schema_version",
            "exported_at",
            "library",
            "entries",
        }
        assert payload["format"] == "assetsmanager.metadata"
        assert payload["schema_version"] == 1
        assert payload["library"]["path_format"] == "relative-to-library-root"

        entries = payload["entries"]
        assert len(entries) == len(LIBRARY_FILES)
        paths = [entry["path"] for entry in entries]
        assert paths == sorted(paths, key=lambda p: (p.casefold(), p))
        assert set(paths) == set(LIBRARY_FILES)
        for entry in entries:
            # Per-entry contract: the exact implemented field set.  Rating,
            # favorite and collection state are NOT part of the JSON export
            # contract (build_metadata_export collects notes/urls + tags).
            assert set(entry) == {"path", "path_type", "tags", "notes", "urls"}
            assert entry["path_type"] == "relative"

        by_path = {entry["path"]: entry for entry in entries}
        assert "中文 50%/hero.png" in by_path
        assert "普通/scene.txt" in by_path
        assert "未评分/unrated.png" in by_path

        # Entries match the stored DB rows exactly (stable, sorted tags).
        conn = session.connection_for()
        stored_tags: dict[str, list[str]] = {}
        for file_path, tag in conn.execute("SELECT file_path, tag FROM file_tags"):
            stored_tags.setdefault(file_path, []).append(tag)
        stored_meta = {
            row[0]: {"notes": row[1], "urls": json.loads(row[2])}
            for row in conn.execute("SELECT file_path, notes, urls FROM file_meta")
        }
        for relative, entry in by_path.items():
            absolute = str(root / relative)
            assert entry["tags"] == sorted(
                set(stored_tags.get(absolute, [])),
                key=lambda tag: (tag.casefold(), tag),
            )
            assert entry["notes"] == stored_meta[absolute]["notes"]
            assert entry["urls"] == stored_meta[absolute]["urls"]

        # Chinese and literal '%' paths survive as raw UTF-8 (no \u escapes).
        assert "中文 50%/hero.png".encode("utf-8") in raw
        assert "未评分说明".encode("utf-8") in raw
        assert b"50%" in raw
        assert b"\\u" not in raw

        # Rating / favorite / collection state is absent from the payload:
        # no such keys on entries and no such words anywhere in the JSON.
        serialized = json.dumps(payload, ensure_ascii=False)
        assert "rating" not in serialized
        assert "favorite" not in serialized
        assert "collection" not in serialized

        # Atomic destination replacement: re-export over the same target
        # fully replaces it and leaves no temporary residue.
        services.metadata_service.set_notes(
            root, root / "普通" / "scene.txt", "更新后的备注 第二版"
        )
        second = services.export_service.export_metadata_json(root, destination)
        assert second.entry_count == result.entry_count
        assert second.bytes_written == destination.stat().st_size
        payload2 = json.loads(destination.read_bytes().decode("utf-8"))
        scene_entry = next(
            entry
            for entry in payload2["entries"]
            if entry["path"] == "普通/scene.txt"
        )
        assert scene_entry["notes"] == "更新后的备注 第二版"
        assert not list(destination.parent.glob(".metadata.json.*.tmp"))
    finally:
        bootstrap.library_service.close()
