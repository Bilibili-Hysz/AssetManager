# Testing Strategy

The original baseline was `90 passed, 4 warnings` with `pytest` in the refactor workspace. The current flattened-root audited state is `603 passed, 0 warnings`.

## Required Checks

- Run `pytest` before and after each refactor phase.
- Run `python -m ruff check .` after installing `requirements-dev.txt`; full-repository cleanup is complete.
- Run `python -m pyright` after installing `requirements-dev.txt`; `pyrightconfig.json` is scoped to application/lan/core with 0 errors.
- Run `python -m compileall AssetsManager` to verify no syntax errors.
- Add unit tests for new application services.
- Add integration tests for migrations, SQLite repositories, LAN path validation, and share scope.
- Add desktop tests only where behavior cannot be tested without Qt.
- Keep architecture boundary tests passing when moving code between layers.

## Quality Gate Summary

| Check | Status | Notes |
|---|---|---|
| `pytest` | 603 passed | No warnings |
| `ruff check .` | All checks passed | Full-repository clean |
| `pyright` | 0 errors, 0 warnings, 0 informations | Scoped by `pyrightconfig.json` |
| `compileall` | All files compiled | No syntax errors |

## Architecture Boundary Tests

`tests/unit/test_architecture_boundaries.py` scans imports with `ast` and guards the highest-value dependency rules:

- `domain/` does not import application, controllers, LAN, repositories, or presentation modules.
- `core/` does not grow dependencies on upper layers, except documented transitional plugin category registration.
- non-presentation layers do not grow PySide6 dependencies.
- `lan/` does not import desktop presentation modules.
- desktop presentation code does not add direct DB/store calls outside documented bootstrap-free fallback functions.

If a new exception is truly required, update `docs/adr/0001-architecture-governance.md` in the same change.

## Test Layout Direction

Current layout:

- `tests/unit/` — pure Python domain/application logic tests
- `tests/integration/` — SQLite, filesystem, migration, service integration tests
- `tests/desktop/` — PySide6 offscreen widget behavior tests
- `tests/lan/` — aiohttp route and security tests
- `tests/core/` — core infrastructure tests
- `tests/perf/` — optional local performance baselines

## Performance Baselines

Run `python -m tests.perf.perf_baseline` to regenerate. Current baseline (500 files, 25 dirs):

| Operation | Avg | Min |
|---|---|---|
| `AssetService.list_directory()` | 16.9 ms | 16.7 ms |
| `ProjectService.list_projects()` | 179.7 ms | 164.3 ms |
| `ProjectService.build_tree()` | 8.1 ms | 7.8 ms |
| `thumbnail_cache_key()` x10000 | 775.8 us | 7757.6 us |
| `sort_key_for_entry()` x1000 items x100 | 2.9 ms | 2.4 ms |

Track these before high-risk changes:

- Large directory listing time.
- Search/filter/sort time.
- Thumbnail cache miss and hit time.
- LAN `/api/files`, `/api/projects`, and thumbnail response time.
- Application cold start and library switch time.
