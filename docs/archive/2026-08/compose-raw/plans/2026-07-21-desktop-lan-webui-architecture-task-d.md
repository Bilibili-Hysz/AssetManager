# Desktop–LAN–WebUI Architecture Task D Implementation Plan

> [!NOTE]
> This document may not reflect the current implementation.
> See the [Task D final report](../reports/desktop-lan-webui-architecture-task-d.md)
> for the delivered compatibility cleanup and verification evidence.

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove only the proven Desktop/LAN/WebUI migration compatibility paths while preserving the canonical `LibrarySession → LibraryRuntime → LAN/React adapters` composition spine.

**Architecture:** Desktop callers resolve `ApplicationBootstrap.runtime_for(session).services` directly. The legacy `for_library()` and `cleanup_library()` bootstrap entry points are removed after all production and test callers migrate. The centralized `RealtimeContext → WebSocketTransportHost → useWebSocket` transport remains because it is still the actual production transport boundary; page/component code remains forbidden from consuming it directly.

**Tech Stack:** Python 3, pytest, PySide6, React 18, TypeScript, Vitest, Vite.

## Global Constraints

- Preserve unrelated working-tree changes; do not reset, checkout, or delete user files.
- Do not read or modify `DeepSeek Docs/`.
- Do not commit or push without explicit authorization.
- Do not introduce a second service assembly path, persistent revision store, Redis, Kafka, React Query, or WebSocket business-object transport.
- Do not remove `migrate_path_metadata_for_library()` while `FileOperationService` still calls it in production.
- Do not modify `WorkspaceTabs.current_library()`; it is UI tab state, not a service-composition fallback.
- Every behavior change starts with a deterministic failing regression and ends with a focused gate.
- `ApplicationBootstrap.runtime_for(session)` is the only production Runtime composition boundary.

## File Responsibility Map

- `AssetsManager/window.py`: resolve Desktop panel services from the canonical Runtime.
- `AssetsManager/window_lifecycle_coordinator.py`: close sessions directly; never perform post-close compatibility cleanup.
- `AssetsManager/application/bootstrap.py`: own Runtime cache/lifecycle only; remove `for_library()` and `cleanup_library()`.
- `AssetsManager/application/metadata_service.py`, `AssetsManager/application/tag_service.py`: update stale compatibility-oriented error messages to describe the required explicit provider/session contract.
- `tests/unit/test_architecture_boundaries.py`: enforce canonical Desktop composition and absence of removed production fallback calls.
- `tests/unit/test_bootstrap.py`, `tests/unit/test_library_runtime.py`, `tests/integration/test_event_publishing.py`, `tests/desktop/*.py`: migrate test fixtures from `for_library(session)` to `runtime_for(session).services`.
- `tests/unit/test_window_session_switching.py`: verify direct Runtime composition and no `cleanup_library()` call.
- `tests/core/test_package_contents.py`, `scripts/check_package_contents.py`: preserve canonical Runtime/DTO/principal package contents.
- `webui/src/hooks/useWebSocket.ts`, `webui/src/types/api.ts`: retain centralized transport and token-free public API contracts; add static checks only where production compatibility residue exists.
- `docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-recalibration.md`, Task D final report, parent report and project memory: record the delivered compatibility cleanup at the Task D handoff; current Task E evidence is in the recalibration final report.

---

### Task 1: Migrate Desktop composition to the canonical Runtime

**Covers:** [S5] Scope and non-goals; canonical Runtime composition constraint.

**Files:**
- Modify: `AssetsManager/window.py`
- Modify: `AssetsManager/window_lifecycle_coordinator.py`
- Test: `tests/unit/test_window_session_switching.py`
- Test: `tests/desktop/test_scoped_service_access.py`

**Interfaces:**
- Consumes: `ApplicationBootstrap.runtime_for(session) -> LibraryRuntime` and `LibraryRuntime.services`.
- Produces: `MainWindow._scoped_services_for_session(session)` returning `runtime_for(session).services`; `WindowLifecycleCoordinator.switch_library()` calling only `close_session(old_session)` for session teardown.

- [x] **Step 1: Add the failing Desktop composition test.**

  Change the scoped-service test double so `bootstrap.runtime_for(session)` returns a Runtime with `.services`, while `bootstrap.for_library` raises if called. Assert the window applies the Runtime service bundle:

  ```python
  runtime = SimpleNamespace(services=services)
  bootstrap.runtime_for.return_value = runtime
  bootstrap.for_library.side_effect = AssertionError("legacy composition used")

  assert window._scoped_services_for_session(session) is services
  bootstrap.runtime_for.assert_called_once_with(session)
  ```

  Add a switch test with `bootstrap.cleanup_library` replaced by a function that raises. Assert the old session closes and the new session opens without calling the removed cleanup hook.

- [x] **Step 2: Run the focused tests and confirm RED.**

  Run:

  ```powershell
  python -m pytest tests/unit/test_window_session_switching.py tests/desktop/test_scoped_service_access.py -q
  ```

  Expected: FAIL because `MainWindow` still calls `for_library()` and the coordinator still calls `cleanup_library()`.

- [x] **Step 3: Implement the minimal Desktop migration.**

  Replace the window helper body with:

  ```python
  def _scoped_services_for_session(self, session):
      return self._bootstrap.runtime_for(session).services
  ```

  Remove only the `old_root` variable and `window._bootstrap.cleanup_library(old_root)` call from `switch_library()`. Keep `close_session(old_session)` as the lifecycle trigger and preserve existing error/status/tray ordering.

- [x] **Step 4: Run the focused tests and confirm GREEN.**

  Run the same command. Expected: all focused Desktop composition and switching tests pass, including the existing stop-failure cleanup cases.

---

### Task 2: Delete the proven bootstrap compatibility API and migrate callers

**Covers:** [S5] Scope and non-goals; explicit Runtime/session ownership.

**Files:**
- Modify: `AssetsManager/application/bootstrap.py`
- Modify: `AssetsManager/application/metadata_service.py`
- Modify: `AssetsManager/application/tag_service.py`
- Modify: `tests/unit/test_bootstrap.py`
- Modify: `tests/unit/test_library_runtime.py`
- Modify: `tests/integration/test_event_publishing.py`
- Modify: `tests/integration/test_file_operation_service.py`
- Modify: `tests/integration/test_undo_service.py`
- Modify: `tests/desktop/conftest.py`
- Modify: `tests/desktop/test_file_list_details.py`
- Modify: `tests/desktop/test_file_list_shim.py`
- Modify: `tests/desktop/test_scoped_service_access.py`
- Modify: any additional test file reported by `rg -n "for_library\(" tests`
- Test: `tests/unit/test_architecture_boundaries.py`

**Interfaces:**
- Consumes: `runtime_for(session).services` as the sole scoped-service accessor.
- Produces: no `ApplicationBootstrap.for_library()` or `ApplicationBootstrap.cleanup_library()` methods; explicit provider/session error messages that do not advertise removed compatibility APIs.

- [x] **Step 1: Add the failing static compatibility gates.**

  Add tests that scan production Python files, excluding `tests/`, `DeepSeek Docs/`, `__pycache__` and the bootstrap definition itself where necessary:

  ```python
  def test_desktop_uses_runtime_for_session():
      source = (SRC / "window.py").read_text(encoding="utf-8")
      assert "runtime_for(session)" in source
      assert "for_library(session)" not in source

  def test_no_production_cleanup_library_compatibility_call():
      for path in (SRC / "window.py", SRC / "window_lifecycle_coordinator.py"):
          assert "cleanup_library(" not in path.read_text(encoding="utf-8")

  def test_no_production_for_library_compatibility_call():
      for path in (SRC / "window.py", SRC / "window_lifecycle_coordinator.py"):
          assert "for_library(" not in path.read_text(encoding="utf-8")
  ```

  Add a direct API-removal assertion after the production callers are enumerated:

  ```python
  source = (SRC / "application" / "bootstrap.py").read_text(encoding="utf-8")
  assert "def for_library(" in source
  assert "def cleanup_library(" in source
  ```

- [x] **Step 2: Run the static gate and confirm RED.**

  Run:

  ```powershell
  python -m pytest tests/unit/test_architecture_boundaries.py::test_desktop_uses_runtime_for_session tests/unit/test_architecture_boundaries.py::test_no_production_cleanup_library_compatibility_call tests/unit/test_architecture_boundaries.py::test_no_production_for_library_compatibility_call -q
  ```

  Expected: the Desktop call-site assertions fail against the current compatibility paths. If an assertion passes before the migration, keep it as a regression and make the API-removal assertion fail until the method is deleted.

- [x] **Step 3: Migrate all remaining test callers mechanically and explicitly.**

  For every `bootstrap.for_library(session)` test caller, use:

  ```python
  scoped = bootstrap.runtime_for(session).services
  ```

  Preserve the existing session object and teardown. Do not replace explicit Runtime/session fixtures with raw database connections. Update `tests/desktop/conftest.py` and all test files found by `rg` before deleting the method so the test suite remains importable.

- [x] **Step 4: Delete the bootstrap compatibility methods.**

  Remove `ApplicationBootstrap.for_library()` and `ApplicationBootstrap.cleanup_library()` from `AssetsManager/application/bootstrap.py`. Keep `runtime_for()`, `_close_runtime()`, `_cleanup_session()`, and the Runtime cache unchanged.

  Update service errors to:

  ```python
  "MetadataService requires an explicit ConnectionProvider."
  "TagService requires an explicit db_conn or ConnectionProvider."
  ```

  Do not remove `migrate_path_metadata_for_library()`; `FileOperationService` still calls it in production.

- [x] **Step 5: Run the bootstrap and architecture focused gate.**

  Run:

  ```powershell
  python -m pytest tests/unit/test_architecture_boundaries.py tests/core/test_package_contents.py tests/unit/test_bootstrap.py tests/unit/test_library_runtime.py tests/unit/test_window_session_switching.py -q
  ```

  Expected: zero compatibility-call findings, Runtime cache/lifecycle tests green, and canonical package contents still present.

---

### Task 3: Ratchet WebUI/LAN static boundaries and document Task D

**Covers:** [S5] Scope and non-goals; [S6] completion evidence boundary.

**Files:**
- Modify: `tests/unit/test_architecture_boundaries.py`
- Modify: `tests/core/test_package_contents.py`
- Modify: `scripts/check_package_contents.py`
- Modify: `webui/src/types/api.ts` only if a remaining token compatibility field is found by the static gate
- Modify: `webui/src/hooks/useWebSocket.ts` only if an unused page-level bridge remains after production caller scan
- Create: `docs/compose/reports/desktop-lan-webui-architecture-task-d.md`
- Modify: `docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-recalibration.md`
- Modify: `docs/compose/reports/desktop-lan-webui-architecture-migration.md`

**Interfaces:**
- Consumes: cookie-only auth types, centralized `RealtimeContext`, canonical Runtime composition and package checks.
- Produces: static evidence that page/components do not call `useWebSocket`, auth public types contain no browser bearer-token state, LAN routes do not construct application services from raw connections, and Task D remains distinct from Task E.

- [x] **Step 1: Add failing token/transport/static gates.**

  Assert that `webui/src/types/api.ts`, `webui/src/stores/AuthContext.tsx`, `webui/src/pages/LoginPage.tsx` contain no response/client `token` or `setToken` compatibility state, while allowing share-token functions and server cookie internals. Keep the existing page/component `useWebSocket(` gate and add an explicit assertion that `RealtimeContext.tsx` is the sole production consumer of `WebSocketTransportHost`.

  Assert LAN route files do not instantiate `MetadataService`, `ProjectService`, `TagService`, `SearchService`, `ThumbnailService` or `AssetService` from a raw connection. Preserve the existing eager `LanScopedServices` lookup test.

- [x] **Step 2: Run the static and package gates.**

  Run:

  ```powershell
  python -m pytest tests/unit/test_architecture_boundaries.py tests/core/test_package_contents.py -q
  npm --prefix webui test -- --run src/stores/AuthContext.test.tsx src/stores/RealtimeContext.test.tsx src/hooks/useWebSocket.test.tsx
  ```

  Expected: the new static assertions pass after Task 2 and existing WebUI transport/auth tests remain green. Any failing token assertion must identify an actual remaining browser-visible compatibility field before changing production code.

- [x] **Step 3: Update Task D documentation and plan status.**

  Write `docs/compose/reports/desktop-lan-webui-architecture-task-d.md` with `status: delivered`, the exact removed APIs/callers, preserved `migrate_path_metadata_for_library()` rationale, centralized WebSocket transport decision, verification counts and the Task E handoff state. Mark Task D Steps 1–4 complete in the recalibration plan and update the parent report’s task table without changing the then-current release decision from `partial / not release-ready`.

- [x] **Step 4: Run the complete Task D verification gate.**

  Run serially:

  ```powershell
  python -m pytest tests/unit/test_architecture_boundaries.py tests/core/test_package_contents.py tests/unit/test_bootstrap.py tests/unit/test_window_session_switching.py -q
  npm --prefix webui test -- --run
  npm --prefix webui run typecheck
  npm --prefix webui run build
  python -m pytest -q
  git diff --check
  ```

  Expected at the Task D handoff: all commands exit successfully; the Windows directory-symlink skip is recorded separately; no production `for_library(` or `cleanup_library(` call remains; `DeepSeek Docs/` remains untouched; Task E stays open. The later Task E result supersedes that pending status in the recalibration final report.
