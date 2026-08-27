# AssetsManager 审计证据收敛与修复排期（2026-08-20）

## 1. Snapshot Metadata

| Field | Value |
|---|---|
| Report ID | `evidence-convergence-2026-08-20` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; audit reports were read from the mutable worktree, not a clean checkout. |
| Tracked / untracked changes | 12 / 4 at capture time |
| Status fingerprint | `d133d64ccf7933b0e453cc48a7a2439643813af764801ac545ec3aaa2557d032` |
| Binary diff fingerprint | `093438bd7596a03cf01f90fdac01637c053cd862ea12e7e6ee10cd72510edcf3` |
| Validation state | Static evidence only. No test, service, browser, benchmark, package, dependency, vulnerability, or release workflow was run for this snapshot. |

The machine-readable companion is [audit-manifest-2026-08-20.json](audit-manifest-2026-08-20.json). It is the source of truth for input digests, canonical IDs, source IDs, anchors, and evidence statuses. A future run must create a new dated manifest rather than overwrite this one.

## 2. Scope and Inputs

This report converges the following discovery artifacts:

1. [Full modular scan](full-scan-2026-08-20.md).
2. [Cross-module flow and API audit](cross-module-flow-api-audit-2026-08-20.md).
3. [Performance and timing audit](performance-timing-audit-2026-08-20.md).
4. [Deep quality, architecture, worktree, documentation, and dependency audit](code-quality-architecture-worktree-dependency-audit-2026-08-20.md).

It does not claim that the source reports are an exhaustive dynamic security or performance assessment. `confirmed` means the static code/configuration fact and its direct local contract are established. `conditional` means the design hazard is established but the operating behavior, exploitability, or practical magnitude remains to be measured. `verified-fixed` is unavailable until a dated command/result artifact is attached to a later manifest.

## 3. Canonical Register

The manifest defines thirteen initial canonical findings. The register intentionally preserves source IDs rather than creating a replacement numbering system.

| Canonical issue | Source IDs consolidated | Status | Next action |
|---|---|---|---|
| EVID-01 Share preview policy parity | `P1-01` | Confirmed | `S1`: reuse verified/blur/cache policy and add LAN integration tests. |
| EVID-02 LAN auth/event-loop blocking | `P1-08`, `PT-01`, `PT-02` | Confirmed | `S2`: define credential authority and move the full synchronous chain behind bounded execution. |
| EVID-03 POSIX stale library lock | `P1-09` | Confirmed | `S4`: two-process POSIX proof before changing lock recovery. |
| EVID-04 Release/dependency provenance | `P1-12`, `GOV-01` to `GOV-03` | Confirmed | `G1/G2`: lock, action SHA, minimal permission, immutable release inputs. |
| EVID-05 After-commit event timing | `XFS-05`, `CQ-11` | Confirmed | `C3`: establish one write-scope and rollback oracle. |
| EVID-06 Session-bound persistence | `CQ-01`, `CQ-02`, `CQ-14`, `XFS-09` | Confirmed | `C2/C3`: remove raw override from session mode and normalize transaction ownership. |
| EVID-07 LAN/WebUI contract drift | `XAPI-02`, `XAPI-05` to `XAPI-07`, `CQ-16` | Confirmed | `C1`: typed errors, Gallery union, timestamp/DTO parity. |
| EVID-08 Desktop drop error truthfulness | `WT-02` | Confirmed | `PC-2`: result-or-error completion payload. |
| EVID-09 Desktop cover callback affinity | `WT-01` | Conditional | `PC-1`: real-PySide thread test, then QObject-bound queued bridge. |
| EVID-10 Private pool destruction | `WT-03` | Conditional | `PC-3`: blocked-runnable destruction test, then retain timed-out pool if required. |
| EVID-11 Watcher/Gallery fallback | `PT-09` | Confirmed | Warm-gallery `external_watch` test and wide-tree benchmark. |
| EVID-12 Decode stderr mutex | `PT-07` | Confirmed | Concurrent lock wait/hold benchmark and narrower suppression design. |
| EVID-13 HTTP exception response consistency | `XAPI-01` | Conditional | Route/status matrix before a global mapper change. |

Secondary findings remain in their source reports and must be added to a later canonical register before implementation begins. This first register covers the cross-report duplicates, disputed findings, current Desktop precommit risks, and the highest-impact architectural workstreams.

## 4. Corrections and Evidence-Level Changes

The following entries correct prior wording without erasing the original source IDs.

### PT-09: Watcher/Gallery causal chain

`LibraryWatcherService` uses a list FIFO with `pop(0)`, which is a static wide-tree complexity concern at `AssetsManager/application/library_watcher_service.py:72,138,144`. It publishes `external_watch` at `:199`. A warm Gallery receives the event through incremental handling, but `_apply_change` has no `external_watch` branch; fallback invalidates cached/persisted projection and schedules a debounced full build at `AssetsManager/application/gallery/_incremental.py:78,168,253,365`.

The corrected claim is: **`external_watch` is unsupported by incremental apply and invalidates a warm projection for a debounced full rebuild.** The practical rebuild rate, cache-unavailable duration, and wide-tree latency require measurement. The earlier phrase that every nonempty watcher round immediately triggers a full rebuild is withdrawn.

### PT-07: Decode serialization scope

`_suppress_libpng_warnings()` holds a process-global stderr mutex across current `QImageReader.read()` call sites at `AssetsManager/panels/file_list/_loader.py:102,198,936,997` and `AssetsManager/panels/image_viewer.py:70`. It therefore serializes those protected read sections and can suppress unrelated process stderr.

The corrected claim is not that the entire decode pipeline has concurrency one. Header inspection, scheduling, cache work, and other unprotected activity may still be concurrent. Throughput loss is a benchmark question.

### WT-01: Cover callback affinity

`_CoverScanSignals.done` is emitted from worker work at `AssetsManager/panels/file_list/_base_logic.py:53,73`, but is connected to a local closure at `:533,539` rather than a QObject receiver with an explicit queued connection. The callback mutates panel state at `:547`.

The corrected status is **conditional**: the code does not establish a GUI-thread guarantee, but static review alone does not prove the actual PySide delivery thread. The next test records worker and result-handler thread identities while pumping the Qt event loop. The target implementation is the repository's parented QObject/queued bridge pattern in `AssetsManager/panels/_event_bridge.py:10`.

### WT-03: Timed pool drain and destruction

`BoundedPool.drain()` only delegates to timed `waitForDone` at `AssetsManager/core/workers.py:100`. FileList cancels, drains, and releases its pool reference at `AssetsManager/panels/file_list/_base.py:130`; Viewer retains the pool through close until owner destruction at `AssetsManager/panels/image_viewer.py:879`.

The corrected status is **conditional**: releasing the final wrapper after a failed timed drain is a lifecycle hazard because Qt documents a waiting pool destructor, but the exact PySide destruction timing and user-visible stall require a blocked-runnable destruction test on the target platform.

### XAPI-01: HTTP exception response scope

The prior generic wording is narrowed. The established issue is a **route-contract inconsistency** for exact JSON endpoint/status paths that re-raise aiohttp exceptions, including Gallery at `AssetsManager/lan/routes/gallery.py:85` and path validation at `AssetsManager/lan/routes/_helpers.py:393`. Whether a global middleware already normalizes every affected exception must be established by an endpoint/status response matrix before introducing a global mapper.

### Cross-module path correction

References to obsolete `webui/src/context/AuthContext.tsx` and `SellerAuthContext` paths are corrected to `webui/src/stores/AuthContext.tsx` and `webui/src/stores/SellerAuthContext.tsx`. The seller logout wiring evidence itself remains at `webui/src/components/storefront/StorefrontShell.tsx:109-116`.

## 5. Evidence Plan

| Workstream | Deterministic oracle | Required evidence | Gate |
|---|---|---|---|
| `PC-1` cover callback | Handler thread equals GUI thread | Qt thread identity trace | Desktop + Windows lifecycle |
| `PC-2` drop completion | Closed session/service exception produces error, never zero-success | Focused Desktop tests | PR |
| `PC-3` pool teardown | Close and deletion preserve bounded latency with blocked runnable | Qt timing trace | Windows lifecycle |
| Gallery watcher | One fallback/rebuild for warm `external_watch` batch | Integration fixture, 10k/50k benchmark | PR small + nightly large |
| Decode mutex | Protected read wait/hold and p95 under concurrent loaders | Benchmark JSON with fixture metadata | Nightly |
| Auth offload | Loop ticker progresses under login/DB lock | Async LAN timing fixture | PR deterministic |
| Transaction contract | Rollback yields no event/forced commit | Repository/service integration matrix | PR |
| Release provenance | Clean locked build uses immutable CI revision | Workflow artifacts with digest | Release |

Every dynamic result must append a new dated manifest/report entry with platform, command, tool version, fixture size, sample count, output digest, and pass/fail criterion. A passed default `pytest` invocation is not substitute evidence for excluded `e2e`/`perf` markers.

## 6. Repair Schedule

### Phase 0: Desktop precommit isolation, 1-2 days

Deliver `PC-1`, `PC-2`, and `PC-3` in one Desktop-only branch after their real Qt tests pass. Keep navigation, EXIF, cover-cache, and strip queue observations as separate P2 work. Do not combine this batch with LAN, repository, documentation, or release refactors.

### Phase 1: Security and availability containment, 1-2 weeks

Run `S1` share/media policy parity, `S2` auth authority/event-loop containment, `S3` media/ZIP admission budgets, `S4` POSIX stale-lock validation, and `S5` WebUI credential/cache corrections in parallel where their identity contract does not overlap. `S2` defines the authority/generation semantics used by `S5`.

### Phase 2: Contract and transaction foundations, 2-4 weeks

Sequence `C1` HTTP/TS contract, `C2` session-bound composition, `C3` transaction/after-commit ownership, `C4` filesystem repair envelope, and `C5` lifecycle hard gate. `C3` must precede durable repair and realtime replay because operation completion cannot be represented correctly before transaction ownership is explicit.

### Phase 3: Scalability and platform boundaries, 3-6 weeks

Design a per-platform final-open boundary, projection/read scaling, bounded ordered realtime delivery, and plugin contribution ownership only after Phase 2 contracts stabilize. Final-open must have independent POSIX symlink-swap and Windows reparse-point coverage.

### Phase 4: Release and governance, starts now and becomes enforcing after Phase 2

Introduce Python locks/hashes, Action SHA pinning, minimal workflow permissions, SBOM/license/NOTICE, bundle manifest/digest/provenance, and release consumption of a passed immutable revision. Keep deterministic checks in PR lanes; reserve capacity, browser, filesystem, and large-media evidence for nightly or release lanes.

## 7. Acceptance Rules

1. Do not mark a finding `verified-fixed` without a command/result artifact linked from a later manifest.
2. Keep each repair commit inside one boundary: Desktop async, LAN/API/transaction, WebUI contract, or documentation/governance.
3. Run `python scripts/check_audit_reports.py`, `python scripts/check_doc_stats.py`, generator/boundary/layer gates, and `git diff --check` for documentation/governance changes.
4. Treat `docs/full-review/` as dated evidence snapshots. Current code and CI configuration remain the executable authority.
