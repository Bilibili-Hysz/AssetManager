"""S2 gate tests — pages must not import api factories directly."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = ROOT / "scripts" / "check_frontend_data_fetch.py"
_spec = importlib.util.spec_from_file_location(
    "check_frontend_data_fetch", _SCRIPT)
assert _spec is not None and _spec.loader is not None
check_frontend_data_fetch = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = check_frontend_data_fetch
_spec.loader.exec_module(check_frontend_data_fetch)


def test_frontend_data_fetch_gate_passes_on_current_tree():
    violations = check_frontend_data_fetch.collect_violations(ROOT)
    assert violations == [], "\n".join(v.format() for v in violations)


def test_frontend_gate_scans_pages_only():
    files = check_frontend_data_fetch._page_files(ROOT)
    assert files, "expected page files to be scanned"
    assert all(
        path.is_relative_to(check_frontend_data_fetch.PAGES_DIR)
        for path in files
    )
    assert all(".test." not in path.name for path in files)


def test_frontend_gate_detects_api_factory_patterns():
    assert check_frontend_data_fetch._IMPORT_RE.search(
        "import { createShopApi } from '../api/shop';")
    assert check_frontend_data_fetch._IMPORT_RE.search(
        "import { createApiClient } from '../api/client';")
    # api/errors is the explicit exception used by the collector.
    assert check_frontend_data_fetch._API_ERRORS_RE.search(
        "import { ApiError } from '../api/errors';")
    assert check_frontend_data_fetch._CLIENT_CALL_RE.search(
        "const api = createApiClient();")
    assert check_frontend_data_fetch._FETCH_CALL_RE.search(
        "fetch('/api/revision')")
