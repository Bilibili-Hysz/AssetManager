"""Shared test fixtures."""
import itertools
import os
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

import pytest

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
import _pytest.tmpdir as _pytest_tmpdir_plugin

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
    from AssetsManager.core.settings import AppSettings
    from AssetsManager.core.tag_library import get_library

    install_app_settings_provider(lambda: AppSettings.instance())
    install_tag_canonicalizer(get_library().canonical)
    yield


# ── Test-session runtime-data protection ──────────────────────────
# Tests create per-library SQLite databases and identity markers under
# RuntimeData/.  A full suite can leave tens of thousands of artifact
# directories behind.  We snapshot user-facing config files before the
# session and sweep test-produced RuntimeData artifacts afterwards, while
# never touching real user libraries (identified by their identity marker,
# which records the resolved library root path).
_SESSION_START: float | None = None
_PRESERVED_SHARED_FILES: dict[str, bytes | None] = {}

# Debug escape hatch: keep everything (e.g. when inspecting test artifacts).
_KEEP_RUNTIME_DATA = os.environ.get("AM_KEEP_TEST_RUNTIME_DATA") == "1"

# User-facing config files that tests may legitimately write through
# AppSettings / TagLibrary / ToolScheduler singletons; restored afterwards.
_PROTECTED_SHARED_FILES = ("settings.json", "tag_library.json", "tools.json")


def _is_test_root(map_key: str) -> bool:
    """True when a library-root identity points into a pytest workspace.

    Matches roots under the system temp dir (the default pytest basetemp)
    or whose path contains "pytest" (e.g. a custom ``--basetemp``).
    """
    try:
        root = Path(map_key).resolve()
    except (OSError, ValueError):
        return False
    key = str(root).lower()
    return key.startswith(tempfile.gettempdir().lower()) or "pytest" in key


def _read_identity(path: Path) -> str | None:
    """Return the library-root key recorded in an identity marker, or None."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    return text or None


def _remove_dir_retry(path: Path, attempts: int = 2, delay: float = 0.5) -> None:
    """Remove a directory, retrying briefly for in-process handle release.

    Handles held by reconciliation workers usually outlive this window;
    a single quick retry catches transient locks while a persistent failure
    simply keeps the identity pair for the next pytest process (which holds
    no stale handles and removes it).
    """
    for _ in range(attempts):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return
        time.sleep(delay)


def _db_library_root(db_path: Path) -> str | None:
    """Recover the library root recorded inside an orphaned library DB.

    ``library_stats.library_path`` is written by every opened library;
    ``assets.library_root`` is a secondary source.  Read-only access, any
    failure returns None (caller falls back to the age buffer).
    """
    import sqlite3
    from urllib.parse import quote

    try:
        uri = f"file:{quote(db_path.as_posix(), safe='/')}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=1)
        try:
            row = conn.execute(
                "SELECT library_path FROM library_stats LIMIT 1"
            ).fetchone()
            if row and row[0]:
                return str(row[0])
            row = conn.execute(
                "SELECT library_root FROM assets LIMIT 1"
            ).fetchone()
            if row and row[0]:
                return str(row[0])
        finally:
            conn.close()
    except Exception:
        return None
    return None


def _preserve_shared_config() -> None:
    """Snapshot user config files so tests cannot permanently modify them."""
    from AssetsManager.core.path_resolver import SHARED_DIR

    for name in _PROTECTED_SHARED_FILES:
        path = Path(SHARED_DIR) / name
        try:
            original = path.read_bytes() if path.exists() else None
        except OSError:
            original = None
        _PRESERVED_SHARED_FILES[str(path)] = original


def _restore_shared_config() -> None:
    """Restore the snapshot taken at session start."""
    for path_str, original in _PRESERVED_SHARED_FILES.items():
        path = Path(path_str)
        try:
            if original is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(original)
        except OSError:
            pass
    _PRESERVED_SHARED_FILES.clear()


def _cleanup_test_runtime_data() -> None:
    """Remove RuntimeData artifacts created by the test session.

    Only artifacts whose library-root identity resolves inside the system
    temp workspace (or contains "pytest") are removed; real user libraries,
    their identity markers, locks, and the Shared/ config files are never
    touched.
    """
    if _KEEP_RUNTIME_DATA:
        return
    from AssetsManager.core.path_resolver import SHARED_DIR

    runtime_root = Path(SHARED_DIR).parent  # RuntimeData/
    shared = Path(SHARED_DIR)
    if not runtime_root.exists():
        return
    start = _SESSION_START or 0.0

    # 1. Library data directories whose identity points at a pytest root.
    for entry in runtime_root.iterdir():
        if not entry.is_dir():
            continue
        if entry.name in ("Shared", "_orphaned"):
            continue
        map_key = _read_identity(shared / f"{entry.name}.identity")
        if map_key and _is_test_root(map_key):
            _remove_dir_retry(entry)
            if entry.exists():
                # Deletion failed (a handle is still held in-process, e.g.
                # by a reconciliation worker finishing its task).  Keep the
                # identity marker so a later session (fresh process,
                # released handles) can retry the pair.
                continue
            identity = shared / f"{entry.name}.identity"
            identity.unlink(missing_ok=True)
            Path(str(identity) + ".pending.lock").unlink(missing_ok=True)

    # 1b. Identity-less orphan dirs.  Pure thumbnail-cache dirs are always
    #     test artifacts; bare-db dirs are inspected through
    #     ``library_stats.library_path`` for their root (a fresh real
    #     library could look identical, so unverifiable dirs fall back to a
    #     24h age buffer).
    _DB_SIDECARS = {"assetmanager.db", "assetmanager.db-wal", "assetmanager.db-shm"}
    for entry in runtime_root.iterdir():
        if not entry.is_dir() or entry.name in ("Shared", "_orphaned"):
            continue
        if (shared / f"{entry.name}.identity").exists():
            continue  # handled above
        try:
            names = {p.name for p in entry.iterdir()}
        except OSError:
            continue
        if not names:
            shutil.rmtree(entry, ignore_errors=True)
            continue
        if names == {".thumbnails"}:
            shutil.rmtree(entry, ignore_errors=True)
            continue
        if not names <= _DB_SIDECARS | {".thumbnails"}:
            continue  # has user-data sidecars (favorites/recent) — keep
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        if "assetmanager.db" in names:
            root_key = _db_library_root(entry / "assetmanager.db")
            if root_key and _is_test_root(root_key):
                shutil.rmtree(entry, ignore_errors=True)
                continue
            if mtime >= start:
                # Created during this session without an identity marker:
                # a real library always gets one from open_library, so this
                # is a test artifact (cleanup raced the identity marker).
                shutil.rmtree(entry, ignore_errors=True)
                continue
        if mtime < time.time() - 24 * 3600:
            shutil.rmtree(entry, ignore_errors=True)

    # 2. Orphaned identity markers whose data directory is gone (the
    #    library was deleted or its dir was never fully created).  Any
    #    marker pointing at a pytest root is a test artifact; real-library
    #    markers always have their data dir present and are kept.
    for identity in shared.glob("*.identity"):
        data_dir = runtime_root / identity.name[: -len(".identity")]
        if data_dir.exists():
            continue
        map_key = _read_identity(identity)
        if map_key and _is_test_root(map_key):
            identity.unlink(missing_ok=True)
            Path(str(identity) + ".pending.lock").unlink(missing_ok=True)

    # 2b. Library lock files created during the session (their owning test
    #     process has exited, so no live holder can be affected).  Historical
    #     lock files are left untouched because they cannot be attributed.
    for lock in shared.glob("library-*.lock"):
        try:
            if lock.stat().st_mtime >= start:
                lock.unlink(missing_ok=True)
        except OSError:
            pass

    # 3. Undo backup directories created during the session (their owner
    #    test process is dead by now).
    undo_root = Path(tempfile.gettempdir())
    for entry in undo_root.glob("AssetsManager_undo_*"):
        try:
            if entry.stat().st_mtime >= start:
                shutil.rmtree(entry, ignore_errors=True)
                Path(str(entry) + ".assetsmanager-owner").unlink(missing_ok=True)
        except OSError:
            pass

    # 3b. Historical stale undo backups are left to the application's own
    #     startup cleanup (7-day policy).  Sweeping them here would scan the
    #     whole temp dir (tens of thousands of entries after heavy test
    #     runs) and they are frequently pinned by OS-level handles anyway;
    #     see scripts/cleanup_undo_zombies.ps1 for a manual admin sweep.

    # 4. Restore-quarantine dirs produced during the session.
    orphaned = runtime_root / "_orphaned"
    if orphaned.exists():
        for entry in orphaned.iterdir():
            try:
                if entry.stat().st_mtime >= start:
                    shutil.rmtree(entry, ignore_errors=True)
            except OSError:
                pass


def _is_xdist_worker() -> bool:
    """True when running under pytest-xdist as a non-master worker.

    Workers are separate processes that each run session hooks; shared
    config restore and RuntimeData cleanup must happen exactly once in the
    master after every worker has finished.
    """
    return bool(os.environ.get("PYTEST_XDIST_WORKER"))


def pytest_sessionstart(session):
    global _SESSION_START
    _SESSION_START = time.time()
    if not _is_xdist_worker():
        _preserve_shared_config()


def pytest_sessionfinish(session, exitstatus):
    if _is_xdist_worker():
        return
    _restore_shared_config()
    _cleanup_test_runtime_data()
    # tmp_path replacement dirs live under the workspace root (see the
    # fixture below); best-effort sweep of what the sandbox still allows.
    for path in _SANDBOX_TMP_PATHS:
        shutil.rmtree(path, ignore_errors=True)
    _SANDBOX_TMP_PATHS.clear()
    shutil.rmtree(_TMP_PATHS_ROOT, ignore_errors=True)


# ── Sandbox-tolerant tmp_path / mkdtemp ───────────────────────────
# Under the DSH sandbox, directories created with an explicit mode (every
# tempfile.mkdtemp call passes mode 0o700) become unusable immediately: the
# mode leaks into an ACL that denies listing and file creation even to the
# creating process.  pytest's built-in tmp_path therefore errors at setup.
# When the sandbox temp dir is detected we replace tempfile.mkdtemp with a
# default-mode mkdir under the workspace root and route tmp_path through it;
# TemporaryDirectory and test-local mkdtemp calls inherit the fix, and the
# one-unique-dir-per-test semantics stay unchanged everywhere else.
_TMP_PATHS_ROOT = Path(__file__).resolve().parent.parent / ".pytest-tmp-paths"
_TMP_PATHS_COUNTER = itertools.count()
_SANDBOX_TEMP = "dsh-" in tempfile.gettempdir().lower()
_SANDBOX_TMP_PATHS: list[Path] = []


def _sandbox_mkdtemp(suffix=None, prefix=None, dir=None) -> str:
    base = Path(dir) if dir is not None else _TMP_PATHS_ROOT
    base.mkdir(exist_ok=True)
    name = f"{prefix or 'tmp'}{suffix or ''}{next(_TMP_PATHS_COUNTER)}-{os.getpid()}"
    path = base / name
    path.mkdir()  # default mode — the sandbox breaks 0o700 directories
    return str(path)


def pytest_configure(config):
    if _SANDBOX_TEMP:
        tempfile.mkdtemp = _sandbox_mkdtemp


@pytest.fixture
def tmp_path(request) -> Path:
    path = Path(tempfile.mkdtemp(prefix="am-test-"))
    if _SANDBOX_TEMP:
        # Deferred cleanup: a per-test rmtree can run before the monkeypatch
        # fixture is undone (parameter order), tripping over a leaked
        # os.scandir patch; sweep these at session end like pytest's own
        # basetemp retention does.
        _SANDBOX_TMP_PATHS.append(path)
    else:
        request.addfinalizer(lambda: shutil.rmtree(path, ignore_errors=True))
    return path


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

    # Clean up RuntimeData directories created from temp paths
    for root_key in opened_roots:
        try:
            data_dir = library_data_dir(root_key)
            # Only clean up directories that look like test artifacts
            # (roots under the system temp dir or containing "pytest").
            if _is_test_root(str(root_key)):
                if data_dir.exists():
                    shutil.rmtree(data_dir, ignore_errors=True)
        except Exception:
            pass
