"""Per-pytest-process runtime and temporary-directory isolation.

This module intentionally has no ``AssetsManager`` imports.  It is loaded by
the root conftest before pytest collects application modules, so import-time
path constants see the process-local runtime root.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import uuid
import atexit
from dataclasses import dataclass
from pathlib import Path


_OWNER_FILE = ".pytest-runtime-owner"


@dataclass(frozen=True)
class RuntimeIsolation:
    """Directories and cleanup authority for one pytest interpreter."""

    root: Path
    runtime_root: Path
    scratch_root: Path
    pytest_root: Path
    token: str

    def owns_runtime_path(self, candidate: Path) -> bool:
        """Whether a resolved path is contained by this run's RuntimeData."""
        try:
            candidate.resolve().relative_to(self.runtime_root.resolve())
        except (OSError, RuntimeError, ValueError):
            return False
        return True

    def cleanup(self) -> None:
        """Remove only this interpreter's token-authenticated run root."""
        if os.environ.get("AM_KEEP_TEST_RUNTIME_DATA") == "1":
            return
        try:
            if self.root.parent.name != ".pytest-runtime":
                return
            if (self.root / _OWNER_FILE).read_text(encoding="ascii") != self.token:
                return
            shutil.rmtree(self.root, ignore_errors=True)
        except (OSError, UnicodeError, ValueError):
            pass


def install_pytest_runtime() -> RuntimeIsolation:
    """Create and activate a new runtime domain for this pytest process.

    Existing ``AM_RUNTIME_ROOT`` values are deliberately replaced.  A nested
    pytest is another test process and receives a sibling domain; ordinary
    application subprocesses do not load this module and inherit this value.
    """
    repository = Path(__file__).resolve().parents[2]
    container = repository / ".pytest-runtime"
    token = f"{os.getpid()}-{uuid.uuid4().hex}"
    root = container / token
    runtime_root = root / "RuntimeData"
    scratch_root = root / "scratch"
    pytest_root = root / "pytest"
    for path in (runtime_root, scratch_root, pytest_root):
        path.mkdir(parents=True, exist_ok=False if path == runtime_root else True)
    (root / _OWNER_FILE).write_text(token, encoding="ascii")

    # PathResolver reads this before application imports.  TMP/TEMP/TMPDIR and
    # tempfile.tempdir also constrain legacy undo scans to this run's scratch.
    os.environ["AM_RUNTIME_ROOT"] = str(runtime_root)
    os.environ["TMP"] = str(scratch_root)
    os.environ["TEMP"] = str(scratch_root)
    os.environ["TMPDIR"] = str(scratch_root)
    tempfile.tempdir = str(scratch_root)
    isolation = RuntimeIsolation(root, runtime_root, scratch_root, pytest_root, token)
    # Registered before application imports.  AppSettings registers its saver
    # later, so LIFO atexit ordering cleans a directory it may recreate after
    # pytest_sessionfinish.
    atexit.register(isolation.cleanup)
    return isolation
