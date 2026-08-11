import sqlite3
import threading
import time



_SCHEMA = """
CREATE TABLE reconciliation_tasks (
    task_id TEXT PRIMARY KEY NOT NULL,
    library_root TEXT NOT NULL,
    path TEXT NOT NULL,
    kind TEXT NOT NULL,
    reason TEXT NOT NULL,
    state TEXT NOT NULL,
    attempts INTEGER NOT NULL CHECK (attempts >= 0),
    next_attempt_at_wallclock REAL NOT NULL,
    operation_ids TEXT NOT NULL DEFAULT '[]',
    last_error_type TEXT,
    last_error TEXT,
    expected_revision INTEGER,
    observed_revision INTEGER,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    lease_expires_at_wallclock REAL,
    lease_token TEXT,
    max_attempts INTEGER NOT NULL CHECK (max_attempts >= 1),
    UNIQUE (library_root, path, kind)
);
CREATE INDEX idx_reconciliation_tasks_due
    ON reconciliation_tasks(library_root, state, next_attempt_at_wallclock);
CREATE TABLE reconciliation_queue_state (
    library_root TEXT PRIMARY KEY NOT NULL,
    generation INTEGER NOT NULL DEFAULT 0 CHECK (generation >= 0),
    updated_at REAL NOT NULL
);
"""


def _queues(tmp_path, *, poll_interval=0.05):
    from AssetsManager.application import (
        ReconciliationQueue,
        SQLiteReconciliationQueueStore,
    )

    database = tmp_path / "reconciliation.sqlite3"
    connection_a = sqlite3.connect(database, check_same_thread=False, timeout=5.0)
    connection_a.executescript(_SCHEMA)
    connection_a.commit()
    connection_b = sqlite3.connect(database, check_same_thread=False, timeout=5.0)
    library = tmp_path / "library"
    store_a = SQLiteReconciliationQueueStore(
        connection=connection_a,
        library_root=library,
        allow_unmanaged=True,
    )
    store_b = SQLiteReconciliationQueueStore(
        connection=connection_b,
        library_root=library,
        allow_unmanaged=True,
    )
    queue_a = ReconciliationQueue(
        library_root=library,
        persistence_store=store_a,
        cross_process_poll_interval=poll_interval,
    )
    queue_b = ReconciliationQueue(
        library_root=library,
        persistence_store=store_b,
        cross_process_poll_interval=poll_interval,
    )
    return queue_a, queue_b, connection_a, connection_b, library


def test_sqlite_remote_enqueue_wakes_waiting_queue(tmp_path):
    queue_a, queue_b, connection_a, connection_b, library = _queues(tmp_path)
    result = []
    started = threading.Event()

    def waiter():
        started.set()
        result.append(queue_a.wait_for_ready(now=time.monotonic(), timeout=2.0))

    thread = threading.Thread(target=waiter)
    thread.start()
    assert started.wait(1.0)
    time.sleep(0.05)
    task = queue_b.enqueue_or_merge(path=library / "assets", reason="remote")
    thread.join(1.5)
    try:
        assert not thread.is_alive()
        assert result == [True]
        observed = queue_a.get(task.task_id)
        assert observed is not None
        assert observed.task_id == task.task_id
        assert queue_a.persistence_generation == queue_b.persistence_generation
    finally:
        connection_a.close()
        connection_b.close()


def test_sqlite_enqueue_before_wait_is_observed_from_durable_snapshot(tmp_path):
    queue_a, queue_b, connection_a, connection_b, library = _queues(tmp_path)
    try:
        task = queue_b.enqueue_or_merge(path=library / "before-wait", reason="remote")
        started = time.monotonic()
        assert queue_a.wait_for_ready(now=started, timeout=1.0)
        assert queue_a.get(task.task_id) is not None
        assert time.monotonic() - started < 0.5
    finally:
        connection_a.close()
        connection_b.close()


def test_sqlite_queue_wake_returns_for_upper_layer_stop_event(tmp_path):
    queue_a, _queue_b, connection_a, connection_b, _library = _queues(
        tmp_path, poll_interval=0.5
    )
    result = []
    thread = threading.Thread(
        target=lambda: result.append(
            queue_a.wait_for_ready(now=time.monotonic(), timeout=5.0)
        )
    )
    thread.start()
    try:
        time.sleep(0.05)
        queue_a.wake()
        thread.join(1.0)
        assert not thread.is_alive()
        assert result == [False]
    finally:
        connection_a.close()
        connection_b.close()


def test_queue_wake_does_not_block_on_busy_condition_lock(tmp_path):
    from AssetsManager.application import ReconciliationQueue

    queue = ReconciliationQueue(library_root=tmp_path / "library")
    finished = threading.Event()
    queue._condition.acquire()
    try:
        thread = threading.Thread(target=lambda: (queue.wake(), finished.set()))
        thread.start()
        assert finished.wait(0.5)
        thread.join(0.5)
        assert not thread.is_alive()
    finally:
        queue._condition.release()


def test_wait_for_change_consumes_wake_published_before_wait(tmp_path):
    from AssetsManager.application import ReconciliationQueue

    queue = ReconciliationQueue(library_root=tmp_path / "library")
    queue.wake()

    assert queue.wait_for_change(timeout=0.1) is True
