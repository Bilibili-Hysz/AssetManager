# Runtime Event Router Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one session-filtered RuntimeEventRouter to every LibraryRuntime and emit immutable projection invalidations with safe paths and monotonic epoch/revision metadata.

**Architecture:** `RuntimeEventRouter` owns only EventBus subscriptions and subscriber callbacks. `LibraryRuntime` owns the router and closes it before runtime adapter cleanup. Accepted session-scoped events are mapped to deterministic projection domains and increment the existing runtime revision exactly once.

**Tech Stack:** Python 3, frozen dataclasses, Enum, thread-safe EventBus, pytest.

## Global Constraints

- Do not implement WebSocket bridge, HTTP revision endpoint, or React realtime provider in this task.
- Only session-scoped `FileSystemChanged`, `AssetTagsChanged`, `TagCatalogChanged`, `AssetNotesChanged`, and `AssetUrlsChanged` may drive invalidation.
- Wrong session token/root, legacy unscoped events, invalid paths, unknown events, and closed routers must not increment revision or invoke subscribers.
- `InvalidationEvent` must never include database connections, absolute paths, credentials, or repository records.
- Preserve Task 6 Runtime cleanup retry and lifecycle semantics.

---

### Task 1: Define event model and deterministic mappings

**Covers:** [S3], [S4], [S5], [S6]

**Files:**
- Create: `AssetsManager/application/runtime_events.py`
- Test: `tests/integration/test_runtime_events.py`

**Interfaces:**
- Produces `ProjectionDomain`, frozen `InvalidationEvent`, `EVENT_DOMAINS`, and path normalization/mapping helpers used by `RuntimeEventRouter`.

- [ ] **Step 1: Write failing model and mapping tests.** Cover all five event classes, exact domain ordering, root-relative POSIX paths, duplicate removal, root path omission, invalid escape rejection, and empty catalog paths.

- [ ] **Step 2: Run RED.**

```text
python -m pytest tests/integration/test_runtime_events.py -q
```

Expected: collection or import failures because `runtime_events.py` does not exist.

- [ ] **Step 3: Implement the pure model and mapper.** Use a string enum with values `files`, `tree`, `home`, `project_detail`, `metadata`, `tags`; define the five-event mapping in stable tuple order; normalize paths relative to `Path(session.root).resolve()` and reject escapes.

- [ ] **Step 4: Run model tests GREEN.**

```text
python -m pytest tests/integration/test_runtime_events.py -q
```

Expected: all model/path/mapping tests pass.

---

### Task 2: Implement Router subscriptions and filtering

**Covers:** [S2], [S4], [S7], [S9]

**Files:**
- Modify: `AssetsManager/application/runtime_events.py`
- Test: `tests/integration/test_runtime_events.py`

**Interfaces:**
- Produces `RuntimeEventRouter(runtime, event_bus=None)`, `subscribe(handler) -> EventSubscription`, and `close()`.
- `subscribe` handlers receive `InvalidationEvent`; EventBus remains unchanged.

- [ ] **Step 1: Add failing router tests.** Cover accepted events, wrong token/root rejection, legacy event rejection, unknown event rejection, multi-subscriber order, subscriber exception isolation, subscription close, router close idempotence, and no callback after close.

- [ ] **Step 2: Run RED.**

```text
python -m pytest tests/integration/test_runtime_events.py -q
```

Expected: failures for missing Router APIs and callback behavior.

- [ ] **Step 3: Implement Router.** Subscribe only to the five exact event classes. Filter before revision allocation. Call `runtime.next_revision()` only after mapping succeeds. Snapshot subscribers under a lock; isolate callback exceptions; close EventBus subscriptions and reject later subscribers.

- [ ] **Step 4: Run router tests GREEN.**

```text
python -m pytest tests/integration/test_runtime_events.py -q
```

Expected: all router tests pass.

---

### Task 3: Attach Router to LibraryRuntime and preserve lifecycle

**Covers:** [S6], [S8], [S9], [S10]

**Files:**
- Modify: `AssetsManager/application/runtime.py`
- Modify: `AssetsManager/application/bootstrap.py` only if Runtime construction must pass explicit router dependencies
- Modify: `tests/integration/test_runtime_events.py`
- Modify: `tests/integration/test_event_publishing.py`

**Interfaces:**
- `LibraryRuntime.event_router` is available immediately after construction.
- Runtime close closes the router before adapter cleanup; cleanup retry does not recreate or reopen the old router.

- [ ] **Step 1: Add failing integration tests.** Assert every Runtime has an independent router and epoch; events from Runtime A never reach Runtime B; revision increments once per accepted event; router is closed before undo adapter cleanup; repeated Runtime close is safe.

- [ ] **Step 2: Run RED.**

```text
python -m pytest tests/integration/test_runtime_events.py tests/integration/test_event_publishing.py -q
```

Expected: failures because Runtime has no `event_router` integration.

- [ ] **Step 3: Integrate minimally.** Construct `RuntimeEventRouter(self)` in `LibraryRuntime.__init__`; call `event_router.close()` before entering adapter cleanup state. Do not change EventBus publish semantics or implement Task 10 transports.

- [ ] **Step 4: Run integration GREEN.**

```text
python -m pytest tests/integration/test_runtime_events.py tests/integration/test_event_publishing.py -q
```

Expected: all integration and lifecycle tests pass.

---

### Task 4: Full Task 9 verification and review gates

**Covers:** [S1], [S2], [S3], [S4], [S5], [S6], [S7], [S8], [S9], [S10]

**Files:**
- Review all Task 9 diff and the approved spec: `docs/compose/specs/2026-07-21-runtime-event-router-design.md`

- [ ] **Step 1: Run focused and regression tests.**

```text
python -m pytest tests/integration/test_runtime_events.py -q
python -m pytest tests/integration/test_runtime_events.py tests/integration/test_event_publishing.py -q
python -m pytest tests/unit/test_bootstrap.py tests/unit/test_library_runtime.py tests/integration/test_library_service.py -q
```

- [ ] **Step 2: Run static and boundary checks.**

```text
python -m ruff check AssetsManager/application/runtime_events.py AssetsManager/application/runtime.py tests/integration/test_runtime_events.py tests/integration/test_event_publishing.py
python -m compileall -q AssetsManager/application
python -m pytest tests/unit/test_architecture_boundaries.py -q
```

- [ ] **Step 3: Confirm non-goals.** Search the Task 9 diff for WebSocket DTOs, `run_coroutine_threadsafe`, `/api/revision`, React realtime provider changes, and unrelated route mutations. Any such change is out of scope and must be removed.

- [ ] **Step 4: Run broader regression proportional to risk.**

```text
python -m pytest tests/integration tests/lan -q
npm --prefix webui test -- --run
npm --prefix webui run typecheck
npm --prefix webui run build
git diff --check -- AssetsManager/application/runtime_events.py AssetsManager/application/runtime.py AssetsManager/application/bootstrap.py tests/integration/test_runtime_events.py tests/integration/test_event_publishing.py
```

- [ ] **Step 5: Obtain independent defect-first review.** Review mapping completeness, path safety, revision race behavior, subscription close/error isolation, Runtime close ordering, and Task 10 non-goals before reporting Task 9 complete.
