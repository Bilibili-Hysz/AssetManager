# C6-C10 证据收敛与残余边界（2026-08-21）

## 1. Snapshot Metadata

| Field | Value |
|---|---|
| Report ID | `c6-c10-convergence-2026-08-21` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; baseline captured before this report and manifest were added. |
| Status fingerprint | `e8a8685de4ed5fa7dd41eff364007f63dfdef4de046b125e9cdc719b968a7bdd` |
| Binary diff fingerprint | `8f3622fd02bcdcd547e362d98d9566b5635b2f1714ffa480f52cf202f4b5f75a` |
| Tracked / untracked changes | 93 / 38 before this report and manifest were added |
| Runtime | Windows 10.0.26220, Python 3.14.3, pytest 9.0.2, Ruff 0.14.10 |
| Validation state | Focused governance tests and static gates only; all findings remain `fixed-unverified`. |

This is a new dated snapshot. It does not rewrite the C6, C6-B, C7, C8, C9, or C10 reports/manifests. The machine-readable companion is [audit-manifest-c6-c10-convergence-2026-08-21.json](audit-manifest-c6-c10-convergence-2026-08-21.json).

## 2. Convergence Register

| Workstream | Latest evidence | Current status | What is superseded | What remains |
|---|---|---|---|---|
| C6 filesystem projection repair | [C6-min report](c6-min-durable-filesystem-projection-repair-evidence-2026-08-21.md) | `fixed-unverified` | Move/delete projection repair envelope and durable retry path | Filesystem and SQLite are not one atomic transaction; cross-process retry and downgrade policy remain |
| C6-B restore projection repair | [C6-B report](c6-b-restore-projection-repair-evidence-2026-08-21.md) | `fixed-unverified` | Restore tags/metadata/favorites/index snapshot replay | Thumbnail rows/bytes, rolling-version compatibility, and cross-system crash window remain |
| C7 watcher durable rescan | [C7 report](c7-min-watcher-durable-rescan-evidence-2026-08-21.md) | `fixed-unverified` | External-watch root rescan marker and bounded stop/join | In-place overwrite detection and durable scan cursor remain |
| C8 import partial contract | [C8 report](c8-min-import-partial-contract-evidence-2026-08-21.md) | `fixed-unverified` | Partial/degraded/cancelled result and index fallback | C10 partially supersedes the “no durable import intent” limitation; copy replay and outbox remain |
| C9 import UI/pool lifecycle | [C9 report](c9-min-import-ui-cancel-pool-lifecycle-evidence-2026-08-21.md) | `fixed-unverified` | Generation-guarded cancel/close cleanup and session lease drain | C10 only covers the previously stated import-intent gap; modal Windows lifecycle evidence and copy interruption remain |
| C10 durable import intent/recovery | [C10 report](c10-min-import-durable-intent-recovery-evidence-2026-08-21.md) | `fixed-unverified` | Pre-mutation manifest, per-item CAS state, restart-time root rescan enqueue | No automatic copy replay, durable event outbox, exactly-once import event, or cross-system atomicity |

### Explicit supersession relationships

- C10 partially supersedes C8's `C8-03` limitation: an import manifest now records intent before filesystem mutation and can trigger a restart-time root rescan.
- C10 partially supersedes the C9 report's “no import manifest/outbox” limitation only. It does not supersede C9's UI modal/lifecycle evidence gap, cooperative copy cancellation, or pool/lease behavior.
- C10 does not supersede C6/C6-B projection-repair boundaries, C7 watcher cursor/overwrite limitations, thumbnail restore, durable outbox design, or release/platform validation requirements.

These are scope relationships, not a claim that any finding is `verified-fixed`. Historical manifests intentionally retain their own status at their capture point.

## 3. Executed Evidence

The focused run captured fresh raw logs under `artifacts/evidence/2026-08-21/c6-c10-governance-final/`:

| Command | Pass criterion | Result artifact |
|---|---|---|
| `python -m pytest tests/unit/test_check_audit_reports.py -n 0 --basetemp=.zcode/pytest-governance-final` | Exit code 0 and all five governance tests pass | `pytest.stdout.log`, `pytest.stderr.log` |
| `python scripts/check_audit_reports.py` | Exit code 0; every dated report/manifest is indexed, paired, hashed, and structurally valid | `audit.stdout.log`, `audit.stderr.log` |
| `python scripts/check_doc_stats.py` | Exit code 0; README structural marker matches current source counts | `docstats.stdout.log`, `docstats.stderr.log` |
| `python -m compileall -q scripts tests/unit/test_check_audit_reports.py` | Exit code 0 | `compile.stdout.log`, `compile.stderr.log` |
| `python -m ruff check scripts/check_audit_reports.py tests/unit/test_check_audit_reports.py` | Exit code 0 | `ruff.stdout.log`, `ruff.stderr.log` |
| `git diff --check` | Exit code 0 | `diffcheck.stdout.log`, `diffcheck.stderr.log` |
| `python scripts/check_boundaries.py` | Exit code 0 | `boundaries.stdout.log`, `boundaries.stderr.log` |
| `python scripts/check_style_sources.py` | Exit code 0 | `style.stdout.log`, `style.stderr.log` |
| `python scripts/check_route_capabilities.py` | Exit code 0 | `routes.stdout.log`, `routes.stderr.log` |
| `python scripts/check_frontend_data_fetch.py` | Exit code 0 | `frontend.stdout.log`, `frontend.stderr.log` |
| `python scripts/check_layers.py` | Exit code 0 | `layers.stdout.log`, `layers.stderr.log` |

The first audit-validator capture occurred before this report and manifest existed and therefore returned exit code 1 for dangling new index targets; it is retained as a truthful ordering diagnostic. The final rerun after creating both files is the pass result referenced by the manifest.

The local focused pytest command uses `-n 0` and a repository-local basetemp because the default Windows pytest temp root is inaccessible in this environment (`WinError 5`). The validator fixture count is six after adding the artifact-digest regression case.

## 4. Non-goals and Remaining Evidence

- No full Python suite, browser E2E, real-backend LAN acceptance, dependency/CVE scan, package/release validation, performance benchmark, power-loss test, independent Windows lifecycle CI, or clean-checkout reproducibility run was executed.
- No full import copy replay policy, durable event outbox, exactly-once event dispatch, thumbnail snapshot schema, watcher scan cursor, or in-place overwrite detector was added.
- The manifest/recovery design does not make SQLite and filesystem effects one cross-system transaction; queue and refresh crash windows remain observable limitations.
- Existing focused results are local and cumulative dirty-worktree evidence. They do not establish independent commit-level reproduction.
- All C6-C10 findings remain `fixed-unverified`; no status is promoted by this register.
