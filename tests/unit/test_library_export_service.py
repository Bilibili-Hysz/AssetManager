from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import io
from pathlib import Path
import sqlite3
import subprocess
import sys
import stat
import threading
import zipfile

import pytest

import AssetsManager.application.library_export_service as export_module
import AssetsManager.application.library_export_io as export_io_module
from AssetsManager.application import ApplicationBootstrap, LibraryExportService
from AssetsManager.core import path_resolver


@pytest.fixture(autouse=True)
def _use_temporary_runtime_root(tmp_path, monkeypatch):
    monkeypatch.setattr(path_resolver, "runtime_root", lambda: tmp_path / "RuntimeData")


def _open_session(tmp_path: Path):
    bootstrap = ApplicationBootstrap()
    library = tmp_path / "library"
    library.mkdir()
    session = bootstrap.library_service.open_session(library)
    return bootstrap, session


def test_build_metadata_export_uses_relative_paths_and_merges_tags_and_metadata(tmp_path):
    bootstrap, session = _open_session(tmp_path)
    try:
        inside = session.root / "images" / "one.png"
        inside.parent.mkdir()
        outside = tmp_path / "external.txt"
        conn = session.connection_for()
        conn.execute(
            "INSERT INTO file_meta (file_path, notes, urls) VALUES (?, ?, ?)",
            (str(inside), "note", '["https://example.test"]'),
        )
        conn.execute(
            "INSERT INTO file_tags (file_path, tag) VALUES (?, ?)",
            (str(inside), "hero"),
        )
        conn.execute(
            "INSERT INTO file_tags (file_path, tag) VALUES (?, ?)",
            (str(inside), "Hero"),
        )
        conn.execute(
            "INSERT INTO file_tags (file_path, tag) VALUES (?, ?)",
            (str(outside), "external"),
        )
        conn.commit()

        service = bootstrap.runtime_for(session).services.export_service
        payload = service.build_metadata_export(session.root)

        assert payload["format"] == "assetsmanager.metadata"
        assert payload["schema_version"] == 1
        assert payload["library"] == {
            "name": "library",
            "path_format": "relative-to-library-root",
        }
        assert len(payload["entries"]) == 2
        by_path = {entry["path"]: entry for entry in payload["entries"]}
        assert by_path["images/one.png"] == {
            "path": "images/one.png",
            "path_type": "relative",
            "tags": ["Hero", "hero"],
            "notes": "note",
            "urls": ["https://example.test"],
        }
        external_entry = next(
            entry for entry in payload["entries"] if entry["tags"] == ["external"]
        )
        assert external_entry["path_type"] == "absolute"
        assert external_entry["path"].endswith("/external.txt")
        assert "password_hash" not in json.dumps(payload)
    finally:
        bootstrap.library_service.close()


def test_export_metadata_json_writes_atomically_and_reports_size(tmp_path):
    bootstrap, session = _open_session(tmp_path)
    try:
        file_path = session.root / "note.txt"
        conn = session.connection_for()
        conn.execute(
            "INSERT INTO file_meta (file_path, notes) VALUES (?, ?)",
            (str(file_path), "hello"),
        )
        conn.commit()
        destination = tmp_path / "exports" / "metadata.json"

        service = bootstrap.runtime_for(session).services.export_service
        result = service.export_metadata_json(session.root, destination)

        assert result.destination == destination
        assert result.entry_count == 1
        assert result.bytes_written == destination.stat().st_size
        payload = json.loads(destination.read_text(encoding="utf-8"))
        assert payload["entries"] == [
            {
                "path": "note.txt",
                "path_type": "relative",
                "tags": [],
                "notes": "hello",
                "urls": [],
            }
        ]
        assert not list(destination.parent.glob(".metadata.json.*.tmp"))
    finally:
        bootstrap.library_service.close()


def test_export_metadata_json_rejects_library_database_destination(tmp_path):
    bootstrap, session = _open_session(tmp_path)
    try:
        service = bootstrap.runtime_for(session).services.export_service
        with pytest.raises(ValueError, match="library database"):
            service.export_metadata_json(session.root, session.data_dir / "assetmanager.db")
    finally:
        bootstrap.library_service.close()


def test_export_service_is_bound_to_runtime_session(tmp_path):
    bootstrap, session = _open_session(tmp_path)
    try:
        service = bootstrap.runtime_for(session).services.export_service
        assert isinstance(service, LibraryExportService)
        assert service._session is session
    finally:
        bootstrap.library_service.close()


def test_backup_filename_is_timestamped(tmp_path):
    name = LibraryExportService.backup_filename(
        tmp_path / "library",
        datetime(2026, 8, 4, 12, 30, tzinfo=timezone.utc),
    )
    assert name == "library_backup_20260804T123000Z.assetbackup.zip"


def test_create_backup_uses_sqlite_snapshot_and_excludes_thumbnails(tmp_path):
    bootstrap, session = _open_session(tmp_path)
    try:
        conn = session.connection_for()
        conn.execute(
            "INSERT INTO file_meta (file_path, notes) VALUES (?, ?)",
            (str(session.root / "note.txt"), "from snapshot"),
        )
        conn.commit()
        (session.data_dir / "favorites.json").write_text(
            '["note.txt"]', encoding="utf-8"
        )
        (session.thumb_dir / "cached.webp").write_bytes(b"thumbnail")
        destination = tmp_path / "backups" / "library.assetbackup.zip"
        service = bootstrap.runtime_for(session).services.export_service

        result = service.create_backup(session.root, destination)

        assert result.destination == destination
        assert result.file_count == 2
        assert not result.includes_thumbnails
        with zipfile.ZipFile(destination) as archive:
            names = set(archive.namelist())
            assert names == {"manifest.json", "data/assetmanager.db", "data/favorites.json"}
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["format"] == "assetsmanager.library-backup"
            assert manifest["schema_version"] == 1
            assert manifest["includes_thumbnails"] is False
            db_bytes = archive.read("data/assetmanager.db")
        with sqlite3.connect(":memory:") as snapshot:
            snapshot.deserialize(db_bytes)
            assert snapshot.execute(
                "SELECT notes FROM file_meta WHERE file_path=?",
                (str(session.root / "note.txt"),),
            ).fetchone() == ("from snapshot",)

        validation = service.validate_backup(
            destination, expected_library_root=session.root
        )
        assert validation.valid
        assert validation.file_count == 2
        assert validation.database_quick_check == "ok"
        assert not validation.includes_thumbnails
    finally:
        bootstrap.library_service.close()


def test_create_backup_can_include_thumbnails_and_rejects_live_data_destination(tmp_path):
    bootstrap, session = _open_session(tmp_path)
    try:
        (session.thumb_dir / "cached.webp").write_bytes(b"thumbnail")
        service = bootstrap.runtime_for(session).services.export_service
        destination = tmp_path / "with-thumbnails.assetbackup.zip"
        result = service.create_backup(
            session.root, destination, include_thumbnails=True
        )

        assert result.includes_thumbnails
        with zipfile.ZipFile(destination) as archive:
            assert "data/.thumbnails/cached.webp" in archive.namelist()
        validation = service.validate_backup(destination)
        assert validation.valid
        assert validation.includes_thumbnails
        with pytest.raises(ValueError, match="outside"):
            service.create_backup(
                session.root, session.data_dir / "nested.assetbackup.zip"
            )
    finally:
        bootstrap.library_service.close()


def test_validate_backup_rejects_tampered_member_and_unsafe_path(tmp_path):
    bootstrap, session = _open_session(tmp_path)
    try:
        marker = session.data_dir / "favorites.json"
        marker.write_text("original", encoding="utf-8")
        service = bootstrap.runtime_for(session).services.export_service
        valid_path = tmp_path / "valid.assetbackup.zip"
        service.create_backup(session.root, valid_path)

        tampered_path = tmp_path / "tampered.assetbackup.zip"
        with zipfile.ZipFile(valid_path) as source, zipfile.ZipFile(
            tampered_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as target:
            for info in source.infolist():
                data = source.read(info.filename)
                if info.filename == "data/favorites.json":
                    data = b"tampered"
                target.writestr(info, data)
        tampered = service.validate_backup(tampered_path)
        assert not tampered.valid
        assert any("checksum mismatch" in error for error in tampered.errors)

        unsafe_path = tmp_path / "unsafe.assetbackup.zip"
        manifest = {
            "format": "assetsmanager.library-backup",
            "schema_version": 1,
            "created_at": "2026-08-04T00:00:00Z",
            "library": {"name": session.root.name},
            "includes_thumbnails": False,
            "files": [
                {
                    "path": "data/../escape.txt",
                    "size": 0,
                    "sha256": hashlib.sha256(b"").hexdigest(),
                }
            ],
        }
        with zipfile.ZipFile(unsafe_path, "w") as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            archive.writestr("data/../escape.txt", b"")
        unsafe = service.validate_backup(unsafe_path)
        assert not unsafe.valid
        assert any("Unsafe backup member path" in error for error in unsafe.errors)
    finally:
        bootstrap.library_service.close()


def test_restore_backup_requires_closed_session_and_explicit_overwrite(tmp_path):
    bootstrap, session = _open_session(tmp_path)
    try:
        service = bootstrap.runtime_for(session).services.export_service
        archive = tmp_path / "restore.assetbackup.zip"
        service.create_backup(session.root, archive)
        with pytest.raises(RuntimeError, match="session to be closed"):
            service.restore_backup(archive, session.root, overwrite_existing=True)
    finally:
        bootstrap.library_service.close()

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        service = bootstrap.runtime_for(session).services.export_service
        bootstrap.library_service.close_session(session)
        with pytest.raises(FileExistsError, match="explicit overwrite"):
            service.restore_backup(archive, session.root)
    finally:
        bootstrap.library_service.close()


def test_restore_backup_replaces_data_and_preserves_previous_copy(tmp_path):
    bootstrap, session = _open_session(tmp_path)
    root = session.root
    try:
        conn = session.connection_for()
        conn.execute(
            "INSERT INTO file_meta (file_path, notes) VALUES (?, ?)",
            (str(root / "from-backup.txt"), "restored"),
        )
        conn.commit()
        (session.data_dir / "backup-marker.json").write_text(
            "from-backup", encoding="utf-8"
        )
        archive = tmp_path / "restore.assetbackup.zip"
        service = bootstrap.runtime_for(session).services.export_service
        service.create_backup(root, archive)
        (session.data_dir / "old-only.txt").write_text("old", encoding="utf-8")
        bootstrap.library_service.close_session(session)

        result = service.restore_backup(archive, root, overwrite_existing=True)

        assert result.data_dir == session.data_dir
        assert result.previous_data_dir is not None
        assert result.previous_data_dir.is_dir()
        assert (result.data_dir / "backup-marker.json").read_text(encoding="utf-8") == (
            "from-backup"
        )
        assert not (result.data_dir / "old-only.txt").exists()
        assert (result.previous_data_dir / "old-only.txt").read_text(encoding="utf-8") == (
            "old"
        )
    finally:
        bootstrap.library_service.close()


def test_restore_backup_rolls_back_when_installed_database_check_fails(tmp_path, monkeypatch):
    bootstrap, session = _open_session(tmp_path)
    root = session.root
    try:
        marker = session.data_dir / "old-only.txt"
        marker.write_text("old", encoding="utf-8")
        archive = tmp_path / "restore.assetbackup.zip"
        service = bootstrap.runtime_for(session).services.export_service
        service.create_backup(root, archive)
        bootstrap.library_service.close_session(session)

        check_calls = 0

        def fail_installed_check(_database_file):
            nonlocal check_calls
            check_calls += 1
            if check_calls == 2:
                raise RuntimeError("simulated restore check failure")

        monkeypatch.setattr(
            service, "_quick_check_database_file", fail_installed_check
        )
        with pytest.raises(RuntimeError, match="simulated restore"):
            service.restore_backup(archive, root, overwrite_existing=True)
        assert check_calls == 2

        assert marker.read_text(encoding="utf-8") == "old"
        assert session.data_dir.is_dir()
    finally:
        bootstrap.library_service.close()



def test_restore_backup_without_coordinator_fails_closed(tmp_path):
    bootstrap, session = _open_session(tmp_path)
    try:
        archive = tmp_path / "restore.assetbackup.zip"
        coordinated = bootstrap.runtime_for(session).services.export_service
        coordinated.create_backup(session.root, archive)
        uncoordinated = LibraryExportService(
            connection_provider=session.connection_for,
            session=session,
        )
        bootstrap.library_service.close_session(session)

        with pytest.raises(RuntimeError, match="ownership coordinator"):
            uncoordinated.restore_backup(
                archive, session.root, overwrite_existing=True
            )
    finally:
        bootstrap.library_service.close()


def test_restore_backup_rejects_closed_but_uncommitted_session(tmp_path):
    bootstrap, session = _open_session(tmp_path)
    calls = 0
    try:
        service = bootstrap.runtime_for(session).services.export_service
        archive = tmp_path / "restore.assetbackup.zip"
        service.create_backup(session.root, archive)

        def fail_once(_session):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("teardown listener failed")

        bootstrap.library_service.add_session_closing_listener(fail_once)
        with pytest.raises(RuntimeError, match="teardown listener failed"):
            bootstrap.library_service.close_session(session)
        assert session.is_closed

        with pytest.raises(RuntimeError, match="committed teardown"):
            service.restore_backup(archive, session.root, overwrite_existing=True)

        bootstrap.library_service.close_session(session)
    finally:
        bootstrap.library_service.close()



def test_restore_backup_rejects_closed_session_when_service_lock_release_failed(
    tmp_path, monkeypatch
):
    bootstrap, session = _open_session(tmp_path)
    try:
        service = bootstrap.runtime_for(session).services.export_service
        archive = tmp_path / "restore.assetbackup.zip"
        service.create_backup(session.root, archive)
        owned_lock = bootstrap.library_service._library_locks[str(session.root)]
        real_release = owned_lock.release
        release_calls = 0

        def fail_once():
            nonlocal release_calls
            release_calls += 1
            if release_calls == 1:
                return False
            return real_release()

        monkeypatch.setattr(owned_lock, "release", fail_once)
        with pytest.raises(RuntimeError, match="Failed to release library lock"):
            bootstrap.library_service.close_session(session)
        assert session.is_closed

        with pytest.raises(RuntimeError, match="committed teardown"):
            service.restore_backup(archive, session.root, overwrite_existing=True)

        bootstrap.library_service.close_session(session)
    finally:
        bootstrap.library_service.close()

def test_restore_backup_rejects_old_owner_after_same_root_replacement(tmp_path):
    bootstrap, session = _open_session(tmp_path)
    replacement = None
    try:
        service = bootstrap.runtime_for(session).services.export_service
        archive = tmp_path / "restore.assetbackup.zip"
        service.create_backup(session.root, archive)
        bootstrap.library_service.close_session(session)
        replacement = bootstrap.library_service.open_session(session.root)

        with pytest.raises(RuntimeError, match="committed teardown"):
            service.restore_backup(archive, session.root, overwrite_existing=True)
    finally:
        if replacement is not None and not replacement.is_closed:
            bootstrap.library_service.close_session(replacement)
        bootstrap.library_service.close()


def test_restore_reservation_blocks_same_root_open_until_restore_finishes(
    tmp_path, monkeypatch
):
    bootstrap, session = _open_session(tmp_path)
    replacement = None
    restore_entered = threading.Event()
    allow_restore = threading.Event()
    restore_errors = []
    opened = []
    try:
        service = bootstrap.runtime_for(session).services.export_service
        archive = tmp_path / "restore.assetbackup.zip"
        service.create_backup(session.root, archive)
        bootstrap.library_service.close_session(session)
        original_extract = service._extract_validated_backup

        def blocked_extract(*args, **kwargs):
            restore_entered.set()
            assert allow_restore.wait(5)
            return original_extract(*args, **kwargs)

        monkeypatch.setattr(service, "_extract_validated_backup", blocked_extract)

        def run_restore():
            try:
                service.restore_backup(archive, session.root, overwrite_existing=True)
            except BaseException as exc:
                restore_errors.append(exc)

        def run_open():
            opened.append(bootstrap.library_service.open_session(session.root))

        restore_thread = threading.Thread(target=run_restore)
        open_thread = threading.Thread(target=run_open)
        restore_thread.start()
        assert restore_entered.wait(5)
        open_thread.start()
        open_thread.join(0.2)
        assert open_thread.is_alive()
        assert opened == []
        allow_restore.set()
        restore_thread.join(5)
        open_thread.join(5)

        assert not restore_thread.is_alive()
        assert not open_thread.is_alive()
        assert restore_errors == []
        replacement = opened[0]
        assert replacement is not session
    finally:
        allow_restore.set()
        if replacement is not None and not replacement.is_closed:
            bootstrap.library_service.close_session(replacement)
        bootstrap.library_service.close()


def test_restore_uses_one_archive_handle_and_rechecks_extraction_policy(
    tmp_path, monkeypatch
):
    bootstrap, session = _open_session(tmp_path)
    try:
        service = bootstrap.runtime_for(session).services.export_service
        archive_path = tmp_path / "restore.assetbackup.zip"
        service.create_backup(session.root, archive_path)
        bootstrap.library_service.close_session(session)
        real_zip_file = export_module.zipfile.ZipFile
        opened_paths = []

        def tracked_zip_file(*args, **kwargs):
            opened_paths.append(args[0])
            return real_zip_file(*args, **kwargs)

        original_validate = service._validate_open_backup

        def mutate_after_validation(archive, **kwargs):
            result, entries = original_validate(archive, **kwargs)
            assert result.valid
            archive.getinfo(entries[0][0]).external_attr = (
                stat.S_IFLNK | 0o777
            ) << 16
            return result, entries

        monkeypatch.setattr(export_module.zipfile, "ZipFile", tracked_zip_file)
        monkeypatch.setattr(service, "_validate_open_backup", mutate_after_validation)

        with pytest.raises(ValueError, match="link or special file"):
            service.restore_backup(
                archive_path, session.root, overwrite_existing=True
            )
        assert len(opened_paths) == 1
        assert hasattr(opened_paths[0], "read")
    finally:
        bootstrap.library_service.close()


def test_restore_staging_failure_is_quarantined_and_original_error_survives(
    tmp_path, monkeypatch
):
    bootstrap, session = _open_session(tmp_path)
    try:
        service = bootstrap.runtime_for(session).services.export_service
        archive = tmp_path / "restore.assetbackup.zip"
        service.create_backup(session.root, archive)
        bootstrap.library_service.close_session(session)

        def fail_extract(_archive, destination, _entries):
            (destination / "partial.txt").write_text("partial", encoding="utf-8")
            raise RuntimeError("staging extraction failed")

        monkeypatch.setattr(service, "_extract_validated_backup", fail_extract)
        quarantine = session.data_dir.parent / "_orphaned" / "restore-backups"
        before = set(quarantine.glob("failed-staging_*")) if quarantine.exists() else set()
        with pytest.raises(RuntimeError, match="staging extraction failed") as caught:
            service.restore_backup(archive, session.root, overwrite_existing=True)
        assert caught.value.restore_recovery_required is True
        canonical = bootstrap.library_service.restore_failure_state(session.root)
        assert canonical is not None
        assert canonical.phase == "staging"
        assert caught.value.restore_failure_state.phase == canonical.phase
        assert caught.value.restore_failure_state.token == canonical.token
        assert caught.value.restore_failure_state.generation == canonical.generation

        failed = set(quarantine.glob("failed-staging_*")) - before
        assert len(failed) == 1
        failed_entry = failed.pop()
        assert (failed_entry / "partial.txt").read_text(encoding="utf-8") == "partial"
    finally:
        bootstrap.library_service.close()


def test_restore_quarantine_failure_is_exposed_on_original_error(
    tmp_path, monkeypatch
):
    bootstrap, session = _open_session(tmp_path)
    try:
        service = bootstrap.runtime_for(session).services.export_service
        archive = tmp_path / "restore.assetbackup.zip"
        service.create_backup(session.root, archive)
        bootstrap.library_service.close_session(session)

        def fail_extract(_archive, destination, _entries):
            (destination / "partial.txt").write_text("partial", encoding="utf-8")
            raise RuntimeError("primary staging failure")

        def fail_quarantine(*_args, **_kwargs):
            raise OSError("quarantine unavailable")

        monkeypatch.setattr(service, "_extract_validated_backup", fail_extract)
        monkeypatch.setattr(service, "_move_to_restore_quarantine", fail_quarantine)
        with pytest.raises(RuntimeError, match="primary staging failure") as caught:
            service.restore_backup(archive, session.root, overwrite_existing=True)

        assert caught.value.restore_retryable is True
        assert any(
            "quarantine unavailable" in detail
            for detail in caught.value.restore_secondary_errors
        )
    finally:
        bootstrap.library_service.close()


def test_restore_rollback_failure_is_exposed_on_installed_check_error(
    tmp_path, monkeypatch
):
    bootstrap, session = _open_session(tmp_path)
    try:
        marker = session.data_dir / "old-only.txt"
        marker.write_text("old", encoding="utf-8")
        service = bootstrap.runtime_for(session).services.export_service
        archive = tmp_path / "restore.assetbackup.zip"
        service.create_backup(session.root, archive)
        bootstrap.library_service.close_session(session)
        check_calls = 0

        def fail_installed_check(_database_file):
            nonlocal check_calls
            check_calls += 1
            if check_calls == 2:
                raise RuntimeError("installed quick_check failed")

        def fail_rollback(_previous, _data_dir):
            raise OSError("rollback rename failed")

        monkeypatch.setattr(
            service, "_quick_check_database_file", fail_installed_check
        )
        monkeypatch.setattr(service, "_restore_previous_data", fail_rollback)
        with pytest.raises(RuntimeError, match="installed quick_check failed") as caught:
            service.restore_backup(archive, session.root, overwrite_existing=True)

        assert caught.value.restore_retryable is True
        assert any(
            "rollback rename failed" in detail
            for detail in caught.value.restore_secondary_errors
        )
        quarantine = session.data_dir.parent / "_orphaned" / "restore-backups"
        assert any((candidate / "old-only.txt").exists() for candidate in quarantine.iterdir())
    finally:
        bootstrap.library_service.close()


def test_restore_lock_release_failure_is_retryable_and_not_silent(
    tmp_path, monkeypatch
):
    bootstrap, session = _open_session(tmp_path)
    try:
        service = bootstrap.runtime_for(session).services.export_service
        archive = tmp_path / "restore.assetbackup.zip"
        service.create_backup(session.root, archive)
        bootstrap.library_service.close_session(session)
        real_lock = export_module.LibraryLock

        class FalseReleaseLock:
            def __init__(self, path):
                self._inner = real_lock(path)
                self.path = self._inner.path

            def release(self):
                self._inner.release()
                return False

        monkeypatch.setattr(export_module, "LibraryLock", FalseReleaseLock)
        with pytest.raises(RuntimeError, match="Failed to release library lock") as caught:
            service.restore_backup(archive, session.root, overwrite_existing=True)

        assert caught.value.restore_retryable is True
    finally:
        bootstrap.library_service.close()

def test_list_restore_quarantine_returns_only_direct_real_directories(tmp_path, monkeypatch):
    bootstrap, session = _open_session(tmp_path)
    try:
        root = session.root
        service = bootstrap.runtime_for(session).services.export_service
        bootstrap.library_service.close_session(session)

        runtime_root = tmp_path / "RuntimeData"
        data_dir = runtime_root / "library-data"
        quarantine = runtime_root / "_orphaned" / "restore-backups"
        quarantine.mkdir(parents=True)
        (quarantine / "z-nonempty").mkdir()
        (quarantine / "z-nonempty" / "marker.txt").write_text("x", encoding="utf-8")
        (quarantine / "a-empty").mkdir()
        (quarantine / "ignored-file.txt").write_text("x", encoding="utf-8")

        monkeypatch.setattr(export_module, "library_data_dir", lambda _root: data_dir)
        monkeypatch.setattr(
            export_module,
            "library_lock_path",
            lambda _root: tmp_path / "library.lock",
        )

        entries = service.list_restore_quarantine(root)

        assert [entry.name for entry in entries] == ["a-empty", "z-nonempty"]
        assert entries[0].path == quarantine / "a-empty"
        assert entries[0].is_empty is True
        assert entries[1].is_empty is False
        assert all(entry.modified_at.tzinfo == timezone.utc for entry in entries)
    finally:
        bootstrap.library_service.close()


def test_list_restore_quarantine_ignores_traversal_and_absolute_symlink_entries(
    tmp_path, monkeypatch
):
    bootstrap, session = _open_session(tmp_path)
    try:
        root = session.root
        service = bootstrap.runtime_for(session).services.export_service
        bootstrap.library_service.close_session(session)

        runtime_root = tmp_path / "RuntimeData"
        data_dir = runtime_root / "library-data"
        quarantine = runtime_root / "_orphaned" / "restore-backups"
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("secret", encoding="utf-8")
        quarantine.mkdir(parents=True)
        (quarantine / "safe").mkdir()
        try:
            (quarantine / "traversal").symlink_to(
                quarantine / ".." / ".." / "outside", target_is_directory=True
            )
            (quarantine / "absolute").symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"directory symlinks unavailable: {exc}")

        monkeypatch.setattr(export_module, "library_data_dir", lambda _root: data_dir)
        monkeypatch.setattr(
            export_module,
            "library_lock_path",
            lambda _root: tmp_path / "library.lock",
        )

        entries = service.list_restore_quarantine(str(root / ".." / root.name))

        assert [entry.name for entry in entries] == ["safe"]
    finally:
        bootstrap.library_service.close()


def test_list_restore_quarantine_returns_empty_for_missing_or_non_directory_root(
    tmp_path, monkeypatch
):
    bootstrap, session = _open_session(tmp_path)
    try:
        root = session.root
        service = bootstrap.runtime_for(session).services.export_service
        bootstrap.library_service.close_session(session)
        runtime_root = tmp_path / "RuntimeData"
        data_dir = runtime_root / "library-data"
        monkeypatch.setattr(export_module, "library_data_dir", lambda _root: data_dir)
        monkeypatch.setattr(
            export_module,
            "library_lock_path",
            lambda _root: tmp_path / "library.lock",
        )

        assert service.list_restore_quarantine(root) == ()
        quarantine = runtime_root / "_orphaned" / "restore-backups"
        quarantine.parent.mkdir(parents=True)
        quarantine.write_text("not a directory", encoding="utf-8")
        assert service.list_restore_quarantine(root) == ()
    finally:
        bootstrap.library_service.close()



def test_create_backup_holds_one_session_lease_through_zip_publication(
    tmp_path, monkeypatch
):
    bootstrap, session = _open_session(tmp_path)
    errors: list[BaseException] = []
    backup_entered = threading.Event()
    allow_backup = threading.Event()
    try:
        marker = session.data_dir / "favorites.json"
        marker.write_text("stable", encoding="utf-8")
        destination = tmp_path / "leased.assetbackup.zip"
        service = bootstrap.runtime_for(session).services.export_service
        original_write = service._write_zip_file

        def blocking_write(archive, source, archive_path, **kwargs):
            if source == marker:
                backup_entered.set()
                assert allow_backup.wait(5)
            return original_write(archive, source, archive_path, **kwargs)

        monkeypatch.setattr(service, "_write_zip_file", blocking_write)

        def run_backup():
            try:
                service.create_backup(session.root, destination)
            except BaseException as exc:  # pragma: no cover - assertion reports details
                errors.append(exc)

        def run_close():
            try:
                bootstrap.library_service.close_session(session)
            except BaseException as exc:  # pragma: no cover - assertion reports details
                errors.append(exc)

        backup_thread = threading.Thread(target=run_backup)
        close_thread = threading.Thread(target=run_close)
        backup_thread.start()
        assert backup_entered.wait(5)
        close_thread.start()
        close_thread.join(0.2)
        assert close_thread.is_alive(), "close must drain the complete backup lease"
        allow_backup.set()
        backup_thread.join(5)
        close_thread.join(5)

        assert not errors
        assert not backup_thread.is_alive()
        assert not close_thread.is_alive()
        with zipfile.ZipFile(destination) as archive:
            assert archive.read("data/favorites.json") == b"stable"
    finally:
        allow_backup.set()
        bootstrap.library_service.close()


def test_validate_backup_caps_manifest_file_count_before_entry_iteration(
    tmp_path, monkeypatch
):
    bootstrap, session = _open_session(tmp_path)
    try:
        (session.data_dir / "favorites.json").write_text("[]", encoding="utf-8")
        service = bootstrap.runtime_for(session).services.export_service
        archive = tmp_path / "manifest-limit.assetbackup.zip"
        service.create_backup(session.root, archive)
        monkeypatch.setattr(service, "_MAX_MANIFEST_FILES", 1)

        result = service.validate_backup(archive)

        assert not result.valid
        assert result.file_count == 2
        assert any("manifest file count exceeds limit" in error for error in result.errors)
    finally:
        bootstrap.library_service.close()


def test_validate_backup_rejects_manifest_and_windows_canonical_duplicates(tmp_path):
    bootstrap, session = _open_session(tmp_path)
    try:
        marker = session.data_dir / "favorites.json"
        marker.write_text("same", encoding="utf-8")
        service = bootstrap.runtime_for(session).services.export_service
        source_path = tmp_path / "source.assetbackup.zip"
        service.create_backup(session.root, source_path)
        duplicate_path = tmp_path / "duplicate.assetbackup.zip"
        with zipfile.ZipFile(source_path) as source:
            manifest = json.loads(source.read("manifest.json"))
            favorite = next(
                entry for entry in manifest["files"] if entry["path"] == "data/favorites.json"
            )
            manifest["files"].append(dict(favorite))
            manifest["files"].append(
                {**favorite, "path": "data/FAVORITES.JSON"}
            )
            with zipfile.ZipFile(duplicate_path, "w") as target:
                for info in source.infolist():
                    if info.filename != "manifest.json":
                        target.writestr(info, source.read(info))
                target.writestr("data/FAVORITES.JSON", b"same")
                target.writestr("manifest.json", json.dumps(manifest))

        result = service.validate_backup(duplicate_path)

        assert not result.valid
        assert any("Duplicate manifest file path" in error for error in result.errors)
        assert any("Canonical Windows path collision" in error for error in result.errors)
    finally:
        bootstrap.library_service.close()


@pytest.mark.parametrize("left, right", [("Ъ", "ъ"), ("Ⅰ", "ⅰ"), ("Ⓐ", "ⓐ")])
def test_windows_component_key_covers_non_letter_win32_case_pairs(left, right):
    if sys.platform != "win32":
        pytest.skip("Win32 NLS case table is only available on Windows")
    assert LibraryExportService._windows_path_key(f"data/{left}") == (
        "data",
        LibraryExportService._windows_component_key(right),
    )


def test_windows_component_key_preserves_non_bmp_distinctions():
    left = LibraryExportService._windows_component_key("A😀B")
    right = LibraryExportService._windows_component_key("A😀C")
    assert left != right


@pytest.mark.parametrize("file_name", ["straße", "K"])
def test_windows_component_key_does_not_apply_unicode_expansions(file_name):
    other = "strasse" if file_name == "straße" else "k"
    assert LibraryExportService._windows_component_key(file_name) != (
        LibraryExportService._windows_component_key(other)
    )


@pytest.mark.parametrize(
    ("file_name", "directory_name"),
    [("straße", "strasse"), ("K", "k")],
)
def test_validate_backup_preserves_distinct_unicode_windows_names(
    tmp_path, file_name, directory_name
):
    bootstrap, session = _open_session(tmp_path)
    try:
        unicode_file = session.data_dir / file_name
        unicode_directory = session.data_dir / directory_name
        try:
            unicode_file.write_text("file", encoding="utf-8")
            unicode_directory.mkdir()
        except FileExistsError:
            pytest.skip("filesystem treats Unicode names as equivalent")
        (unicode_directory / "child.txt").write_text("child", encoding="utf-8")
        service = bootstrap.runtime_for(session).services.export_service
        archive = tmp_path / "unicode-names.assetbackup.zip"
        service.create_backup(session.root, archive)

        result = service.validate_backup(archive)

        assert result.valid
        assert result.file_count >= 3
    finally:
        bootstrap.library_service.close()


@pytest.mark.parametrize("member_name", ["data/a?b", "data/a<b", "data/a\x01b"])
def test_safe_backup_path_rejects_windows_forbidden_characters(member_name):
    assert not LibraryExportService._is_safe_backup_path(member_name)


def test_validate_backup_rejects_file_directory_prefix_collision(tmp_path):
    bootstrap, session = _open_session(tmp_path)
    try:
        (session.data_dir / "favorites.json").write_text("[]", encoding="utf-8")
        service = bootstrap.runtime_for(session).services.export_service
        source = tmp_path / "source.assetbackup.zip"
        service.create_backup(session.root, source)
        conflict = tmp_path / "file-directory-conflict.assetbackup.zip"
        node_bytes = b"node-file"
        child_bytes = b"child-file"
        with zipfile.ZipFile(source) as source_archive:
            manifest = json.loads(source_archive.read("manifest.json"))
            manifest["files"].extend(
                [
                    {
                        "path": "data/node",
                        "size": len(node_bytes),
                        "sha256": hashlib.sha256(node_bytes).hexdigest(),
                    },
                    {
                        "path": "data/node/child.txt",
                        "size": len(child_bytes),
                        "sha256": hashlib.sha256(child_bytes).hexdigest(),
                    },
                ]
            )
            with zipfile.ZipFile(conflict, "w") as target:
                for info in source_archive.infolist():
                    if info.filename != "manifest.json":
                        target.writestr(info, source_archive.read(info))
                target.writestr("data/node", node_bytes)
                target.writestr("data/node/child.txt", child_bytes)
                target.writestr("manifest.json", json.dumps(manifest))

        result = service.validate_backup(conflict)

        assert not result.valid
        assert any(
            "file path conflicts with a directory prefix" in error
            for error in result.errors
        )
    finally:
        bootstrap.library_service.close()


def test_archive_member_read_enforces_actual_bytes_not_only_zipinfo():
    info = zipfile.ZipInfo("data/file.bin")
    info.file_size = 1

    class DeclaredTooSmallArchive:
        @staticmethod
        def open(_info, mode="r"):
            assert mode == "r"
            return io.BytesIO(b"ab")

    with pytest.raises(ValueError, match="declared or configured size"):
        LibraryExportService._inspect_archive_member(
            DeclaredTooSmallArchive(), info, maximum_size=10
        )


def test_create_backup_skips_quick_check_for_oversized_database(tmp_path, monkeypatch):
    bootstrap, session = _open_session(tmp_path)
    try:
        service = bootstrap.runtime_for(session).services.export_service
        destination = tmp_path / "oversized-db.assetbackup.zip"
        monkeypatch.setattr(service, "_MAX_DATABASE_QUICK_CHECK_SIZE", 1)

        service.create_backup(session.root, destination)
        assert destination.exists()

        result = service.validate_backup(destination)
        assert result.valid
        assert result.database_quick_check == "skipped"
    finally:
        bootstrap.library_service.close()


def test_validate_backup_bounds_database_quick_check_staging_size(tmp_path, monkeypatch):
    bootstrap, session = _open_session(tmp_path)
    try:
        service = bootstrap.runtime_for(session).services.export_service
        archive = tmp_path / "db-cap.assetbackup.zip"
        service.create_backup(session.root, archive)
        monkeypatch.setattr(service, "_MAX_DATABASE_QUICK_CHECK_SIZE", 1)

        result = service.validate_backup(archive)

        assert result.valid
        assert result.database_quick_check == "skipped"
    finally:
        bootstrap.library_service.close()


@pytest.mark.parametrize(
    "member_name",
    [
        "data/file.txt:stream",
        "data/CON",
        "data/con.txt",
        "data/LPT1.log",
        "data/trailing.",
        "data/trailing ",
    ],
)
def test_backup_paths_reject_windows_special_semantics(member_name):
    assert not LibraryExportService._is_safe_backup_path(member_name)


def test_quarantine_rejects_canonical_escape_without_symlink_privileges(
    tmp_path, monkeypatch
):
    runtime_root = tmp_path / "RuntimeData"
    data_dir = runtime_root / "library-data"
    data_dir.mkdir(parents=True)
    quarantine = runtime_root / "_orphaned" / "restore-backups"
    outside = tmp_path / "outside" / "restore-backups"
    real_resolve = Path.resolve

    def escaping_resolve(path, strict=False):
        if path == quarantine:
            outside.parent.mkdir(parents=True, exist_ok=True)
            outside.mkdir(exist_ok=True)
            return outside
        return real_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", escaping_resolve)

    with pytest.raises(ValueError, match="escapes RuntimeData"):
        LibraryExportService._safe_restore_quarantine_root(data_dir)


def test_quarantine_write_rejects_simulated_junction_and_preserves_source(
    tmp_path, monkeypatch
):
    runtime_root = tmp_path / "RuntimeData"
    data_dir = runtime_root / "library-data"
    staging = runtime_root / ".library-data.restore-test"
    data_dir.mkdir(parents=True)
    staging.mkdir()
    quarantine = runtime_root / "_orphaned" / "restore-backups"
    quarantine.mkdir(parents=True)
    real_check = LibraryExportService._is_link_or_junction

    monkeypatch.setattr(
        export_io_module,
        "is_link_or_junction",
        lambda path: path == quarantine or real_check(path),
    )
    monkeypatch.setattr(export_module, "library_data_dir", lambda _root: data_dir)

    with pytest.raises(ValueError, match="not a real directory"):
        LibraryExportService._move_to_restore_quarantine(
            staging, tmp_path / "library", "failed-staging"
        )
    assert staging.is_dir()


def test_unsafe_restore_failure_blocks_new_admission_until_acknowledged(
    tmp_path, monkeypatch
):
    bootstrap, session = _open_session(tmp_path)
    try:
        service = bootstrap.runtime_for(session).services.export_service
        archive = tmp_path / "restore-state.assetbackup.zip"
        service.create_backup(session.root, archive)
        bootstrap.library_service.close_session(session)

        def fail_extract(_archive, destination, _entries):
            (destination / "partial.txt").write_text("partial", encoding="utf-8")
            raise RuntimeError("primary staging failure")

        def fail_quarantine(*_args, **_kwargs):
            raise OSError("quarantine unavailable")

        monkeypatch.setattr(service, "_extract_validated_backup", fail_extract)
        monkeypatch.setattr(service, "_move_to_restore_quarantine", fail_quarantine)
        with pytest.raises(RuntimeError, match="primary staging failure") as caught:
            service.restore_backup(archive, session.root, overwrite_existing=True)

        state = service.restore_failure_state
        assert state is not None
        assert caught.value.restore_admission_blocked is True
        assert caught.value.restore_recovery_required is True
        assert caught.value.restore_failure_state is not None
        assert state.token is not None

        def coordinator_must_not_run(*_args, **_kwargs):
            raise AssertionError("coordinator admission must remain blocked")

        monkeypatch.setattr(service, "_restore_coordinator", coordinator_must_not_run)
        with pytest.raises(export_module.RestoreAdmissionBlockedError) as blocked:
            service.restore_backup(archive, session.root, overwrite_existing=True)
        assert blocked.value.restore_failure_state == state
        acknowledged = service.acknowledge_restore_failure(state.token)
        assert acknowledged is not None
    finally:
        bootstrap.library_service.close()



def test_restore_rejects_unsafe_staging_descendant_before_install(
    tmp_path, monkeypatch
):
    bootstrap, session = _open_session(tmp_path)
    try:
        nested = session.data_dir / "nested"
        nested.mkdir()
        marker = nested / "marker.txt"
        marker.write_text("before", encoding="utf-8")
        service = bootstrap.runtime_for(session).services.export_service
        archive = tmp_path / "staging-descendant.assetbackup.zip"
        service.create_backup(session.root, archive)
        marker.write_text("existing", encoding="utf-8")
        bootstrap.library_service.close_session(session)

        staging_path: Path | None = None
        unsafe_path: Path | None = None
        validation_armed = False
        real_is_link_or_junction = service._is_link_or_junction

        def simulated_link_or_junction(path: Path) -> bool:
            if validation_armed and path == unsafe_path:
                return True
            return real_is_link_or_junction(path)

        monkeypatch.setattr(
            export_io_module,
            "is_link_or_junction",
            simulated_link_or_junction,
        )
        original_extract = service._extract_validated_backup

        def extract_then_arm(archive_file, destination, entries):
            nonlocal staging_path, unsafe_path, validation_armed
            original_extract(archive_file, destination, entries)
            staging_path = destination
            unsafe_path = destination / "nested"
            validation_armed = True

        monkeypatch.setattr(service, "_extract_validated_backup", extract_then_arm)
        install_attempts: list[tuple[Path, Path]] = []
        original_replace = Path.replace

        def record_install_attempt(path: Path, target: Path):
            if path == staging_path and target == session.data_dir:
                install_attempts.append((path, target))
            return original_replace(path, target)

        monkeypatch.setattr(Path, "replace", record_install_attempt)

        with pytest.raises(ValueError, match="link or junction") as caught:
            service.restore_backup(archive, session.root, overwrite_existing=True)

        assert install_attempts == []
        assert marker.read_text(encoding="utf-8") == "existing"
        assert caught.value.restore_poison is True
        assert caught.value.restore_recovery_required is True
        assert service.restore_failure_state is not None
    finally:
        bootstrap.library_service.close()



def test_restore_rechecks_failure_state_after_queued_coordinator_admission(tmp_path):
    bootstrap, session = _open_session(tmp_path)
    try:
        service = bootstrap.runtime_for(session).services.export_service
        archive = tmp_path / "queued-state.assetbackup.zip"
        service.create_backup(session.root, archive)
        bootstrap.library_service.close_session(session)
        state = export_module.RestoreFailureState(
            phase="earlier restore", message="RuntimeData needs review"
        )

        @contextmanager
        def coordinator(_session, _root):
            with service._restore_state_lock:
                service._restore_failure_state = state
            yield

        service._restore_coordinator = coordinator

        with pytest.raises(export_module.RestoreAdmissionBlockedError) as caught:
            service.restore_backup(archive, session.root, overwrite_existing=True)
        assert caught.value.restore_failure_state == state
    finally:
        bootstrap.library_service.close()



def test_iter_backup_files_uses_canonical_containment_without_symlink_privileges(
    tmp_path, monkeypatch
):
    data_dir = tmp_path / "RuntimeData" / "library-data"
    nested = data_dir / "nested"
    nested.mkdir(parents=True)
    safe = nested / "safe.txt"
    escaping = nested / "escaping.txt"
    safe.write_text("safe", encoding="utf-8")
    escaping.write_text("escape", encoding="utf-8")
    outside = tmp_path / "outside" / "escaping.txt"
    outside.parent.mkdir()
    real_resolve = Path.resolve

    def simulated_resolve(path, strict=False):
        if path == escaping:
            return outside
        return real_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", simulated_resolve)
    monkeypatch.setattr(Path, "rglob", lambda *_args, **_kwargs: pytest.fail("rglob must not be used"))

    with pytest.raises(ValueError, match="escapes RuntimeData"):
        list(LibraryExportService._iter_backup_files(data_dir, include_thumbnails=False))


def test_iter_backup_files_rejects_simulated_junction_before_traversal(tmp_path, monkeypatch):
    data_dir = tmp_path / "RuntimeData" / "library-data"
    junction = data_dir / "external-junction"
    junction.mkdir(parents=True)
    (junction / "secret.txt").write_text("secret", encoding="utf-8")
    monkeypatch.setattr(
        LibraryExportService,
        "_is_link_or_junction",
        staticmethod(lambda path: path == junction),
    )

    with pytest.raises(ValueError, match="link or junction"):
        list(LibraryExportService._iter_backup_files(data_dir, include_thumbnails=False))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction test")
def test_iter_backup_files_rejects_real_windows_junction(tmp_path):
    data_dir = tmp_path / "RuntimeData" / "library-data"
    outside = tmp_path / "outside"
    data_dir.mkdir(parents=True)
    outside.mkdir()
    junction = data_dir / "junction"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        text=True,
        # cmd.exe emits OEM-codepage text (e.g. GBK on a Chinese locale);
        # decoding it strictly as UTF-8 can raise UnicodeDecodeError in
        # subprocess's reader thread. The output is only used for a skip
        # message, so replace undecodable bytes instead of failing.
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        pytest.skip(f"directory junctions unavailable: {result.stderr or result.stdout}")
    (outside / "secret.txt").write_text("secret", encoding="utf-8")

    with pytest.raises(ValueError, match="link or junction"):
        list(LibraryExportService._iter_backup_files(data_dir, include_thumbnails=False))


def test_list_restore_quarantine_rejects_simulated_ancestor_junction(tmp_path, monkeypatch):
    bootstrap, session = _open_session(tmp_path)
    try:
        service = bootstrap.runtime_for(session).services.export_service
        bootstrap.library_service.close_session(session)
        runtime_root = tmp_path / "RuntimeData"
        data_dir = runtime_root / "library-data"
        orphaned = runtime_root / "_orphaned"
        quarantine = orphaned / "restore-backups"
        quarantine.mkdir(parents=True)
        monkeypatch.setattr(export_module, "library_data_dir", lambda _root: data_dir)
        monkeypatch.setattr(export_module, "library_lock_path", lambda _root: tmp_path / "library.lock")
        monkeypatch.setattr(
            export_io_module,
            "is_link_or_junction",
            lambda path: path == orphaned,
        )

        with pytest.raises(ValueError, match="not a real directory"):
            service.list_restore_quarantine(session.root)
    finally:
        bootstrap.library_service.close()


def test_validate_backup_rejects_duplicate_archive_zipinfo(tmp_path):
    bootstrap, session = _open_session(tmp_path)
    try:
        service = bootstrap.runtime_for(session).services.export_service
        source = tmp_path / "source.assetbackup.zip"
        duplicate = tmp_path / "duplicate-zipinfo.assetbackup.zip"
        service.create_backup(session.root, source)
        with zipfile.ZipFile(source) as source_archive, zipfile.ZipFile(duplicate, "w") as target:
            for info in source_archive.infolist():
                target.writestr(info, source_archive.read(info))
                if info.filename == "data/assetmanager.db":
                    target.writestr(info, source_archive.read(info))

        result = service.validate_backup(duplicate)
        assert not result.valid
        assert any("duplicate member name" in error for error in result.errors)
    finally:
        bootstrap.library_service.close()


def test_create_backup_stores_highly_compressible_members_under_ratio_cap(
    tmp_path, monkeypatch
):
    bootstrap, session = _open_session(tmp_path)
    try:
        payload = session.data_dir / "repetitive.bin"
        payload.write_bytes(b"A" * 4096)
        service = bootstrap.runtime_for(session).services.export_service
        monkeypatch.setattr(service, "_MAX_COMPRESSION_RATIO", 2)
        archive = tmp_path / "ratio-safe.assetbackup.zip"

        service.create_backup(session.root, archive)

        assert service.validate_backup(archive).valid
        with zipfile.ZipFile(archive) as source:
            info = source.getinfo("data/repetitive.bin")
            assert info.compress_type == zipfile.ZIP_STORED
            assert info.file_size == 4096
            assert info.compress_size == 4096
    finally:
        bootstrap.library_service.close()


def test_create_and_validate_backup_count_manifest_toward_small_limits(
    tmp_path, monkeypatch
):
    bootstrap, session = _open_session(tmp_path)
    try:
        service = bootstrap.runtime_for(session).services.export_service
        monkeypatch.setattr(service, "_utc_timestamp", lambda: "2026-08-04T00:00:00Z")
        baseline = tmp_path / "baseline.assetbackup.zip"
        service.create_backup(session.root, baseline)
        with zipfile.ZipFile(baseline) as archive:
            manifest_size = len(archive.read("manifest.json"))
            data_size = sum(
                info.file_size
                for info in archive.infolist()
                if info.filename != "manifest.json"
            )

        monkeypatch.setattr(service, "_MAX_MANIFEST_SIZE", manifest_size)
        monkeypatch.setattr(service, "_MAX_EXPANDED_SIZE", data_size + manifest_size)
        boundary = tmp_path / "boundary.assetbackup.zip"
        service.create_backup(session.root, boundary)
        assert service.validate_backup(boundary).valid

        monkeypatch.setattr(service, "_MAX_MANIFEST_SIZE", manifest_size - 1)
        with pytest.raises(ValueError, match="manifest exceeds configured limit"):
            service.create_backup(session.root, tmp_path / "manifest-over.assetbackup.zip")

        monkeypatch.setattr(service, "_MAX_MANIFEST_SIZE", manifest_size)
        monkeypatch.setattr(service, "_MAX_EXPANDED_SIZE", data_size + manifest_size - 1)
        with pytest.raises(ValueError, match="expanded size exceeds configured limit"):
            service.create_backup(session.root, tmp_path / "expanded-over.assetbackup.zip")

        result = service.validate_backup(boundary)
        assert not result.valid
        assert any("expanded size exceeds limit" in error for error in result.errors)
    finally:
        bootstrap.library_service.close()


def test_validate_backup_does_not_read_members_after_declared_expansion_overflow(
    tmp_path, monkeypatch
):
    bootstrap, session = _open_session(tmp_path)
    try:
        service = bootstrap.runtime_for(session).services.export_service
        archive_path = tmp_path / "expanded-limit.assetbackup.zip"
        service.create_backup(session.root, archive_path)
        monkeypatch.setattr(service, "_MAX_EXPANDED_SIZE", 1)
        opened = []
        original_open = zipfile.ZipFile.open

        def spy_open(archive, member, mode="r", pwd=None, *, force_zip64=False):
            info = member if isinstance(member, zipfile.ZipInfo) else archive.getinfo(member)
            opened.append(info.filename)
            return original_open(archive, member, mode=mode, pwd=pwd, force_zip64=force_zip64)

        monkeypatch.setattr(zipfile.ZipFile, "open", spy_open)
        result = service.validate_backup(archive_path)

        assert not result.valid
        assert opened == ["manifest.json"]
        assert any("expanded size exceeds limit" in error for error in result.errors)
    finally:
        bootstrap.library_service.close()


@pytest.mark.parametrize("fatal_kind", ["duplicate", "member-size", "ratio"])
def test_validate_backup_member_structure_fails_before_any_member_open(
    tmp_path, monkeypatch, fatal_kind
):
    bootstrap, session = _open_session(tmp_path)
    try:
        service = bootstrap.runtime_for(session).services.export_service
        archive_path = tmp_path / f"fatal-{fatal_kind}.zip"
        service.create_backup(session.root, archive_path)
        original_infolist = zipfile.ZipFile.infolist
        with zipfile.ZipFile(archive_path) as archive:
            infos = original_infolist(archive)
        data_info = next(info for info in infos if info.filename == "data/assetmanager.db")
        if fatal_kind == "duplicate":
            infos = infos + [data_info]
        elif fatal_kind == "member-size":
            data_info.file_size = service._MAX_MEMBER_SIZE + 1
            infos = [data_info if info.filename == data_info.filename else info for info in infos]
        else:
            data_info.file_size = 1001
            data_info.compress_size = 1
            infos = [data_info if info.filename == data_info.filename else info for info in infos]
        monkeypatch.setattr(zipfile.ZipFile, "infolist", lambda _archive: infos)
        opened = []
        monkeypatch.setattr(
            zipfile.ZipFile,
            "open",
            lambda *args, **kwargs: opened.append(args[1] if len(args) > 1 else None),
        )
        result = service.validate_backup(archive_path)
        assert not result.valid
        assert opened == []
    finally:
        bootstrap.library_service.close()


def test_validate_backup_central_directory_member_count_is_rejected_before_zipfile(
    tmp_path, monkeypatch
):
    bootstrap, session = _open_session(tmp_path)
    try:
        service = bootstrap.runtime_for(session).services.export_service
        archive_path = tmp_path / "central-directory-limit.zip"
        # The class-level cap is patched so the test stays fast; the preflight
        # reads the class attribute, not an instance override.
        monkeypatch.setattr(
            export_module.LibraryExportService, "_MAX_ARCHIVE_MEMBERS", 10
        )
        with zipfile.ZipFile(archive_path, "w") as archive:
            for index in range(11):
                archive.writestr(f"data/f{index}.txt", b"")
        constructed = []
        original_zipfile = zipfile.ZipFile

        class TrackingZipFile(original_zipfile):
            def __init__(self, *args, **kwargs):
                constructed.append(True)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(zipfile, "ZipFile", TrackingZipFile)
        result = service.validate_backup(archive_path)
        assert not result.valid
        assert constructed == []
        assert any("member count exceeds" in error.lower() for error in result.errors)
    finally:
        bootstrap.library_service.close()


def test_backup_limit_constants_cover_large_libraries():
    # Contract: large libraries (multi-GB video/model assets, extensive
    # thumbnail caches) must remain backupable. The hard caps only guard
    # against absurd archives and runaway member sizes.
    assert LibraryExportService._MAX_MEMBER_SIZE == 64 * 1024**3
    assert LibraryExportService._MAX_EXPANDED_SIZE == 512 * 1024**3
    assert LibraryExportService._MAX_ARCHIVE_MEMBERS == 100_000
    assert LibraryExportService._MAX_MANIFEST_FILES == 99_999
    assert (
        LibraryExportService._MAX_MANIFEST_FILES
        == LibraryExportService._MAX_ARCHIVE_MEMBERS - 1
    )



def test_validate_backup_manifest_fatal_opens_manifest_only(tmp_path, monkeypatch):
    bootstrap, session = _open_session(tmp_path)
    try:
        service = bootstrap.runtime_for(session).services.export_service
        source = tmp_path / "source.assetbackup.zip"
        service.create_backup(session.root, source)
        rewritten = tmp_path / "rewritten.assetbackup.zip"
        with zipfile.ZipFile(source, "r") as original:
            manifest = json.loads(original.read("manifest.json"))
            manifest["files"][0]["sha256"] = "not-a-digest"
            with zipfile.ZipFile(rewritten, "w") as output:
                for info in original.infolist():
                    payload = (
                        json.dumps(manifest).encode("utf-8")
                        if info.filename == "manifest.json"
                        else original.read(info)
                    )
                    output.writestr(info, payload)

        opened = []
        real_open = zipfile.ZipFile.open

        def tracked_open(archive, member, *args, **kwargs):
            opened.append(member.filename if isinstance(member, zipfile.ZipInfo) else member)
            return real_open(archive, member, *args, **kwargs)

        monkeypatch.setattr(zipfile.ZipFile, "open", tracked_open)
        result = service.validate_backup(rewritten)
        assert not result.valid
        assert opened == ["manifest.json"]
    finally:
        bootstrap.library_service.close()

def test_restore_callbacks_compare_and_delete_global_state_before_local_clear(tmp_path):
    calls = []
    external = {"generation": 7, "token": "canonical-token", "phase": "install", "message": "bad", "secondary_errors": ()}
    def provider(_root):
        return external

    def acknowledger(root, token):
        calls.append((root, token))
        if token != external["token"]:
            return external
        previous = dict(external)
        external.clear()
        return previous

    session = type("Session", (), {"root": tmp_path / "library"})()
    session.root.mkdir()
    service = LibraryExportService(
        connection_provider=lambda _root: None,
        session=session,
        restore_state_provider=provider,
        restore_acknowledger=acknowledger,
    )
    with service._restore_state_lock:
        service._restore_failure_state = export_module.RestoreFailureState(
            phase="local", message="stale", token="canonical-token"
        )
    # Default ACK is local-only and cannot clear process-global state.
    assert service.acknowledge_restore_failure().token == "canonical-token"
    assert calls == []
    assert service.restore_failure_state is not None
    # An explicit canonical token is the only global confirmation.
    assert service.acknowledge_restore_failure("canonical-token").token == "canonical-token"
    assert calls == [(session.root, "canonical-token")]
    assert service.restore_failure_state is None


def test_restore_state_callback_uses_local_token_and_does_not_clear_stale_global(
    tmp_path,
):
    root = tmp_path / "library"
    root.mkdir()
    external = {"generation": 7, "token": "canonical-token", "phase": "install", "message": "bad", "secondary_errors": ()}
    calls = []

    def acknowledger(_root, token):
        calls.append(token)
        return external

    service = LibraryExportService(
        connection_provider=lambda _root: None,
        session=type("Session", (), {"root": root})(),
        restore_state_provider=lambda _root: external,
        restore_acknowledger=acknowledger,
    )
    with service._restore_state_lock:
        service._restore_failure_state = export_module.RestoreFailureState(
            phase="local", message="stale", token="stale-token"
        )
    state = service.acknowledge_restore_failure()
    assert calls == []
    assert state is not None
    assert service.restore_failure_state is not None
    state = service.acknowledge_restore_failure("stale-token")
    assert calls == ["stale-token"]
    assert state is not None
    assert service.restore_failure_state is not None



def test_restore_admission_preflight_failure_does_not_poison_canonical_state(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    data_dir = root / "RuntimeData" / "library-data"
    data_dir.mkdir(parents=True)
    session = type("Session", (), {"root": root})()
    called = []

    @contextmanager
    def coordinator(_session, _root):
        called.append(True)
        yield

    service = LibraryExportService(
        connection_provider=lambda _root: None,
        session=session,
        restore_coordinator=coordinator,
        restore_state_provider=lambda _root: None,
        restore_acknowledger=lambda _root, _token: None,
    )
    with pytest.raises((FileNotFoundError, ValueError)):
        service.restore_backup(tmp_path / "missing.assetbackup.zip", root)
    assert called == []
    assert service.restore_failure_state is None

def test_build_metadata_export_rejects_managed_foreign_root_provider(tmp_path):
    from AssetsManager.core.database import DatabaseManager

    bootstrap, session = _open_session(tmp_path)
    foreign_root = tmp_path / "foreign-library"
    foreign_root.mkdir()
    manager = DatabaseManager()
    try:
        foreign_connection = manager.connection_for(foreign_root)
        with pytest.raises(ValueError, match="does not belong to the LibrarySession"):
            LibraryExportService(
                connection_provider=lambda _root: foreign_connection,
                session=session,
            )
    finally:
        manager.close()
        bootstrap.library_service.close()


def test_write_zip_file_reopens_path_after_rename_over(tmp_path, monkeypatch):
    data_dir = tmp_path / "RuntimeData" / "library-data"
    data_dir.mkdir(parents=True)
    source = data_dir / "changing.bin"
    source.write_bytes(b"placeholder")
    first = tmp_path / "first.bin"
    second = tmp_path / "second.bin"
    first.write_bytes(b"A" * 100)
    second.write_bytes(b"B" * 100)
    state = {"opens": 0}
    real_open = Path.open
    real_stat = Path.stat

    def unstable_open(path, mode="r"):
        if path == source:
            state["opens"] += 1
            return (first if state["opens"] == 1 else second).open("rb")
        return real_open(path, mode)

    def unstable_stat(path, *args, **kwargs):
        if path == source:
            # The path always names the replacement inode: the first attempt
            # (which read the old handle) must be detected as a rename-over.
            return second.stat()
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", unstable_open)
    monkeypatch.setattr(Path, "stat", unstable_stat)
    service = LibraryExportService(connection_provider=lambda _root: None)

    out = tmp_path / "out.zip"
    with zipfile.ZipFile(out, "w") as archive:
        entry = service._write_zip_file(
            archive, source, "data/changing.bin", containment_root=data_dir
        )

    assert entry is not None
    assert entry["size"] == 100
    assert entry["sha256"] == hashlib.sha256(b"B" * 100).hexdigest()
    with zipfile.ZipFile(out) as archive:
        assert archive.read("data/changing.bin") == b"B" * 100
    assert state["opens"] == 2


def test_write_zip_file_skips_continuously_changing_source(tmp_path, monkeypatch):
    data_dir = tmp_path / "RuntimeData" / "library-data"
    data_dir.mkdir(parents=True)
    source = data_dir / "churn.bin"
    source.write_bytes(b"placeholder")
    blobs = []
    for payload in (b"A" * 64, b"B" * 64, b"C" * 64, b"D" * 64):
        blob = tmp_path / f"blob{len(blobs)}.bin"
        blob.write_bytes(payload)
        blobs.append(blob)
    state = {"opens": 0}
    real_open = Path.open
    real_stat = Path.stat

    def unstable_open(path, mode="r"):
        if path == source:
            index = state["opens"]
            state["opens"] += 1
            return blobs[min(index, len(blobs) - 1)].open("rb")
        return real_open(path, mode)

    def unstable_stat(path, *args, **kwargs):
        if path == source:
            # Never matches the handle currently open: the path keeps moving.
            return blobs[state["opens"] % len(blobs)].stat()
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", unstable_open)
    monkeypatch.setattr(Path, "stat", unstable_stat)
    service = LibraryExportService(connection_provider=lambda _root: None)

    warnings: list[str] = []
    out = tmp_path / "out.zip"
    with zipfile.ZipFile(out, "w") as archive:
        entry = service._write_zip_file(
            archive,
            source,
            "data/churn.bin",
            containment_root=data_dir,
            warnings=warnings,
        )

    assert entry is None
    assert warnings == [
        "Backup source kept changing while reading; skipped: data/churn.bin"
    ]
    with zipfile.ZipFile(out) as archive:
        assert "data/churn.bin" not in archive.namelist()
    assert state["opens"] == 3

    # Without a warnings sink the unstable member still aborts the backup.
    with zipfile.ZipFile(tmp_path / "abort.zip", "w") as archive:
        with pytest.raises(ValueError, match="changed while reading"):
            service._write_zip_file(
                archive, source, "data/churn.bin", containment_root=data_dir
            )


def test_create_backup_skips_unstable_file_and_reports_warning(tmp_path, monkeypatch):
    bootstrap, session = _open_session(tmp_path)
    try:
        (session.data_dir / "favorites.json").write_text("[]", encoding="utf-8")
        churn = session.data_dir / "churn.bin"
        churn.write_bytes(b"x")
        blobs = []
        for payload in (b"A" * 64, b"B" * 64, b"C" * 64, b"D" * 64):
            blob = tmp_path / f"e2e-blob{len(blobs)}.bin"
            blob.write_bytes(payload)
            blobs.append(blob)
        state = {"opens": 0}
        real_open = Path.open
        real_stat = Path.stat

        def unstable_open(path, mode="r", *args, **kwargs):
            if path == churn:
                index = state["opens"]
                state["opens"] += 1
                return blobs[min(index, len(blobs) - 1)].open("rb")
            return real_open(path, mode, *args, **kwargs)

        def unstable_stat(path, *args, **kwargs):
            if path == churn:
                return blobs[state["opens"] % len(blobs)].stat()
            return real_stat(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", unstable_open)
        monkeypatch.setattr(Path, "stat", unstable_stat)
        service = bootstrap.runtime_for(session).services.export_service
        destination = tmp_path / "churn.assetbackup.zip"

        result = service.create_backup(session.root, destination)

        assert len(result.warnings) == 1
        assert "skipped" in result.warnings[0]
        assert result.file_count == 2  # snapshot database + favorites.json
        with zipfile.ZipFile(destination) as archive:
            assert "data/churn.bin" not in archive.namelist()
        assert service.validate_backup(destination).valid
    finally:
        bootstrap.library_service.close()


def test_create_backup_checks_cancel_during_post_write_validation(
    tmp_path, monkeypatch
):
    bootstrap, session = _open_session(tmp_path)
    try:
        (session.data_dir / "favorites.json").write_text("[]", encoding="utf-8")
        service = bootstrap.runtime_for(session).services.export_service
        destination = tmp_path / "cancel-validation.assetbackup.zip"
        armed = {"value": False}
        original_validate = service.validate_backup

        def arm_during_validation(archive_path, **kwargs):
            armed["value"] = True
            return original_validate(archive_path, **kwargs)

        monkeypatch.setattr(service, "validate_backup", arm_during_validation)

        with pytest.raises(RuntimeError, match="Backup cancelled"):
            service.create_backup(
                session.root,
                destination,
                should_cancel=lambda: armed["value"],
            )
        assert not destination.exists()
        assert not list(destination.parent.glob(f".{destination.name}.*.tmp"))
    finally:
        bootstrap.library_service.close()


def test_inspect_archive_member_obeys_should_cancel():
    info = zipfile.ZipInfo("data/file.bin")
    info.file_size = 5

    class ChunkArchive:
        @staticmethod
        def open(_info, mode="r"):
            return io.BytesIO(b"x" * 5)

    with pytest.raises(RuntimeError, match="Backup cancelled"):
        LibraryExportService._inspect_archive_member(
            ChunkArchive(), info, maximum_size=10, should_cancel=lambda: True
        )


def test_create_backup_does_not_hold_db_write_lock_during_snapshot(
    tmp_path, monkeypatch
):
    bootstrap, session = _open_session(tmp_path)
    try:
        service = bootstrap.runtime_for(session).services.export_service
        destination = tmp_path / "unlocked.assetbackup.zip"
        real_connect = export_module.sqlite3.connect
        in_snapshot = threading.Event()
        release_snapshot = threading.Event()
        snapshot_uris = []

        class TrackingSnapshotConnection:
            """Minimal wrapper around the read-only snapshot connection.

            ``sqlite3.Connection`` is immutable on Python 3.14, so the page
            copy is intercepted by wrapping the connection returned from
            ``sqlite3.connect`` instead of patching the method.
            """

            def __init__(self, real):
                self._real = real

            def backup(self, target):
                in_snapshot.set()
                assert release_snapshot.wait(5)
                return self._real.backup(target)

            def close(self):
                self._real.close()

        def tracked_connect(*args, **kwargs):
            conn = real_connect(*args, **kwargs)
            if kwargs.get("uri"):
                snapshot_uris.append(args[0])
                return TrackingSnapshotConnection(conn)
            return conn

        monkeypatch.setattr(export_module.sqlite3, "connect", tracked_connect)
        backup_errors = []

        def run_backup():
            try:
                service.create_backup(session.root, destination)
            except BaseException as exc:
                backup_errors.append(exc)

        backup_thread = threading.Thread(target=run_backup)
        backup_thread.start()
        assert in_snapshot.wait(5)
        try:
            assert snapshot_uris and "mode=ro" in snapshot_uris[0]
            conn = session.connection_for()
            # A writer using the cooperative db_write_lock must succeed while
            # the snapshot page copy is in flight; the backup must not hold
            # the lock for the whole snapshot.
            with export_module.db_write_lock(conn):
                conn.execute(
                    "INSERT INTO file_meta (file_path, notes) VALUES (?, ?)",
                    (str(session.root / "during.txt"), "written"),
                )
                conn.commit()
        finally:
            release_snapshot.set()
        backup_thread.join(5)

        assert not backup_thread.is_alive()
        assert backup_errors == []
        assert service.validate_backup(destination).valid
        conn = session.connection_for()
        assert conn.execute(
            "SELECT notes FROM file_meta WHERE file_path=?",
            (str(session.root / "during.txt"),),
        ).fetchone() == ("written",)
    finally:
        bootstrap.library_service.close()
