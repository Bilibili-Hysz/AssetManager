# Import Hardening Convergence Evidence (2026-08-25)

## 1. Snapshot Metadata

| Field | Value |
|---|---|
| Report ID | `import-hardening-convergence-evidence-2026-08-25` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; convergence snapshot for batches 28-A/29/28-B/28-C/28-D |
| Baseline status SHA-256 | `9830c568db7d31138c4458bff2b36fbfa76c990726bfe5e6dc5ff9a6defb5ad0` |
| Baseline diff SHA-256 | `5c272f4d94e0387f4a54925fa6fbaf16c82af8ba54315134300081d004c13a8e` |
| Baseline tracked / untracked entries | `143 / 127` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |
| Validation state | Dynamic (focused import matrix + static governance); full-suite green evidence inherited from the same-day 28-D snapshot |

This is a new dated convergence snapshot. It does not rewrite the 28-A, 29, 28-B, 28-C, or 28-D reports or manifests; those snapshots keep their captured-point status. The machine-readable companion is [audit-manifest-import-hardening-convergence-evidence-2026-08-25.json](audit-manifest-import-hardening-convergence-evidence-2026-08-25.json).

## 2. Convergence Register

| Workstream | Latest evidence | Current status | What is superseded | What remains |
|---|---|---|---|---|
| Import atomic no-overwrite copy (28-A) | [import-no-overwrite-atomic-copy-evidence-2026-08-23.md](import-no-overwrite-atomic-copy-evidence-2026-08-23.md) | fixed-unverified | Pre-existing ancestor-link escape window closed by 28-B admission (partial; see relations below) | Post-open reparse/junction replacement races, POSIX dirfd/openat proof, power-loss |
| Batch move transaction boundary (29) | [batch-move-transaction-boundary-evidence-2026-08-23.md](batch-move-transaction-boundary-evidence-2026-08-23.md) | verified-fixed | — (standalone contract, verified by focused + full suite at its capture point) | Mid-batch transaction-open races, restore_backup admission, filesystem rollback via savepoints |
| Destination ancestor link admission (28-B) | [import-ancestor-link-admission-evidence-2026-08-23.md](import-ancestor-link-admission-evidence-2026-08-23.md) | fixed-unverified | Closes the documented nested pre-existing symlink/junction escape of 28-A for admission-time checks | Link replacement between checks, Windows native reparse-safe handles, source-link policy |
| Explicit replay / idempotency (28-C) | [import-copy-replay-idempotency-evidence-2026-08-25.md](import-copy-replay-idempotency-evidence-2026-08-25.md) | fixed-unverified | Replay update-exception crash, silent index desync, ignored finish result, ambiguous claim race — compensated by 28-D (partial) | Exactly-once execution, item-level SQLite copy ledger/outbox, fingerprint-to-copy TOCTOU, global same-content dedup |
| Filesystem/DB/queue compensation (28-D) | [import-filesystem-db-queue-consistency-evidence-2026-08-25.md](import-filesystem-db-queue-consistency-evidence-2026-08-25.md) | fixed-unverified | Cancellation intent loss and replay compensation gaps from earlier batches' deferred work | Cross-system atomicity, power-loss windows inside recover(), completed-with-pending-items bookkeeping semantics |

### Explicit supersession relationships

- `IMPORT-ANCESTOR-LINK-ADMISSION-28B-01` partially supersedes `IMPORT-COPY-NO-OVERWRITE-28A-01`: the destination/relative-parent link/reparse admission rejects the pre-existing nested-link escape that 28-A documented as unverified. The post-open replacement race window remains owned by 28-A's remaining boundary.
- `IMPORT-FSQ-COMPENSATION-28D-01` partially supersedes `IMPORT-COPY-REPLAY-IDEMPOTENCY-28C-01`: 28-D implemented the replay robustness gaps that 28-C explicitly deferred (per-item update exceptions, finish failure compensation, claim-race determinism, replay index synchronization). Exactly-once execution and power-loss safety stay open in both.

These are scope relationships only, not status promotions. Historical manifests keep the status recorded at their capture point; no finding is upgraded to `verified-fixed` by this snapshot.

## 3. Executed Evidence

| Command | Pass criterion | Result artifact |
|---|---|---|
| `python -m pytest -n 0 -q tests/integration/test_import_service.py tests/integration/test_import_subprocess_termination.py tests/unit/test_import_manifest_store.py tests/integration/test_import_manifest_recovery_claim_process.py tests/integration/test_reconciliation_queue_sqlite_runtime.py` | exit 0; platform-gated skips recorded | **55 passed, 2 skipped** in 17.03s → `artifacts/evidence/2026-08-25/import-hardening-convergence/focused.stdout.log` |
| Static chain: doc stats, boundaries, style sources, route capabilities, frontend data fetch, layers, full Ruff, compileall, `git diff --check` | each command exits 0 | `artifacts/evidence/2026-08-25/import-hardening-convergence/static-post-index.stdout.log` |
| `python scripts/check_audit_reports.py` (run separately to avoid self-referential hashing) | exit 0 | validator console output recorded at execution time |

The latest full serial Python suite remains the green 28-D run archived at `artifacts/evidence/2026-08-25/import-filesystem-db-queue-consistency/full.stdout.log` (**4033 passed, 16 skipped, 20 deselected, 2 warnings**, exit 0); no production bytes changed after that run in this batch. README statistics were independently re-verified against actual repository measurements (`python_test_files=277`, schema version 34) with no drift. The xdist default lane stays unusable on this host (worker temp-directory `PermissionError: [WinError 5]`), so all suite evidence uses `-n 0`.

## 4. Non-goals and Remaining Evidence

The following remain explicitly unverified or out of scope across all five workstreams:

- No cross-system atomicity: filesystem copy, SQLite CAS, and queue enqueue remain separate non-transactional systems; savepoints do not roll back filesystem mutations.
- No power-loss safety or exactly-once execution claim anywhere in the import pipeline.
- Windows reparse-point/junction replacement races and root-directory replacement remain unproven; Windows has no `O_NOFOLLOW` equivalent on this path.
- POSIX dirfd/openat no-follow directory traversal was not implemented.
- Process-kill windows inside `recover()` between claim/enqueue/finish were exercised only with monkeypatch-level fault injection, not real subprocess kills.
- Fingerprint-to-copy TOCTOU (source mutated between fingerprinting and streaming) remains open.
- Restart recovery still marks manifests containing pending items as `completed` after the root rescan — a documented bookkeeping semantics choice with manual `replay_import` as the item-level exit.
- Restore backup existing-target admission, E2E browser flows, LAN intermediary behavior, CVE/dependency status, performance benchmarks, package/release integrity, and clean-checkout behavior are separate work streams not covered here.

No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
