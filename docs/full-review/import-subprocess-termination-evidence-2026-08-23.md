# Import Subprocess Termination / Restart Checkpoint Evidence (2026-08-23)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `import-subprocess-termination-evidence-2026-08-23` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; bounded import child-termination/restart checkpoint batch |
| Baseline status SHA-256 | `a975e0e19105d0f22bf13dc7b4d5d77abfe5e5f3ca0e4d9bb6d84df4fdf40893` |
| Baseline diff SHA-256 | `d85b9f175a78fa141990de2417a596f0847e4bf69c6fe64571999736a874cbca` |
| Baseline tracked / untracked entries | `143 / 110` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only snapshot records bounded subprocess termination checkpoints around the existing synchronous ImportService. Finding ID: `IMPORT-SUBPROCESS-TERMINATION-01`. The machine-readable companion is [audit-manifest-import-subprocess-termination-evidence-2026-08-23.json](audit-manifest-import-subprocess-termination-evidence-2026-08-23.json).

## Implemented contract

- The production import architecture remains unchanged: `ImportService.import_sources()` is synchronous and the desktop UI wraps it in a Qt worker. The new test harness starts a separate Python child only to exercise the real service and terminate it at controlled persistence boundaries.
- A Windows-safe child harness uses `sys.executable -c`, atomic JSON handshakes, bounded polling, `terminate()` and bounded `kill()` fallback. It covers `before_copy`, `after_copy_before_item_update`, and `after_item_update_before_finish`.
- After child termination, a newly opened `ApplicationBootstrap` discovers the durable manifest and performs the existing root projection recovery. The original `operation_id` is retained, the manifest reaches the existing terminal `completed` state, and the recovery task remains a single deduplicated queue task across a second reopen.
- The `after_copy_before_item_update` case proves the already-copied target remains unchanged and that restart recovery does not invoke `shutil.copy2` again. This is no-replay behavior for the tested projection-recovery path, not a general copy idempotency contract.
- The late-cancellation branch now applies the same copied-output compensation as the earlier cancellation checkpoint: when the last item has been copied and cancellation is observed, it enqueues `import_partial` without refreshing or publishing an import event.

## Verification

### Focused matrix

```text
python -m pytest -n 0 -q tests/integration/test_import_subprocess_termination.py tests/unit/test_import_manifest_store.py tests/integration/test_import_service.py tests/integration/test_reconciliation_queue_process_termination_subprocess.py tests/integration/test_reconciliation_queue_process_matrix.py tests/integration/test_reconciliation_queue_fault_injection.py tests/integration/test_reconciliation_queue_external_lock.py
```

Result: **32 passed, 0 failed**, exit code 0, 14.03 seconds. Raw output: `artifacts/evidence/2026-08-23/import-subprocess-termination/focused.stdout.log`.

Coverage includes three real ImportService child-termination checkpoints, restart-time manifest recovery, queue task deduplication, no-copy-replay assertion, manifest terminal/CAS behavior, late cancellation compensation, and existing reconciliation subprocess/process/lock recovery.

### Full Python suite

```text
python -W error::RuntimeWarning -m pytest --basetemp=.zcode/pytest-batch26b-full -n 0 -q
```

Result: **4002 passed, 14 skipped, 20 deselected, 2 warnings**, exit code 0, 577.16 seconds. Raw output: `artifacts/evidence/2026-08-23/import-subprocess-termination/full.stdout.log`.

The skipped cases include platform-limited POSIX flock and symlink/junction fixtures, plus the pre-existing nondeterministic multiprocessing Queue termination module. The new subprocess-based import test itself passed on Windows.

### Static/governance gates

The final combined chain passed: audit manifest validation, README statistics, boundary checks, style-source checks, route capability checks, frontend data-fetch checks, layer DAG checks, Ruff, compileall, and `git diff --check`. Raw output: `artifacts/evidence/2026-08-23/import-subprocess-termination/static.stdout.log`; Git line-ending warnings are recorded in `static.stderr.log`.

The first static attempt stopped at the expected README statistics gate because adding the new test file changed `python_test_files` from 275 to 276. README was updated to 276 and the complete chain was rerun successfully; the final artifact is the authoritative result.

## Evidence boundaries

This batch demonstrates abrupt termination after explicit test checkpoints in a Windows child process and restart-time durable-intent projection recovery. It does **not** demonstrate power-loss safety, filesystem durability after hardware failure, filesystem/SQLite/queue cross-system atomicity, atomic no-overwrite under concurrent target creation, symlink/junction race resistance, or a general copy replay/idempotency key. Production CDN/intermediary behavior, POSIX filesystem races, package/release integrity, CVE/dependency status, performance, and clean-checkout behavior remain **fixed-unverified**. No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
