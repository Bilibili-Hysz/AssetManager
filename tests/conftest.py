"""Shared test fixtures."""
import itertools
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

import pytest
from tests.test_support.runtime_isolation import install_pytest_runtime

# This must precede every AssetsManager import, including imports made while
# pytest collects test modules.  Each pytest interpreter deliberately gets a
# new domain, even when it was launched by another pytest process.
_ORIGINAL_TEMP_ENV = " ".join(
    os.environ.get(name, "") for name in ("TMP", "TEMP", "TMPDIR")
).lower()
_RUNTIME_ISOLATION = install_pytest_runtime()

# ── DSH sandbox basetemp sweep tolerance ──────────────────────────
# Under the DSH harness sandbox a pytest-created basetemp directory can
# stop being scandir-able once the creating session finishes (the sandbox
# revokes directory listing on process exit).  pytest's dead-symlink sweep
# then raises PermissionError during pytest_sessionfinish, which surfaces
# as an INTERNALERROR that hides the real test summary and poisons the
# exit code.  The sweep only removes stale symlinks left inside the
# basetemp; skipping it on PermissionError is a strict no-op in every
# non-sandbox environment and preserves the exit code that reflects the
# actual test results.
import _pytest.tmpdir as _pytest_tmpdir_plugin  # noqa: E402

_original_cleanup_dead_symlinks = _pytest_tmpdir_plugin.cleanup_dead_symlinks


def _cleanup_dead_symlinks_tolerant(root) -> None:
    try:
        _original_cleanup_dead_symlinks(root)
    except PermissionError:
        pass


_pytest_tmpdir_plugin.cleanup_dead_symlinks = _cleanup_dead_symlinks_tolerant


@pytest.fixture(autouse=True)
def _tag_store_repository_factory_installed():
    """Install the application-layer seam used by core TagStore tests."""
    from AssetsManager.core.tag_store import install_repository_factory
    from AssetsManager.repositories.tag_repository import TagRepository

    install_repository_factory(
        lambda conn, *, library_root=None, session=None: TagRepository(
            conn, library_root=library_root, session=session
        )
    )
    yield


@pytest.fixture(autouse=True)
def _application_provider_seams_installed():
    """Install the G3 settings/tag-canonicalizer seams for application tests."""
    from AssetsManager.application.app_settings_provider import install_app_settings_provider
    from AssetsManager.application.tag_canonicalizer import install_tag_canonicalizer
    from AssetsManager.core.plugins.host_context import install_event_bus_provider
    from AssetsManager.core.settings import AppSettings
    from AssetsManager.core.tag_library import get_library
    from AssetsManager.domain.event_bus import get_event_bus

    install_app_settings_provider(lambda: AppSettings.instance())
    install_tag_canonicalizer(get_library().canonical)
    install_event_bus_provider(get_event_bus)
    yield


# ── Fast PBKDF2 for the test suite ──────────────────────────────
# The shipped PBKDF2 costs (600k / 100k / 50k iterations) are deliberate
# security knobs, but replaying them on thousands of tests spends the bulk
# of a full run inside hashlib.  Everything under test — hash format,
# verification, rehash signalling — behaves identically at any cost, so the
# suite swaps in small values.  The versioned password format embeds its
# cost, which is what keeps a cheap test hash verifiable against a
# production-cost hash; tests marked ``real_pbkdf2_cost`` opt out and
# observe the real values.  LEGACY must stay below PASSWORD so the
# "legacy hash needs rehash" contract survives the downgrade.
_TEST_PBKDF2_COSTS = {
    "PASSWORD_ITERATIONS": 1_000,
    "LEGACY_PASSWORD_ITERATIONS": 600,
    "KEY_ITERATIONS": 1_000,
}


@pytest.fixture(autouse=True)
def _fast_pbkdf2(request):
    """Override the domain/auth PBKDF2 cost constants for one test."""
    if request.node.get_closest_marker("real_pbkdf2_cost"):
        yield
        return
    if os.environ.get("AM_REAL_PBKDF2") == "1":  # escape hatch for cost baselines
        yield
        return
    from AssetsManager.domain import auth

    originals = {name: getattr(auth, name) for name in _TEST_PBKDF2_COSTS}
    for name, value in _TEST_PBKDF2_COSTS.items():
        setattr(auth, name, value)
    try:
        yield
    finally:
        for name, value in originals.items():
            setattr(auth, name, value)


def _is_test_root(map_key: str) -> bool:
    """True when a library-root identity points into a pytest workspace.

    Test-created library slots belong to this process's RuntimeData root, so
    this is used only for prompt per-test cleanup rather than global
    attribution.
    """
    try:
        root = Path(map_key).resolve()
    except (OSError, ValueError):
        return False
    return _RUNTIME_ISOLATION.owns_runtime_path(root)


def pytest_sessionfinish(session, exitstatus):
    """Keep the run domain alive until pytest and atexit hooks finish.

    ``pytest_sessionfinish`` runs before pytest's remaining teardown hooks and
    before application ``atexit`` handlers. Removing the domain here would
    make pytest's own temp/report cleanup race with us and could let a later
    settings saver recreate part of the directory. The isolation object's
    earliest registered atexit handler performs the token-checked removal
    after those hooks have completed.
    """
    return None


# ── Sandbox-tolerant tmp_path / mkdtemp ───────────────────────────
# Under the DSH sandbox, directories created with an explicit mode (every
# tempfile.mkdtemp call passes mode 0o700) become unusable immediately: the
# mode leaks into an ACL that denies listing and file creation even to the
# creating process.  pytest's built-in tmp_path therefore errors at setup.
# When the sandbox temp dir is detected we replace tempfile.mkdtemp with a
# default-mode mkdir under the isolated scratch directory and route mkdtemp
# through it;
# TemporaryDirectory and test-local mkdtemp calls inherit the fix, and the
# one-unique-dir-per-test semantics stay unchanged everywhere else.
_TMP_PATHS_COUNTER = itertools.count()
_SANDBOX_TEMP = "dsh-" in _ORIGINAL_TEMP_ENV


def _sandbox_mkdtemp(suffix=None, prefix=None, dir=None) -> str:  # noqa: A002
    base = Path(dir) if dir is not None else _RUNTIME_ISOLATION.scratch_root
    base.mkdir(parents=True, exist_ok=True)
    name = f"{prefix or 'tmp'}{suffix or ''}{next(_TMP_PATHS_COUNTER)}-{os.getpid()}"
    path = base / name
    path.mkdir()  # default mode — the sandbox breaks 0o700 directories
    return str(path)


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    if config.option.basetemp is None:
        config.option.basetemp = str(_RUNTIME_ISOLATION.pytest_root)
    if _SANDBOX_TEMP:
        tempfile.mkdtemp = _sandbox_mkdtemp
    config.addinivalue_line(
        "markers",
        "real_pbkdf2_cost: observe production PBKDF2 cost constants "
        "(skip the fast-PBKDF2 override)",
    )


@pytest.fixture
def isolated_plugin_settings(monkeypatch):
    """Keep plugin durable-state tests out of the shared user settings file."""
    from AssetsManager.core.settings import AppSettings

    class _Settings:
        def __init__(self):
            self.data = {}
            self.save_calls = 0

        def get(self, key, default=None):
            return self.data.get(key, default)

        def set(self, key, value):
            self.data[key] = value

        def save(self):
            self.save_calls += 1

    settings = _Settings()
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda cls: settings))
    return settings


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


# ── Shared scratch-library session ────────────────────────────────
# Several service test modules need the same throwaway library: a fresh
# ApplicationBootstrap, a "library/" directory under tmp_path, and an open
# LibrarySession.  The fixture owns the session lifecycle, so tests (and
# fixtures built on top of it) must not call ``library_service.close()``
# themselves.
@pytest.fixture
def opened_session(tmp_path):
    """Yield ``(bootstrap, session)`` for a scratch library under tmp_path.

    ``bootstrap.library_service.close()`` runs during teardown and also
    closes any session the test closed or replaced mid-test.
    """
    from AssetsManager.application import ApplicationBootstrap

    bootstrap = ApplicationBootstrap()
    library = tmp_path / "library"
    library.mkdir()
    session = bootstrap.library_service.open_session(library)
    try:
        yield bootstrap, session
    finally:
        bootstrap.library_service.close()


@pytest.fixture(autouse=True)
def _cleanup_stores():
    """Close per-library stores and clean up test data directories."""
    yield
    from PySide6.QtCore import QThreadPool
    from PySide6.QtWidgets import QApplication
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

    mgr.close()

    # Reset the global EventBus singleton to avoid handler leaks between tests
    from AssetsManager.domain import event_bus as _eb
    _eb._instance = None

    # Only remove paths resolved inside this interpreter's RuntimeData.  A
    # monkeypatched resolver can otherwise target a user-owned directory.
    if os.environ.get("AM_KEEP_TEST_RUNTIME_DATA") == "1":
        return
    for root_key in opened_roots:
        try:
            data_dir = library_data_dir(root_key)
            if _RUNTIME_ISOLATION.owns_runtime_path(data_dir):
                if data_dir.exists():
                    shutil.rmtree(data_dir, ignore_errors=True)
        except Exception:
            pass
