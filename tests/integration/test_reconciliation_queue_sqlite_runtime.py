def test_sqlite_reconciliation_queue_survives_database_manager_reopen(tmp_path):
    from AssetsManager.application import (
        ReconciliationQueue,
        ReconciliationState,
        SQLiteReconciliationQueueStore,
    )
    from AssetsManager.core.database import DatabaseManager

    library = tmp_path / "library"
    first = DatabaseManager()
    try:
        connection = first.connection_for(library)
        store = SQLiteReconciliationQueueStore(
            connection=connection,
            library_root=library,
            clock=lambda: 100.0,
            wall_clock=lambda: 1000.0,
        )
        queue = ReconciliationQueue(
            library_root=library,
            persistence_store=store,
            clock=lambda: 100.0,
            wall_clock=lambda: 1000.0,
        )
        task = queue.enqueue_or_merge(
            path=library,
            reason="busy",
            operation_id="operation-1",
            now=100.0,
        )
        claimed = queue.claim_next(now=100.0, lease_seconds=5.0)
        assert claimed is not None
        retryable = queue.mark_retryable(
            task.task_id, lease_token=claimed.lease_token, now=100.0
        )
        assert retryable.state is ReconciliationState.RETRYABLE
    finally:
        first.close()

    second = DatabaseManager()
    try:
        connection = second.connection_for(library)
        store = SQLiteReconciliationQueueStore(
            connection=connection,
            library_root=library,
            clock=lambda: 0.0,
            wall_clock=lambda: 1000.25,
        )
        restored = ReconciliationQueue(
            library_root=library,
            persistence_store=store,
            clock=lambda: 0.0,
            wall_clock=lambda: 1000.25,
        )
        current = restored.get(task.task_id)
        assert current is not None
        assert current.state is ReconciliationState.RETRYABLE
        assert current.operation_ids == ("operation-1",)
        assert current.next_attempt_at == 0.0
    finally:
        second.close()
