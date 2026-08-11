"""Integration coverage for the reconciliation bootstrap order."""


def test_bootstrap_orders_schema_marker_migration_and_reconciliation_worker(
    tmp_path, monkeypatch
):
    from AssetsManager.application import ApplicationBootstrap, ReconciliationQueue
    import AssetsManager.application.bootstrap as bootstrap_module
    from AssetsManager.application.asset_index_reconciliation_service import (
        AssetIndexReconciliationService,
    )
    from AssetsManager.core.database import DatabaseManager

    events = []
    library = tmp_path / "library"
    bootstrap = ApplicationBootstrap()

    original_open_library = DatabaseManager.open_library
    original_migrate = bootstrap_module.migrate_reconciliation_marker
    original_start = AssetIndexReconciliationService.start

    def record_open_library_success(manager, root_path):
        result = original_open_library(manager, root_path)
        events.append("schema_migration_complete")
        return result

    def record_marker_migration(*args, **kwargs):
        events.append("migrate_reconciliation_marker_start")
        result = original_migrate(*args, **kwargs)
        events.append("migrate_reconciliation_marker_complete")
        return result

    def record_reconciliation_start(service, *args, **kwargs):
        assert "migrate_reconciliation_marker_complete" in events
        events.append("reconciliation_start")
        result = original_start(service, *args, **kwargs)
        assert service.is_running
        events.append("reconciliation_worker_running")
        return result

    monkeypatch.setattr(DatabaseManager, "open_library", record_open_library_success)
    monkeypatch.setattr(
        bootstrap_module,
        "migrate_reconciliation_marker",
        record_marker_migration,
    )
    monkeypatch.setattr(
        AssetIndexReconciliationService,
        "start",
        record_reconciliation_start,
    )

    session = None
    try:
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
            reason="bootstrap-order-test",
            operation_id="bootstrap-order-test",
            now=10.0,
        )

        runtime = bootstrap.runtime_for(session)
        service = runtime.services.reconciliation_service
        queue = runtime.services.reconciliation_queue
        assert service is not None
        assert queue is not None
        assert service.is_running
        assert queue.get(task.task_id) is not None
        assert not marker.exists()
        assert (marker.parent / (marker.name + ".migrated")).exists()

        migration_complete = events.index("migrate_reconciliation_marker_complete")
        reconciliation_start = events.index("reconciliation_start")
        worker_running = events.index("reconciliation_worker_running")
        assert events.index("schema_migration_complete") < migration_complete
        assert migration_complete < reconciliation_start < worker_running
    finally:
        bootstrap.library_service.close()
