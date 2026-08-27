# Testing Strategy

Historical baseline evolution：`90 passed`（重构早期）→ `603 passed`（架构重构阶段）→ `1590`（2026-08-01）→ `2790`（2026-08-09）→ **`2952 passed, 7 skipped, 0 failed`**（2026-08-11 Windows / Python 3.13 snapshot）。这些数字只描述当时的快照；当前运行结果必须附日期化 command/artifact 证据。完整历史基线见 `docs/full-review/07-verification.md`，C6-C10 当前收敛见 `docs/full-review/c6-c10-convergence-2026-08-21.md`。

## Required Checks

- Run `pytest` before and after each refactor phase.
- Run `python -m ruff check AssetsManager tests scripts run.py` after installing `requirements-dev.txt`; full-repository cleanup is complete.
- Run `python -m pyright` after installing `requirements-dev.txt`; `pyrightconfig.json` is scoped to application/controllers/core(部分)/di/domain/lan/repositories + selected panels/widgets/dialogs with 0 errors.
- Run `python -m compileall AssetsManager` to verify no syntax errors.
- Add unit tests for new application services.
- Add integration tests for migrations, SQLite repositories, LAN path validation, and share scope.
- Add desktop tests only where behavior cannot be tested without Qt.
- Keep architecture boundary tests passing when moving code between layers.

## Quality Gate Summary

| Check | Status | Notes |
|---|---|---|
| `pytest` | **2952 passed, 7 skipped** | 2026-08-11 historical snapshot only; current results require a dated command/artifact |
| `ruff check .` | All checks passed | Full-repository clean |
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

- `tests/unit/` — pure Python domain/application logic tests（57 文件，含架构边界 ast 扫描）
- `tests/integration/` — SQLite, filesystem, migration, service integration tests（46 文件，含对账队列系列）
- `tests/desktop/` — PySide6 offscreen widget behavior tests（34 文件）
- `tests/lan/` — aiohttp route and security tests（30 文件，含契约测试对照 lan_public_contracts.json）
- `tests/core/` — core infrastructure tests（17 文件）
- `tests/e2e/` — 真实 LAN + Playwright Chromium 验收（1 文件）
- `tests/performance/` — pytest 基准（2 文件）；`tests/perf/` — 基准脚本（7 个，含 nightly grid telemetry）
- `tests/contracts/`、`tests/fixtures/` — 契约快照 / 旧版 schema fixture

前端：`webui/src/**/*.test.ts(x)`（90 Vitest 文件）+ `webui/e2e/`（Playwright 5 spec，30 用例）。

## Performance Baselines

Run `python -m tests.perf.perf_baseline` to regenerate. Historical baseline (500 files, 25 dirs, 2026-08 前):

| Operation | Avg | Min |
|---|---|---|
| `AssetService.list_directory()` | 16.9 ms | 16.7 ms |
| `ProjectService.list_projects()` | 179.7 ms | 164.3 ms |
| `ProjectService.build_tree()` | 8.1 ms | 7.8 ms |
| `thumbnail_cache_key()` x10000 | 775.8 us | 7757.6 us |
| `sort_key_for_entry()` x1000 items x100 | 2.9 ms | 2.4 ms |

> 注：上表为早期快照，非当前承诺。当前性能观测走 `tests/perf/` 基准脚本与 nightly grid telemetry（CI 每日 03:17 UTC，artifacts 保留 30 天）。

Track these before high-risk changes:

- Large directory listing time.
- Search/filter/sort time.
- Thumbnail cache miss and hit time.
- LAN `/api/files`, `/api/projects`, and thumbnail response time.
- Application cold start and library switch time.
