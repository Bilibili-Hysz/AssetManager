def test_bootstrap_cuts_over_legacy_marker_to_sqlite_queue(tmp_path):
    from AssetsManager.application import ApplicationBootstrap, ReconciliationQueue

    library = tmp_path / "library"
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    marker = session.data_dir / "reconciliation-queue.json"
    legacy_queue = ReconciliationQueue(
        library_root=library,
        persistence_path=marker,
        clock=lambda: 10.0,
        wall_clock=lambda: 1000.0,
    )
    task = legacy_queue.enqueue_or_merge(
        path=library,
        reason="busy",
        operation_id="legacy-operation",
        now=10.0,
    )

    try:
        runtime = bootstrap.runtime_for(session)
        queue = runtime.services.reconciliation_queue
        assert queue is not None
        assert queue.persistence_path is None
        restored = queue.get(task.task_id)
        assert restored is not None
        assert restored.operation_ids == ("legacy-operation",)
        assert not marker.exists()
        assert (marker.parent / (marker.name + ".migrated")).exists()
        assert session.connection_for(library).execute(
            "SELECT COUNT(*) FROM reconciliation_tasks"
        ).fetchone()[0] == 1
    finally:
        bootstrap.library_service.close()


def test_bootstrap_retries_marker_retirement_after_durable_cutover(tmp_path, monkeypatch):
    from AssetsManager.application import (
        ApplicationBootstrap,
        ReconciliationMarkerMigrationError,
        ReconciliationQueue,
    )
    import AssetsManager.application.reconciliation_queue_migration as migration

    library = tmp_path / "library"
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    marker = session.data_dir / "reconciliation-queue.json"
    legacy_queue = ReconciliationQueue(
        library_root=library,
        persistence_path=marker,
        clock=lambda: 10.0,
        wall_clock=lambda: 1000.0,
    )
    task = legacy_queue.enqueue_or_merge(path=library, reason="busy", now=10.0)

    original_rename = migration.os.rename

    def fail_rename(_source, _target):
        raise OSError("simulated marker archive failure")

    monkeypatch.setattr(migration.os, "rename", fail_rename)
    try:
        try:
            bootstrap.runtime_for(session)
        except ReconciliationMarkerMigrationError as error:
            assert error.durable_store_updated
        else:
            raise AssertionError("expected marker retirement failure")
        assert marker.exists()
        assert session.connection_for(library).execute(
            "SELECT COUNT(*) FROM reconciliation_tasks"
        ).fetchone()[0] == 1
    finally:
        monkeypatch.setattr(migration.os, "rename", original_rename)
        # A failed runtime build must not close the session before the retry.
        runtime = bootstrap.runtime_for(session)
        assert runtime.services.reconciliation_queue is not None
        assert runtime.services.reconciliation_queue.get(task.task_id) is not None
        bootstrap.library_service.close()
