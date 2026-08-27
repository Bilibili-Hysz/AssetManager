"""Process-level ownership and committed-teardown tests for LibraryService."""
from __future__ import annotations

import sqlite3
import threading

import pytest

import AssetsManager.application.library_service as library_service_module
import AssetsManager.core.database as database_module
from AssetsManager.application.bootstrap import ApplicationBootstrap
from AssetsManager.application.library_service import LibraryService
from AssetsManager.application.library_export_io import (
    restore_intent_path,
    write_restore_intent,
)
from AssetsManager.core.path_resolver import library_data_dir


def test_stale_restore_coordinator_rejects_live_owner_from_another_bootstrap(tmp_path):
    root = tmp_path / "library"
    first = ApplicationBootstrap()
    second = ApplicationBootstrap()
    old_session = first.library_service.open_session(root)
    first.library_service.close_session(old_session)
    replacement = second.library_service.open_session(root)

    try:
        with pytest.raises(RuntimeError, match="owned by another LibraryService"):
            with first.library_service.restore_reservation(old_session, root):
                pass
    finally:
        second.library_service.close_session(replacement)

    with pytest.raises(RuntimeError, match="superseded"):
        with first.library_service.restore_reservation(old_session, root):
            pass


def test_same_root_is_exclusive_across_services_but_different_roots_are_independent(
    tmp_path,
):
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first = LibraryService()
    second = LibraryService()
    first_session = first.open_session(first_root)

    try:
        with pytest.raises(RuntimeError, match="owned by another LibraryService"):
            second.close_session(first_session)
        assert not first_session.is_closed
        with pytest.raises(RuntimeError, match="owned by another LibraryService"):
            second.open_session(first_root)
        second_session = second.open_session(second_root)
        assert second.owns_live_session(second_session)
    finally:
        first.close_session(first_session)
        if second.current_session is not None:
            second.close_session(second.current_session)


def test_windows_mixed_case_alias_is_rejected_before_lock_acquisition(tmp_path, monkeypatch):
    root = tmp_path / "MiXeDLibrary"
    root.mkdir()
    alias = tmp_path / "MIXEDLIBRARY"
    owner = LibraryService()
    contender = LibraryService()
    session = owner.open_session(root)
    lock_attempts = 0

    def forbidden_lock(_key):
        nonlocal lock_attempts
        lock_attempts += 1
        raise AssertionError("the alias must be rejected before QLock acquisition")

    monkeypatch.setattr(contender, "_acquire_library_lock", forbidden_lock)
    try:
        _, canonical_root = owner.canonical_root_identity(root)
        _, canonical_alias = owner.canonical_root_identity(alias)
        assert canonical_root == canonical_alias
        with pytest.raises(RuntimeError, match="owned by another LibraryService"):
            contender.open_session(alias)
        assert lock_attempts == 0
    finally:
        owner.close_session(session)


def test_restore_failure_poison_is_shared_across_openers_and_can_be_acknowledged(
    tmp_path,
):
    root = tmp_path / "MiXeDLibrary"
    root.mkdir()
    owner = LibraryService()
    session = owner.open_session(root)
    owner.close_session(session)

    with pytest.raises(ValueError, match="unsafe restore"):
        with owner.restore_reservation(session, root):
            error = ValueError("unsafe restore")
            error.restore_recovery_required = True
            raise error

    assert owner.restore_failure_state(root) is not None
    contender = LibraryService()
    with pytest.raises(RuntimeError, match="Restore admission is blocked"):
        contender.open_session(tmp_path / "MIXEDLIBRARY")

    recovery_state = owner.restore_failure_state(root)
    assert recovery_state is not None
    assert owner.acknowledge_restore_failure(
        tmp_path / "MIXEDLIBRARY", recovery_state.token
    ) is None
    replacement = owner.open_session(root)
    owner.close_session(replacement)


def test_queued_open_fails_closed_after_restore_failure_is_published(tmp_path):
    root = tmp_path / "MiXeDLibrary"
    root.mkdir()
    owner = LibraryService()
    session = owner.open_session(root)
    owner.close_session(session)
    started = threading.Event()
    finished = threading.Event()
    result = []

    def queued_open():
        started.set()
        try:
            owner.open_session(tmp_path / "MIXEDLIBRARY")
        except BaseException as error:
            result.append(error)
        finally:
            finished.set()

    reservation = owner.restore_reservation(session, root)
    reservation.__enter__()
    thread = threading.Thread(target=queued_open)
    thread.start()
    assert started.wait(2)
    assert not finished.wait(0.05)
    try:
        raise ValueError("queued restore failure")
    except ValueError as error:
        owner._record_restore_failure(
            owner.canonical_root_identity(root)[1], 1, error, "restore"
        )
    finally:
        reservation.__exit__(None, None, None)
    thread.join(2)

    assert finished.is_set()
    assert len(result) == 1
    assert "Restore admission is blocked" in str(result[0])


def test_lock_release_failure_retains_process_owner_until_retry(tmp_path, monkeypatch):
    root = tmp_path / "library"
    owner = LibraryService()
    contender = LibraryService()
    session = owner.open_session(root)
    owned_lock = owner._library_locks[str(session.root)]
    real_release = owned_lock.release
    calls = 0

    def fail_once():
        nonlocal calls
        calls += 1
        if calls == 1:
            return False
        return real_release()

    monkeypatch.setattr(owned_lock, "release", fail_once)

    with pytest.raises(RuntimeError, match="Failed to release library lock"):
        owner.close_session(session)

    with pytest.raises(RuntimeError, match="owned by another LibraryService"):
        contender.open_session(root)
    with pytest.raises(RuntimeError, match="committed teardown"):
        with owner.restore_reservation(session, root):
            pass

    owner.close_session(session)
    replacement = contender.open_session(root)
    contender.close_session(replacement)


def test_database_close_failure_retains_process_owner_until_retry(tmp_path, monkeypatch):
    root = tmp_path / "library"
    owner = LibraryService()
    contender = LibraryService()
    session = owner.open_session(root)
    real_close_library = owner._db.close_library
    calls = 0

    def fail_once(library_root):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("database close failed")
        return real_close_library(library_root)

    monkeypatch.setattr(owner._db, "close_library", fail_once)

    with pytest.raises(RuntimeError, match="database close failed"):
        owner.close_session(session)

    with pytest.raises(RuntimeError, match="owned by another LibraryService"):
        contender.open_session(root)

    owner.close_session(session)
    replacement = contender.open_session(root)
    contender.close_session(replacement)


def test_database_initialization_failure_closes_registered_connection(
    tmp_path, monkeypatch
):
    created = []

    class FailingInitializationConnection(sqlite3.Connection):
        closed = False

        def executescript(self, _script):
            raise sqlite3.OperationalError("injected schema failure")

        def close(self):
            type(self).closed = True
            return super().close()

    real_connect = database_module.sqlite3.connect

    def connect(*args, **kwargs):
        kwargs["factory"] = FailingInitializationConnection
        connection = real_connect(*args, **kwargs)
        created.append(connection)
        return connection

    monkeypatch.setattr(database_module.sqlite3, "connect", connect)
    manager = database_module.DatabaseManager()
    with pytest.raises(sqlite3.OperationalError, match="injected schema failure"):
        manager.connection_for(tmp_path / "library")

    assert created
    assert FailingInitializationConnection.closed is True
    assert manager._connections == {}
    with pytest.raises(sqlite3.ProgrammingError):
        created[0].execute("SELECT 1")



def test_open_failure_cleanup_is_retryable_after_database_rollback_failure(
    tmp_path, monkeypatch
):
    root = tmp_path / "library"
    owner = LibraryService()
    contender = LibraryService()
    real_context = library_service_module.LibraryContext

    def fail_context(**_kwargs):
        raise RuntimeError("context assembly failed")

    monkeypatch.setattr(library_service_module, "LibraryContext", fail_context)
    real_close_library = owner._db.close_library
    calls = 0

    def fail_once(identity):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("opening database rollback failed")
        return real_close_library(identity)

    monkeypatch.setattr(owner._db, "close_library", fail_once)
    with pytest.raises(RuntimeError, match="context assembly failed"):
        owner.open_session(root)

    key = database_module.DatabaseManager._identity(root).map_key
    assert key in owner._opening_progress
    opening = owner._opening_progress[key]
    assert opening.database_closed is False
    assert opening.lock_released is False
    with pytest.raises(RuntimeError, match="owned by another LibraryService"):
        contender.open_session(root)

    owner.retry_open_cleanup(root)
    assert key not in owner._opening_progress
    monkeypatch.setattr(library_service_module, "LibraryContext", real_context)
    session = owner.open_session(root)
    owner.close_session(session)


def test_service_close_retries_failed_opening_cleanup(
    tmp_path, monkeypatch
):
    root = tmp_path / "library"
    owner = LibraryService()
    real_context = library_service_module.LibraryContext

    def fail_context(**_kwargs):
        raise RuntimeError("context assembly failed")

    monkeypatch.setattr(library_service_module, "LibraryContext", fail_context)
    real_close_library = owner._db.close_library
    calls = 0

    def fail_once(identity):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("opening database rollback failed")
        return real_close_library(identity)

    monkeypatch.setattr(owner._db, "close_library", fail_once)
    with pytest.raises(RuntimeError, match="context assembly failed"):
        owner.open_session(root)

    owner.close()
    assert owner._opening_progress == {}
    monkeypatch.setattr(library_service_module, "LibraryContext", real_context)
    session = owner.open_session(root)
    owner.close_session(session)


def test_real_database_close_failure_retains_connection_and_process_owner(
    tmp_path, monkeypatch
):
    class FailingConnection(sqlite3.Connection):
        fail_close = False

        def close(self):
            if type(self).fail_close:
                raise sqlite3.OperationalError("injected database close failure")
            return super().close()

    real_connect = database_module.sqlite3.connect

    def connect(*args, **kwargs):
        kwargs["factory"] = FailingConnection
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(database_module.sqlite3, "connect", connect)
    root = tmp_path / "library"
    owner = LibraryService()
    contender = LibraryService()
    session = owner.open_session(root)
    key = session.context.root_key
    connection = owner._db._connections[key]
    FailingConnection.fail_close = True

    with pytest.raises(sqlite3.OperationalError, match="injected database close failure"):
        owner.close_session(session)

    with pytest.raises(RuntimeError, match="cleanup is pending"):
        owner._db.connection_for(root)
    assert connection.execute("SELECT 1").fetchone() == (1,)
    assert key in owner._db._connections
    with pytest.raises(RuntimeError, match="owned by another LibraryService"):
        contender.open_session(root)

    FailingConnection.fail_close = False
    owner.close_session(session)
    replacement = contender.open_session(root)
    contender.close_session(replacement)


def test_database_close_rejects_read_to_write_upgrade(tmp_path):
    manager = database_module.DatabaseManager()
    root = tmp_path / "library"
    connection = manager.connection_for(root)

    with database_module.db_write_lock(connection):
        with pytest.raises(RuntimeError, match="current thread holds db_write_lock"):
            manager.close_library(root)
        key = database_module.DatabaseManager._identity(root).map_key
        assert manager._connection_locks[key].closed is False

    manager.close_library(root)

    second_manager = database_module.DatabaseManager()
    second_root = tmp_path / "second-library"
    second_connection = second_manager.connection_for(second_root)
    with database_module.db_write_lock(second_connection):
        with pytest.raises(RuntimeError, match="current thread holds db_write_lock"):
            second_manager.close()
        second_key = database_module.DatabaseManager._identity(second_root).map_key
        assert second_manager._connection_locks[second_key].closed is False
    second_manager.close()



def test_service_close_propagates_finish_failure_and_allows_explicit_retry(
    tmp_path, monkeypatch
):
    root = tmp_path / "library"
    owner = LibraryService()
    contender = LibraryService()
    session = owner.open_session(root)
    real_clear_cache = session.context.tag_store.clear_cache
    calls = 0

    def fail_once():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("session finish failed")
        return real_clear_cache()

    monkeypatch.setattr(session.context.tag_store, "clear_cache", fail_once)

    with pytest.raises(RuntimeError, match="session finish failed"):
        owner.close()

    with pytest.raises(RuntimeError, match="owned by another LibraryService"):
        contender.open_session(root)

    owner.close()
    replacement = contender.open_session(root)
    contender.close_session(replacement)


def test_missing_final_component_identity_reuses_db_and_lock_after_creation(tmp_path):
    root = tmp_path / "MiXeDLibrary"
    service = LibraryService()
    first = service.open_session(root)
    first_data_dir = first.data_dir
    root.mkdir()
    service.close_session(first)

    second = service.open_session(tmp_path / "MIXEDLIBRARY")
    try:
        assert second.context.root_key == first.context.root_key
        assert second.data_dir == first_data_dir
        assert len(service._db._connections) == 1
        assert second.context.db_conn is service._db._connections[second.context.root_key]
    finally:
        service.close_session(second)


def test_stale_generation_ack_cannot_clear_new_process_recovery_state(tmp_path):
    root = tmp_path / "library"
    service = LibraryService()
    session = service.open_session(root)
    service.close_session(session)
    key = session.context.root_key

    first_error = RuntimeError("generation one")
    service._record_restore_failure(key, 1, first_error, "restore")
    token_one = service.restore_failure_state(root).token
    service.acknowledge_restore_failure(root, token_one)

    replacement = service.open_session(root)
    service.close_session(replacement)
    second_error = RuntimeError("generation two")
    service._record_restore_failure(key, 2, second_error, "restore")
    token_two = service.restore_failure_state(root).token

    with pytest.raises(RuntimeError, match="stale or unknown token"):
        service.acknowledge_restore_failure(root, token_one)
    assert service.restore_failure_state(root).token == token_two
    service.acknowledge_restore_failure(root, token_two)


def test_recovery_ack_is_rejected_during_active_restore_reservation(tmp_path):
    root = tmp_path / "library"
    service = LibraryService()
    session = service.open_session(root)
    service.close_session(session)
    key = session.context.root_key

    reservation = service.restore_reservation(session, root)
    reservation.__enter__()
    try:
        service._record_restore_failure(key, 1, RuntimeError("poison"), "restore")
        token = service.restore_failure_state(root).token
        with pytest.raises(RuntimeError, match="active reservation"):
            service.acknowledge_restore_failure(root, token)
        assert service.restore_failure_state(root).token == token
    finally:
        reservation.__exit__(None, None, None)
    service.acknowledge_restore_failure(root, token)


def test_unmarked_restore_preflight_failure_does_not_poison_process(tmp_path):
    root = tmp_path / "library"
    service = LibraryService()
    session = service.open_session(root)
    service.close_session(session)

    with pytest.raises(ValueError, match="preflight"):
        with service.restore_reservation(session, root):
            raise ValueError("preflight validation failed")

    assert service.restore_failure_state(root) is None


def test_marked_restore_failure_poisons_after_reservation_finalizer(tmp_path):
    root = tmp_path / "library"
    service = LibraryService()
    session = service.open_session(root)
    service.close_session(session)

    with pytest.raises(RuntimeError, match="mutation"):
        with service.restore_reservation(session, root):
            error = RuntimeError("mutation failure")
            error.restore_recovery_required = True
            raise error

    state = service.restore_failure_state(root)
    assert state is not None
    assert session.context.root_key not in service._restore_reservations
    service.acknowledge_restore_failure(root, state.token)


def test_restore_intent_status_reports_corrupt_marker_without_opening(tmp_path):
    root = tmp_path / "library"
    data_dir = library_data_dir(root)
    data_dir.mkdir(parents=True)
    marker = restore_intent_path(data_dir)
    marker.write_text("not-json", encoding="utf-8")

    service = LibraryService()
    try:
        status = service.restore_intent_status(root)
        assert status["status"] == "corrupt"
        assert status["token"] is None
        reopened = service.open_session(root)
        assert reopened.data_dir == data_dir
        service.close_session(reopened)
        assert marker.exists() is False
    finally:
        service.close()


def test_restore_intent_manual_ack_requires_token_and_verified_data_dir(tmp_path):
    root = tmp_path / "library"
    data_dir = library_data_dir(root)
    data_dir.mkdir(parents=True)
    token = write_restore_intent(
        data_dir,
        map_key=str(root.resolve()).casefold(),
        quarantine_entry=data_dir.parent / "missing-previous",
        staging=data_dir.parent / ".staging",
    )
    service = LibraryService()
    try:
        with pytest.raises(RuntimeError, match="stale or unknown token"):
            service.acknowledge_restore_intent(root, "wrong")
        service.acknowledge_restore_intent(root, token)
        assert restore_intent_path(data_dir).exists() is False
        assert service.restore_intent_status(root) is None
    finally:
        service.close()


def test_retry_interrupted_restore_recovers_quarantined_previous(tmp_path):
    root = tmp_path / "library"
    service = LibraryService()
    session = service.open_session(root)
    data_dir = session.data_dir
    service.close_session(session)
    quarantine = data_dir.parent / "_orphaned" / "restore-backups" / "manual"
    quarantine.parent.mkdir(parents=True, exist_ok=True)
    (data_dir / "sentinel.txt").write_text("keep", encoding="utf-8")
    data_dir.replace(quarantine)
    write_restore_intent(
        data_dir,
        map_key=session.context.root_key,
        quarantine_entry=quarantine,
        staging=data_dir.parent / ".staging",
    )
    try:
        assert service.restore_intent_status(root)["status"] == "recoverable"
        assert service.retry_interrupted_restore(root) is None
        assert (data_dir / "sentinel.txt").read_text(encoding="utf-8") == "keep"
        assert restore_intent_path(data_dir).exists() is False
    finally:
        service.close()


def test_compatibility_root_map_never_recanonicalizes_captured_keys(monkeypatch, tmp_path):
    import AssetsManager.application.library_service as library_service_module
    from AssetsManager.application.library_service import _CanonicalRootMap

    root_a = tmp_path / "A"
    root_b = tmp_path / "B"
    key_a = str(root_a).casefold()
    key_b = str(root_b).casefold()
    mapping = _CanonicalRootMap()
    mapping[key_a] = "session-a"
    mapping[key_b] = "session-b"

    def forbidden_recanonicalization(_root):
        raise AssertionError("compatibility lookup must not resolve a captured key")

    monkeypatch.setattr(library_service_module, "root_identity", forbidden_recanonicalization)
    assert mapping[str(root_a)] == "session-a"
    assert mapping.pop(str(root_a)) == "session-a"
    assert mapping.get(str(root_b)) == "session-b"


def test_sweep_archives_orphan_staging_and_tmp_but_keeps_marker(tmp_path):
    import os

    from AssetsManager.core.path_resolver import root_identity

    root = tmp_path / "library"
    service = LibraryService()
    session = service.open_session(root)
    data_dir = session.data_dir
    identity = root_identity(root)
    service.close_session(session)

    runtime = data_dir.parent
    stale_dir = runtime / f".{data_dir.name}.restore-{'a' * 32}"
    stale_dir.mkdir()
    fresh_dir = runtime / f".{data_dir.name}.restore-{'b' * 32}"
    fresh_dir.mkdir()
    marker = restore_intent_path(data_dir)
    marker.write_text("{}", encoding="utf-8")
    stale_tmp = runtime / f".{data_dir.name}.restore-intent-deadbeef.tmp"
    stale_tmp.write_text("x", encoding="utf-8")
    old = 1_000_000.0
    os.utime(stale_dir, (old, old))
    os.utime(stale_tmp, (old, old))

    foreign = runtime / f".other-slot.restore-{'c' * 32}"
    foreign.mkdir()
    os.utime(foreign, (old, old))

    service._sweep_orphan_restore_residue(identity, now=old + 9 * 86400)

    assert not stale_dir.exists(), "week-old staging must be archived away"
    backups_root = runtime / "_orphaned" / "restore-backups"
    # The archived copy inherits the source's stale mtime, so the same pass
    # folds it under `_expired`: either location proves successful archival,
    # exactly one entry must exist across the two levels.
    staged = list(backups_root.glob(f".{data_dir.name}.restore-*")) + list(
        (backups_root / "_expired").glob(f".{data_dir.name}.restore-*")
    )
    assert len(staged) == 1
    assert fresh_dir.exists(), "recent staging must be left alone"
    assert not stale_tmp.exists()
    assert marker.exists(), "intent marker is protected crash evidence"
    assert foreign.exists(), "other slots' namespaces are out of bounds"


def test_open_session_runs_sweep_and_survives_scan(tmp_path):
    import os

    root = tmp_path / "library"
    service = LibraryService()
    first = service.open_session(root)
    data_dir = first.data_dir
    service.close_session(first)

    stale = data_dir.parent / f".{data_dir.name}.restore-intent-old.tmp"
    stale.write_text("x", encoding="utf-8")
    os.utime(stale, (1_000_000.0, 1_000_000.0))

    reopened = service.open_session(root)
    try:
        assert reopened.data_dir == data_dir
        assert not stale.exists()
    finally:
        service.close_session(reopened)


def test_sweep_preserves_link_flagged_candidates(tmp_path, monkeypatch):
    import os

    root = tmp_path / "library"
    service = LibraryService()
    session = service.open_session(root)
    data_dir = session.data_dir
    from AssetsManager.core.path_resolver import root_identity

    identity = root_identity(root)
    service.close_session(session)

    stale = data_dir.parent / f".{data_dir.name}.restore-{'d' * 32}"
    stale.mkdir()
    os.utime(stale, (1_000_000.0, 1_000_000.0))
    monkeypatch.setattr(
        "AssetsManager.application.library_service._path_is_link_or_reparse",
        lambda _path: True,
    )

    from AssetsManager.application.library_export_io import (
        safe_restore_quarantine_root,
    )

    quarantine_before = safe_restore_quarantine_root(data_dir, create_missing=False)
    listing_before = set(quarantine_before.iterdir()) if quarantine_before else set()

    service._sweep_orphan_restore_residue(identity, now=1_000_000.0 + 9 * 86400)

    assert stale.exists(), "refused link/reparse candidates must be preserved"
    quarantine_after = safe_restore_quarantine_root(data_dir, create_missing=False)
    listing_after = set(quarantine_after.iterdir()) if quarantine_after else set()
    # Nothing staging-shaped was added under this slot's name.
    assert not {p for p in listing_after - listing_before if p.name.startswith(f".{data_dir.name}")}


def test_archive_expired_quarantine_entries_folds_old_backups(tmp_path):
    import os

    from AssetsManager.application.library_export_io import (
        safe_restore_quarantine_root,
    )

    root = tmp_path / "library"
    service = LibraryService()
    session = service.open_session(root)
    data_dir = session.data_dir
    service.close_session(session)

    q_root = safe_restore_quarantine_root(data_dir)
    old_entry = q_root / f"{data_dir.name}_20200101T000000Z_deadbeef"
    old_entry.mkdir()
    (old_entry / "assetmanager.db").write_bytes(b"db")
    fresh_entry = q_root / f"{data_dir.name}_20990101T000000Z_livebeef"
    fresh_entry.mkdir()
    os.utime(old_entry, (1_000_000.0, 1_000_000.0))

    LibraryService._archive_expired_quarantine_entries(q_root, 1_000_000.0 + 9 * 86400)

    expired = q_root / "_expired" / old_entry.name
    assert expired.is_dir()
    assert (expired / "assetmanager.db").exists()
    assert fresh_entry.exists(), "fresh quarantine entries stay in place"

