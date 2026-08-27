# C9-min Import UI cancel 与后台池生命周期证据（2026-08-21）

## 1. Scope and baseline

本报告记录 C8 ImportService partial/degraded contract 之后的桌面生命周期收敛：恢复用户取消入口、处理进度对话框关闭竞态、为 import 私有 `BoundedPool` 接入终止性 close/reaper 路径，并让 library switch/shutdown 复用同一 cleanup boundary。

本批不改变 `ImportResult` 字段、不新增 reconciliation kind、不尝试中断正在执行的单个 `shutil.copy2`，也不实现完整 import manifest/outbox。

| Field | Value |
|---|---|
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Worktree source | Dirty worktree |
| Status fingerprint | `cf16112e31f4dc39fa863a54c56e69013c8f78b1f1e1ce50d5f0722c81870cc0` |
| Binary diff fingerprint | `63611e10c899408ccc50e6f7faec510dc43ef212a74d8c902968ce85537ebf5f` |
| Tracked / untracked changes | 89 / 31 before this report and manifest were added |
| Runtime | Windows, Python 3.14 local environment |

## 2. Implemented findings

### C9-01 / C8-01 / EVID-06: Terminal import cleanup boundary

`MainWindow` now owns an idempotent `_cleanup_import()` boundary. It cancels the current token, calls `BoundedPool.close()` with a bounded timeout and an owner label, clears task/pool/token/dialog references, and advances an import generation. A stale worker completion therefore cannot update a newer import or a window whose lifecycle cleanup has already invalidated the generation.

Starting a new import first cleans up any previous import owner state. Normal completion, worker start failure, dialog dismissal, library switch and window shutdown all converge on the same cleanup path. A timeout uses the existing retained-native-pool reaper rather than forcing an unbounded Qt pool destructor on the GUI thread.

### C9-02 / C8-02: Cooperative user cancellation and dialog-close safety

The progress dialog now retains its Cancel button and connects `canceled` to the import token. Cancellation remains cooperative: an active `shutil.copy2` call is not interrupted, but subsequent work observes the token; the existing partial result keeps copied files and the no-refresh/no-import-event cancellation contract.

A dedicated progress-dialog subclass emits a close hook for window-manager/X dismissal. Dismissal requests cancellation, invalidates the owner state and prevents later progress/finished callbacks from touching the dismissed dialog or presenting a message. Worker completion still preserves the two-element `(status, value)` payload and the existing cancelled/error/partial/success presentation contract when the dialog remains active.

### C9-03 / C8-01: Lifecycle coordinator integration

Library switch and shutdown no longer duplicate `cancel_all()` plus `drain()` when the window exposes the canonical cleanup method. They delegate to `_cleanup_import()`, which exercises `BoundedPool.close()` and clears owner references. Compatibility fallback behavior remains for lightweight test doubles or legacy window objects that do not provide the helper.

The ImportService session operation lease remains unchanged and continues to cover scan, copy, refresh, queue fallback and event publication. A new integration race test blocks `copy2`, starts session close, verifies close waits while the import operation is active, verifies new calls are rejected after close begins, then releases the copy and confirms both operation and teardown complete.

## 3. Executed validation

| Command / scope | Result |
|---|---|
| Import/runtime/reconciliation/owner-handoff/watcher/worker/window focused suite | 90 passed |
| ImportService + worker + window/lifecycle + neighboring desktop suite | 244 passed |
| Import lease/close race | passed as part of the 31-test C9 lease/UI subset |
| Import progress-dialog cancel/close signal tests | passed as part of the 30-test C9 window subset |
| Python compileall | passed |
| `ruff check AssetsManager tests scripts run.py` | passed |
| `git diff --check` | no whitespace errors; LF/CRLF conversion warnings only |
| `python scripts/check_doc_stats.py` | README stats current |
| `python scripts/check_audit_reports.py` | audit evidence manifests are valid (13) after this report and manifest were added |
| `python scripts/check_boundaries.py` | passed |
| `python scripts/check_style_sources.py` | 0 violations across 83 scoped files |
| `python scripts/check_route_capabilities.py` | 0 violations |
| `python scripts/check_frontend_data_fetch.py` | 0 violations across 26 page files |
| `python scripts/check_layers.py` | layer DAG passed |

The focused pytest commands used repository-local `--basetemp` and `-n 0` because the default Windows pytest temp root is inaccessible in this environment (`WinError 5`).

## 4. Explicit non-goals and remaining evidence

- Cancellation remains cooperative and cannot abort an in-flight `shutil.copy2`; a large single-file copy can keep the session operation lease active until the system call returns.
- The new tests cover the reusable progress-dialog signal seam, cleanup idempotency, coordinator delegation and a real service-level lease/close race. They do not constitute a full interactive `MainWindow._import_assets()` modal/browser-style E2E run.
- Dialog dismissal and worker completion are guarded by generation/state checks, but a complete independent Windows lifecycle CI scenario with a blocked import worker remains outstanding.
- Filesystem effects and durable queue enqueue are still not one cross-system transaction; no import manifest/outbox was added.
- No full Python suite, browser E2E, real-backend LAN acceptance, dependency/CVE scan, package/release validation, performance benchmark, or independent Windows lifecycle CI was run for this batch.
- C9 findings remain `fixed-unverified`; this report does not mark them `verified-fixed`.
