"""Tests for AssetIndexService."""
import os

import pytest

from AssetsManager.application.asset_index_service import (
    AssetIndexPublishResult,
    AssetIndexPublishStatus,
    AssetIndexService,
    _BUSY_RETRY_LIMIT,
)
from AssetsManager.repositories.asset_index_repository import (
    AssetIndexRepository,
    AssetIndexRevisionConflict,
)


def test_index_directory_populates_assets_table(tmp_path, schema_db):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "photo.jpg").write_bytes(b"jpg")
    (lib / "readme.txt").write_text("txt")
    (lib / "sub").mkdir()

    conn = schema_db
    svc = AssetIndexService()
    count = svc.index_directory(conn, lib, lib)

    assert count == 3
    assert svc.count(conn, lib) == 3


def test_index_directory_skips_if_already_indexed(tmp_path, schema_db):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "file.txt").write_text("x")

    conn = schema_db
    svc = AssetIndexService()
    svc.index_directory(conn, lib, lib)

    count = svc.index_directory(conn, lib, lib, force=False)
    assert count == 1
    assert svc.count(conn, lib) == 1


def test_index_directory_force_reindexes(tmp_path, schema_db):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "file.txt").write_text("x")

    conn = schema_db
    svc = AssetIndexService()
    svc.index_directory(conn, lib, lib)
    (lib / "new.txt").write_text("y")
    count = svc.index_directory(conn, lib, lib, force=True)

    assert count == 2
    assert svc.count(conn, lib) == 2


def test_force_index_removes_stale_entries_from_parent(tmp_path, schema_db):
    lib = tmp_path / "lib"
    stale = lib / "stale.txt"
    lib.mkdir()
    stale.write_text("x")

    svc = AssetIndexService()
    svc.index_directory(schema_db, lib, lib)
    stale.unlink()

    svc.index_directory(schema_db, lib, lib, force=True)

    assert svc.get_entry(schema_db, stale) is None


def test_query_by_parent(tmp_path, schema_db):
    lib = tmp_path / "lib"
    sub = lib / "sub"
    sub.mkdir(parents=True)
    (lib / "a.txt").write_text("a")
    (sub / "b.txt").write_text("b")

    conn = schema_db
    svc = AssetIndexService()
    svc.index_directory(conn, lib, lib)
    svc.index_directory(conn, lib, sub)

    root_items = svc.query_by_parent(conn, lib, lib)
    sub_items = svc.query_by_parent(conn, lib, sub)

    assert len(root_items) == 2  # a.txt + sub/
    assert len(sub_items) == 1
    assert sub_items[0].name == "b.txt"


def test_query_by_extension(tmp_path, schema_db):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "a.jpg").write_bytes(b"a")
    (lib / "b.jpg").write_bytes(b"b")
    (lib / "c.txt").write_text("c")

    conn = schema_db
    svc = AssetIndexService()
    svc.index_directory(conn, lib, lib)

    jpgs = svc.query_by_extension(conn, lib, ".jpg")
    assert len(jpgs) == 2


def test_search_by_name(tmp_path, schema_db):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "hero_idle.png").write_bytes(b"a")
    (lib / "hero_attack.png").write_bytes(b"b")
    (lib / "villain_idle.png").write_bytes(b"c")

    conn = schema_db
    svc = AssetIndexService()
    svc.index_directory(conn, lib, lib)

    results = svc.search_by_name(conn, lib, "hero")
    assert len(results) == 2


def test_remove_entry(tmp_path, schema_db):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "file.txt").write_text("x")

    conn = schema_db
    svc = AssetIndexService()
    svc.index_directory(conn, lib, lib)
    assert svc.count(conn, lib) == 1

    svc.remove_entry(conn, lib, lib / "file.txt")
    assert svc.count(conn, lib) == 0


def test_remove_directory(tmp_path, schema_db):
    lib = tmp_path / "lib"
    sub = lib / "sub"
    sub.mkdir(parents=True)
    (sub / "a.txt").write_text("a")
    (sub / "b.txt").write_text("b")

    conn = schema_db
    svc = AssetIndexService()
    svc.index_directory(conn, lib, sub)

    removed = svc.remove_directory(conn, lib, sub)
    assert removed == 2
    assert svc.count(conn, lib) == 0


def test_get_entry(tmp_path, schema_db):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "photo.jpg").write_bytes(b"jpg")

    conn = schema_db
    svc = AssetIndexService()
    svc.index_directory(conn, lib, lib)

    entry = svc.get_entry(conn, lib / "photo.jpg")
    assert entry is not None
    assert entry.name == "photo.jpg"
    assert entry.extension == ".jpg"
    assert entry.kind == "file"

    assert svc.get_entry(conn, lib / "missing.txt") is None



def test_index_directory_skips_symlink_and_junction_entries(tmp_path, schema_db):
    lib = tmp_path / "lib"
    outside = tmp_path / "outside"
    lib.mkdir()
    outside.mkdir()
    (lib / "regular.txt").write_text("regular")
    (lib / "regular_dir").mkdir()
    outside_file = outside / "outside.txt"
    outside_file.write_text("outside")
    outside_dir = outside / "outside_dir"
    outside_dir.mkdir()

    try:
        os.symlink(outside_file, lib / "linked.txt")
        os.symlink(outside_dir, lib / "linked_dir", target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    svc = AssetIndexService()
    assert svc.index_directory(schema_db, lib, lib) == 2
    indexed = svc.query_by_parent(schema_db, lib, lib)

    assert {item.name for item in indexed} == {"regular.txt", "regular_dir"}
    assert svc.get_entry(schema_db, lib / "linked.txt") is None
    assert svc.get_entry(schema_db, lib / "linked_dir") is None


def test_asset_index_upsert_refreshes_scope_on_file_path_conflict(schema_db):
    repo = AssetIndexRepository(schema_db)
    file_path = "/library/file.txt"
    first = (file_path, "file.txt", ".txt", "file", 1, 1.0, "/library/old", "/library", 1.0, 1.0)
    second = (file_path, "file.txt", ".txt", "file", 2, 2.0, "/library/new", "/library", 2.0, 2.0)

    repo.replace_parent_entries("/library/old", "/library", [first], clear_existing=True)
    repo.replace_parent_entries("/library/new", "/library", [second], clear_existing=True)

    entry = repo.get_entry(file_path)
    assert entry is not None
    assert entry.parent_path == "/library/new"
    assert entry.library_root == "/library"
    assert entry.size == 2
    assert repo.query_by_parent("/library", "/library/old") == []
    assert [item.file_path for item in repo.query_by_parent("/library", "/library/new")] == [file_path]


def test_asset_index_delete_path_respects_subtree_boundary(schema_db):
    repo = AssetIndexRepository(schema_db, library_root="/library")
    entries = [
        ("/library/folder", "folder", "", "dir", 0, 1.0, "/library", "/library", 1.0, 1.0),
        ("/library/folder/child.txt", "child.txt", ".txt", "file", 1, 1.0, "/library/folder", "/library", 1.0, 1.0),
        ("/library/folder-copy/keep.txt", "keep.txt", ".txt", "file", 1, 1.0, "/library/folder-copy", "/library", 1.0, 1.0),
    ]
    repo.replace_parent_entries("/library", "/library", entries, clear_existing=True)

    assert repo.delete_path("/library/folder") == 2
    assert repo.get_entry("/library/folder") is None
    assert repo.get_entry("/library/folder/child.txt") is None
    assert repo.get_entry("/library/folder-copy/keep.txt") is not None


def test_raw_mode_delete_rejects_without_library_root(schema_db):
    repo = AssetIndexRepository(schema_db)
    with pytest.raises(ValueError, match="library_root"):
        repo.delete_entry("/library/file.txt")
    with pytest.raises(ValueError, match="library_root"):
        repo.delete_path("/library/folder")


def test_canonical_facades_for_one_session_share_refresh_lock(tmp_path):
    from AssetsManager.application import ApplicationBootstrap

    library = tmp_path / "library"
    library.mkdir()
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    try:
        first = AssetIndexService.for_session(session)
        second = AssetIndexService.for_session(session)
        assert first._refresh_lock is second._refresh_lock
    finally:
        bootstrap.library_service.close()


def test_canonical_facades_for_same_root_share_refresh_lock(tmp_path):
    from types import SimpleNamespace

    from AssetsManager.application.asset_index_service import _refresh_lock_for
    from AssetsManager.core.path_resolver import root_identity

    library = tmp_path / "library"
    identity = root_identity(library, strict=False)
    first = SimpleNamespace(context=SimpleNamespace(root_identity=identity))
    second = SimpleNamespace(context=SimpleNamespace(root_identity=identity))

    assert _refresh_lock_for(first) is _refresh_lock_for(second)


def test_canonical_session_facade_supports_index_query_search_and_remove(tmp_path):
    from AssetsManager.application import ApplicationBootstrap

    library = tmp_path / "library"
    library.mkdir()
    asset = library / "hero_idle.png"
    asset.write_bytes(b"hero")

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    service = AssetIndexService.for_session(session)

    assert service.session is session
    assert service.index_directory(library) == 1
    assert [entry.name for entry in service.query_by_parent(library)] == [asset.name]
    assert [entry.name for entry in service.query_by_extension(".png")] == [asset.name]
    assert [entry.name for entry in service.search_by_name("hero")] == [asset.name]

    service.remove_entry(asset)
    assert service.get_entry(asset) is None
    assert service.count() == 0



def test_bound_index_directory_preserves_caller_outer_transaction(tmp_path):
    from AssetsManager.application import ApplicationBootstrap

    library = tmp_path / "library"
    library.mkdir()
    asset = library / "asset.txt"
    asset.write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    try:
        service = AssetIndexService.for_session(session)
        conn = session.connection_for(library)
        conn.execute("CREATE TABLE caller_data (value TEXT NOT NULL)")
        conn.commit()
        conn.execute("BEGIN")
        conn.execute("INSERT INTO caller_data VALUES ('keep-me')")

        assert service.index_directory(library) == 1
        assert conn.in_transaction is True
        assert conn.execute("SELECT * FROM caller_data").fetchall() == [("keep-me",)]
        conn.rollback()
        assert service.count() == 0
    finally:
        bootstrap.library_service.close()


def test_index_directory_tree_removes_disappeared_descendants(tmp_path, schema_db):
    library = tmp_path / "library"
    old_dir = library / "old"
    old_dir.mkdir(parents=True)
    (old_dir / "stale.txt").write_text("stale", encoding="utf-8")

    service = AssetIndexService()
    repository = AssetIndexRepository(schema_db, library_root=library)
    service.index_directory_tree(schema_db, library, library)
    assert repository.get_entry(old_dir / "stale.txt") is not None
    first_revision = repository.current_revision(library)

    (old_dir / "stale.txt").unlink()
    old_dir.rmdir()
    service.index_directory_tree(schema_db, library, library)

    assert repository.current_revision(library) == first_revision + 1
    assert repository.get_entry(old_dir / "stale.txt") is None


def test_file_backed_two_connection_stale_scan_is_rejected(tmp_path, monkeypatch):
    import sqlite3
    import threading

    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate

    library = tmp_path / "library"
    library.mkdir()
    (library / "asset.txt").write_text("asset", encoding="utf-8")
    db_path = tmp_path / "asset-index.db"
    first_conn = sqlite3.connect(db_path, check_same_thread=False, timeout=5)
    second_conn = sqlite3.connect(db_path, check_same_thread=False, timeout=5)
    first_conn.executescript(database._SCHEMA)
    migrate(first_conn)
    first_conn.commit()

    service_a = AssetIndexService()
    service_b = AssetIndexService()
    original_scan = service_a._scan_directory_entries
    scan_ready = threading.Event()
    release_scan = threading.Event()
    result_a = []
    errors_a = []

    def delayed_scan(root, target, now):
        entries = original_scan(root, target, now)
        scan_ready.set()
        assert release_scan.wait(timeout=5)
        return entries

    monkeypatch.setattr(service_a, "_scan_directory_entries", delayed_scan)

    def run_a():
        try:
            result_a.append(
                service_a.index_directory(
                    first_conn, library, library, force=True
                )
            )
        except BaseException as exc:  # assertion below must observe worker errors
            errors_a.append(exc)

    thread = threading.Thread(target=run_a)
    thread.start()
    try:
        assert scan_ready.wait(timeout=5)
        assert service_b.index_directory(second_conn, library, library, force=True) == 1
        release_scan.set()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert not result_a
        assert len(errors_a) == 1
        assert isinstance(errors_a[0], AssetIndexRevisionConflict)
        assert first_conn.in_transaction is False

        repository = AssetIndexRepository(second_conn, library_root=library)
        assert repository.current_revision(library) == 1
        assert repository.count(str(library)) == 1
    finally:
        release_scan.set()
        thread.join(timeout=5)
        first_conn.close()
        second_conn.close()


def test_committed_result_is_visible_to_second_connection(tmp_path):
    import sqlite3

    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate

    library = tmp_path / "library"
    library.mkdir()
    (library / "asset.txt").write_text("asset", encoding="utf-8")
    db_path = tmp_path / "asset-index.db"
    first_conn = sqlite3.connect(db_path)
    second_conn = sqlite3.connect(db_path)
    first_conn.executescript(database._SCHEMA)
    migrate(first_conn)
    first_conn.commit()
    try:
        result = AssetIndexService().index_directory_result(
            first_conn, library, library, force=True
        )

        assert result.committed is True
        assert result.durable
        repository = AssetIndexRepository(second_conn, library_root=library)
        assert repository.current_revision(library) == result.revision
        assert repository.count(str(library)) == result.count
    finally:
        first_conn.close()
        second_conn.close()


def test_index_directory_result_distinguishes_empty_skipped_and_scan_failure(
    tmp_path, schema_db, monkeypatch
):
    library = tmp_path / "library"
    library.mkdir()
    service = AssetIndexService()

    empty = service.index_directory_result(schema_db, library, library, force=True)
    assert empty.status is AssetIndexPublishStatus.EMPTY
    assert empty.count == 0
    assert empty.committed is True
    assert empty.durable

    asset = library / "asset.txt"
    asset.write_text("asset", encoding="utf-8")
    published = service.index_directory_result(schema_db, library, library, force=True)
    assert published.status is AssetIndexPublishStatus.PUBLISHED
    assert published.count == 1
    assert published.committed is True
    assert published.durable

    skipped = service.index_directory_result(schema_db, library, library, force=False)
    assert skipped.status is AssetIndexPublishStatus.SKIPPED
    assert skipped.count == 1

    monkeypatch.setattr(service, "_scan_directory_entries", lambda *_args: None)
    failed = service.index_directory_result(schema_db, library, library, force=True)
    assert failed.status is AssetIndexPublishStatus.SCAN_FAILED
    assert failed.count == 0


def test_index_directory_result_returns_stale_without_raising(
    tmp_path, schema_db, monkeypatch
):
    library = tmp_path / "library"
    library.mkdir()
    (library / "asset.txt").write_text("asset", encoding="utf-8")
    service = AssetIndexService()
    repository = AssetIndexRepository(schema_db, library_root=library)
    original_scan = service._scan_directory_entries

    def scan_then_advance(root, target, now):
        entries = original_scan(root, target, now)
        repository.replace_parent_entries(
            str(library), str(library), [], clear_existing=True, commit=True
        )
        return entries

    monkeypatch.setattr(service, "_scan_directory_entries", scan_then_advance)
    result = service.index_directory_result(schema_db, library, library, force=True)

    assert result.status is AssetIndexPublishStatus.STALE
    assert result.stale
    assert result.failure is not None
    assert result.expected_revision == 0
    assert result.actual_revision == 1


def test_index_directory_result_retries_busy_publish(
    tmp_path, schema_db, monkeypatch
):
    import AssetsManager.application.asset_index_service as asset_index_module
    from sqlite3 import OperationalError

    library = tmp_path / "library"
    library.mkdir()
    (library / "asset.txt").write_text("asset", encoding="utf-8")
    service = AssetIndexService()
    original = AssetIndexRepository.replace_parent_entries
    attempts = 0
    delays = []

    def busy_twice_then_publish(self, *args, **kwargs):
        nonlocal attempts
        if attempts < 2:
            attempts += 1
            raise OperationalError("database is locked")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(AssetIndexRepository, "replace_parent_entries", busy_twice_then_publish)
    monkeypatch.setattr(asset_index_module.time, "sleep", delays.append)
    result = service.index_directory_result(schema_db, library, library, force=True)

    assert result.status is AssetIndexPublishStatus.PUBLISHED
    assert result.retry_count == 2
    assert attempts == 2
    assert delays == [0.01, 0.02]


def test_index_directory_result_reports_busy_after_bounded_retries(
    tmp_path, schema_db, monkeypatch
):
    import AssetsManager.application.asset_index_service as asset_index_module
    from sqlite3 import OperationalError

    library = tmp_path / "library"
    library.mkdir()
    (library / "asset.txt").write_text("asset", encoding="utf-8")
    service = AssetIndexService()

    def always_busy(*_args, **_kwargs):
        raise OperationalError("database is busy")

    monkeypatch.setattr(AssetIndexRepository, "replace_parent_entries", always_busy)
    monkeypatch.setattr(asset_index_module.time, "sleep", lambda _delay: None)
    result = service.index_directory_result(schema_db, library, library, force=True)

    assert result.status is AssetIndexPublishStatus.BUSY
    assert result.retry_count == _BUSY_RETRY_LIMIT
    assert isinstance(result.failure, OperationalError)

    with pytest.raises(OperationalError, match="database is busy"):
        service.index_directory(schema_db, library, library, force=True)


@pytest.mark.parametrize("read_method, force", [("count_by_parent", False), ("current_revision", True)])
def test_index_directory_result_retries_busy_preflight_reads(
    tmp_path, schema_db, monkeypatch, read_method, force
):
    import AssetsManager.application.asset_index_service as asset_index_module
    from sqlite3 import OperationalError

    library = tmp_path / "library"
    library.mkdir()
    (library / "asset.txt").write_text("asset", encoding="utf-8")
    service = AssetIndexService()
    original = getattr(AssetIndexRepository, read_method)
    attempts = 0
    delays = []

    def busy_once_then_read(self, *args, **kwargs):
        nonlocal attempts
        if attempts < 1:
            attempts += 1
            raise OperationalError("database is locked")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(AssetIndexRepository, read_method, busy_once_then_read)
    monkeypatch.setattr(asset_index_module.time, "sleep", delays.append)

    result = service.index_directory_result(
        schema_db, library, library, force=force
    )

    assert result.status is AssetIndexPublishStatus.PUBLISHED
    assert result.retry_count == 1
    assert attempts == 1
    assert delays == [0.01]


def test_legacy_index_wrapper_raises_for_status_without_failure(
    tmp_path, schema_db, monkeypatch
):
    library = tmp_path / "library"
    library.mkdir()
    service = AssetIndexService()

    monkeypatch.setattr(
        service,
        "index_directory_result",
        lambda *_args, **_kwargs: AssetIndexPublishResult(
            AssetIndexPublishStatus.STALE,
            expected_revision=4,
            actual_revision=5,
        ),
    )

    with pytest.raises(AssetIndexRevisionConflict, match="expected 4, found 5"):
        service.index_directory(schema_db, library, library, force=True)


def test_asset_index_publish_contract_is_exported_from_application_package():
    from AssetsManager.application import (
        AssetIndexPublishResult as ExportedResult,
        AssetIndexPublishStatus as ExportedStatus,
    )

    assert ExportedResult is AssetIndexPublishResult
    assert ExportedStatus is AssetIndexPublishStatus


def test_index_directory_result_marks_commit_false_as_staged(tmp_path, schema_db):
    library = tmp_path / "library"
    library.mkdir()
    (library / "asset.txt").write_text("asset", encoding="utf-8")
    service = AssetIndexService()

    result = service.index_directory_result(
        schema_db, library, library, force=True, commit=False
    )

    assert result.status is AssetIndexPublishStatus.PUBLISHED
    assert result.committed is False
    assert not result.durable
    assert result.degraded
    schema_db.rollback()
    repository = AssetIndexRepository(schema_db, library_root=library)
    assert repository.current_revision(library) == 0
    assert repository.count(str(library)) == 0


def test_bound_tree_result_marks_outer_transaction_as_staged(tmp_path):
    from AssetsManager.application import ApplicationBootstrap

    library = tmp_path / "library"
    library.mkdir()
    (library / "asset.txt").write_text("asset", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    try:
        runtime = bootstrap.runtime_for(session)
        service = runtime.services.asset_index_service
        # The reconciliation worker shares the session connection and can
        # hold a write transaction while the test opens its own; stop it so
        # the caller-owned outer transaction is the only one in flight.
        runtime.services.reconciliation_service.stop()
        conn = session.connection_for(library)
        conn.execute("BEGIN")

        result = service.index_directory_tree_result(library)

        assert result.status is AssetIndexPublishStatus.PUBLISHED
        assert result.committed is False
        assert not result.durable
        assert result.degraded
        conn.rollback()
        assert service.count() == 0
    finally:
        bootstrap.library_service.close()


def test_index_directory_rejects_stale_scan_before_publish(tmp_path, schema_db, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    (library / "asset.txt").write_text("asset", encoding="utf-8")

    service = AssetIndexService()
    repository = AssetIndexRepository(schema_db, library_root=library)
    original_scan = service._scan_directory_entries

    def scan_then_advance(root, target, now):
        entries = original_scan(root, target, now)
        repository.replace_parent_entries(
            str(library), str(library), [], clear_existing=True, commit=True
        )
        return entries

    monkeypatch.setattr(service, "_scan_directory_entries", scan_then_advance)
    with pytest.raises(AssetIndexRevisionConflict, match="expected 0, found 1"):
        service.index_directory(schema_db, library, library, force=True)

    assert repository.current_revision(library) == 1
    assert repository.count(str(library)) == 0


def test_index_directory_tree_rolls_back_all_parent_replacements_on_failure(tmp_path, schema_db, monkeypatch):
    from AssetsManager.repositories.asset_index_repository import AssetIndexRepository

    library = tmp_path / "library"
    first = library / "first"
    second = library / "second"
    first.mkdir(parents=True)
    second.mkdir()
    (first / "one.txt").write_text("one", encoding="utf-8")
    (second / "two.txt").write_text("two", encoding="utf-8")

    service = AssetIndexService()
    original = AssetIndexRepository.replace_parent_entries
    calls = 0

    def fail_on_second(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected index replacement failure")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(AssetIndexRepository, "replace_parent_entries", fail_on_second)
    with pytest.raises(RuntimeError, match="injected index replacement failure"):
        service.index_directory_tree(schema_db, library, library)

    assert schema_db.in_transaction is False
    assert schema_db.execute("SELECT COUNT(*) FROM assets").fetchone() == (0,)


def test_index_directory_tree_result_reports_empty_and_published(tmp_path, schema_db):
    library = tmp_path / "library"
    library.mkdir()
    service = AssetIndexService()

    empty = service.index_directory_tree_result(schema_db, library, library)
    assert empty.status is AssetIndexPublishStatus.EMPTY
    assert empty.count == 0

    (library / "asset.txt").write_text("asset", encoding="utf-8")
    published = service.index_directory_tree_result(schema_db, library, library)
    assert published.status is AssetIndexPublishStatus.PUBLISHED
    assert published.count == 1


def test_index_directory_tree_result_reports_scan_failure(tmp_path, schema_db, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    service = AssetIndexService()
    monkeypatch.setattr(service, "_scan_directory_entries", lambda *_args: None)

    result = service.index_directory_tree_result(schema_db, library, library)

    assert result.status is AssetIndexPublishStatus.SCAN_FAILED
    assert result.failure is None


def test_index_directory_tree_result_reports_stale_without_raising(
    tmp_path, schema_db, monkeypatch
):
    library = tmp_path / "library"
    library.mkdir()
    (library / "asset.txt").write_text("asset", encoding="utf-8")
    service = AssetIndexService()
    repository = AssetIndexRepository(schema_db, library_root=library)
    original_scan = service._scan_directory_entries

    def scan_then_advance(root, target, now):
        entries = original_scan(root, target, now)
        repository.replace_parent_entries(
            str(library), str(library), [], clear_existing=True, commit=True
        )
        return entries

    monkeypatch.setattr(service, "_scan_directory_entries", scan_then_advance)
    result = service.index_directory_tree_result(schema_db, library, library)

    assert result.status is AssetIndexPublishStatus.STALE
    assert result.expected_revision == 0
    assert result.actual_revision == 1


def test_index_directory_tree_result_reports_busy_preflight(
    tmp_path, schema_db, monkeypatch
):
    import AssetsManager.application.asset_index_service as asset_index_module
    from sqlite3 import OperationalError

    library = tmp_path / "library"
    library.mkdir()
    service = AssetIndexService()

    def always_busy(*_args, **_kwargs):
        raise OperationalError("database is busy")

    monkeypatch.setattr(AssetIndexRepository, "current_revision", always_busy)
    monkeypatch.setattr(asset_index_module.time, "sleep", lambda _delay: None)
    result = service.index_directory_tree_result(schema_db, library, library)

    assert result.status is AssetIndexPublishStatus.BUSY
    assert result.retry_count == _BUSY_RETRY_LIMIT
    assert isinstance(result.failure, OperationalError)


def test_index_directory_skips_hidden_entries(tmp_path, schema_db):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / ".hidden.txt").write_text("hidden", encoding="utf-8")
    (lib / ".git").mkdir()
    (lib / "visible.txt").write_text("visible", encoding="utf-8")

    svc = AssetIndexService()
    count = svc.index_directory(schema_db, lib, lib)

    assert count == 1
    assert svc.count(schema_db, lib) == 1
    assert svc.get_entry(schema_db, lib / ".hidden.txt") is None
    assert svc.get_entry(schema_db, lib / "visible.txt") is not None


def test_index_directory_tree_skips_hidden_subtrees(tmp_path, schema_db):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / ".hidden_dir").mkdir()
    (lib / ".hidden_dir" / "secret.txt").write_text("s", encoding="utf-8")
    (lib / "visible.txt").write_text("v", encoding="utf-8")

    svc = AssetIndexService()
    result = svc.index_directory_tree_result(schema_db, lib, lib)

    assert result.status is AssetIndexPublishStatus.PUBLISHED
    assert result.count == 1
    assert svc.count(schema_db, lib) == 1
    assert svc.get_entry(schema_db, lib / ".hidden_dir" / "secret.txt") is None
    assert svc.get_entry(schema_db, lib / "visible.txt") is not None


# M6a-18 (non-force fast path verifying on-disk changes) was reverted: a
# directory mtime is always >= its newest child mtime, so an equality check
# cannot reliably distinguish an unchanged directory.  A recorded directory
# mtime snapshot (DB migration) is required; deferred to a later round.
def test_index_directory_non_force_skips_when_entries_exist(tmp_path, schema_db):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "file.txt").write_text("x", encoding="utf-8")

    svc = AssetIndexService()
    first = svc.index_directory_result(schema_db, lib, lib, force=True)
    assert first.status is AssetIndexPublishStatus.PUBLISHED
    assert first.count == 1

    # Without force, an already-indexed directory is skipped (fast path).
    result = svc.index_directory_result(schema_db, lib, lib, force=False)
    assert result.status is AssetIndexPublishStatus.SKIPPED
    assert result.count == 1
    assert svc.count(schema_db, lib) == 1


def test_refresh_lock_registry_is_bounded():
    from types import SimpleNamespace

    from AssetsManager.application.asset_index_service import (
        _REFRESH_LOCKS,
        _REFRESH_LOCKS_GUARD,
        _REFRESH_LOCKS_MAX,
        _refresh_lock_for,
    )

    keys = [f"lru-lock-{index}" for index in range(_REFRESH_LOCKS_MAX + 40)]
    with _REFRESH_LOCKS_GUARD:
        original = {key: _REFRESH_LOCKS.get(key) for key in keys}
    try:
        for key in keys:
            _refresh_lock_for(
                SimpleNamespace(
                    context=SimpleNamespace(root_identity=SimpleNamespace(map_key=key))
                )
            )
        with _REFRESH_LOCKS_GUARD:
            assert len(_REFRESH_LOCKS) <= _REFRESH_LOCKS_MAX
            # The oldest created keys were evicted rather than accumulated.
            assert all(key not in _REFRESH_LOCKS for key in keys[:40])
    finally:
        with _REFRESH_LOCKS_GUARD:
            for key in keys:
                _REFRESH_LOCKS.pop(key, None)
            for key, lock in original.items():
                if lock is not None:
                    _REFRESH_LOCKS[key] = lock


def test_index_directory_rescans_when_directory_mtime_changes(tmp_path, schema_db):
    """M6a-18: the fast path must detect on-disk changes via dir_mtime."""
    import os
    import time as _time

    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "file.txt").write_text("x")

    conn = schema_db
    svc = AssetIndexService()
    assert svc.index_directory(conn, lib, lib) == 1
    assert svc.index_directory(conn, lib, lib, force=False) == 1  # SKIPPED

    # Touch the directory so its mtime advances past the snapshot.
    (lib / "new.txt").write_text("new")
    os.utime(lib)

    assert svc.index_directory(conn, lib, lib, force=False) == 2
    assert svc.count(conn, lib) == 2


def test_index_directory_empty_directory_skips_after_snapshot(tmp_path, schema_db):
    """An empty indexed directory is SKIPPED instead of rescanned every time."""
    lib = tmp_path / "lib"
    lib.mkdir()

    conn = schema_db
    svc = AssetIndexService()
    assert svc.index_directory(conn, lib, lib) == 0
    # Second call: dir_mtime matches → SKIPPED (returns 0 without rescan).
    assert svc.index_directory(conn, lib, lib, force=False) == 0
    assert svc.count(conn, lib) == 0
