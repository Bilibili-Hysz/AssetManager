"""Shared test fixtures."""
import shutil
import sqlite3
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def memory_db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    yield conn
    conn.close()


@pytest.fixture
def schema_db(memory_db):
    """Memory DB with application schema and migrations applied."""
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate
    conn = memory_db
    conn.executescript(database._SCHEMA)
    migrate(conn)
    return conn


@pytest.fixture(autouse=True)
def _cleanup_stores():
    """Close per-library stores and clean up test data directories."""
    yield
    from PySide6.QtCore import QThreadPool
    from PySide6.QtWidgets import QApplication
    from AssetsManager.core import database
    from AssetsManager.core.path_resolver import library_data_dir

    app = QApplication.instance()
    if app is not None:
        app.processEvents()
    QThreadPool.globalInstance().waitForDone()
    if app is not None:
        app.processEvents()

    # Collect opened library roots before closing
    from AssetsManager.core.database import DatabaseManager
    from AssetsManager.core.singleton import ThreadSafeSingleton
    mgr = ThreadSafeSingleton.get(DatabaseManager)
    opened_roots = list(mgr._connections.keys())

    database.close_all_dbs()

    # Reset the global EventBus singleton to avoid handler leaks between tests
    from AssetsManager.domain import event_bus as _eb
    _eb._instance = None

    # Clean up RuntimeData directories created from temp paths
    for root_key in opened_roots:
        try:
            data_dir = library_data_dir(root_key)
            # Only clean up directories that look like test artifacts
            # (temp paths contain "pytest" or are under system temp)
            root_path = Path(root_key)
            if "pytest" in str(root_path).lower() or "tmp" in str(root_path).lower():
                if data_dir.exists():
                    shutil.rmtree(data_dir, ignore_errors=True)
        except Exception:
            pass
