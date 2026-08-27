# Restore Backup Fail-Closed Admission Evidence (2026-08-26)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `restore-backup-fail-closed-admission-evidence-2026-08-26` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; bounded restore target-admission hardening batch |
| Baseline status SHA-256 | `79c08bdc098d7ff840903d09a070207769415b76157133535dde315c9fecbd01` |
| Baseline diff SHA-256 | `ddb50f55ee393e386b160871ad6b968cda4258144202d9932df71cc775013a98` |
| Baseline tracked / untracked entries | `153 / 140` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only snapshot records the fail-closed target admission fix for `restore_backup`. The machine-readable companion is [audit-manifest-restore-backup-fail-closed-admission-evidence-2026-08-26.json](audit-manifest-restore-backup-fail-closed-admission-evidence-2026-08-26.json).

## Implemented contract

`FileOperationService.restore_backup()` now checks `os.path.lexists(target)` while holding its existing process-local destination path lock and before entering the copy `try` block. An existing regular file, directory, or dangling link therefore raises `FileExistsError` with a no-overwrite message before any copy, partial-target cleanup, projection mutation, or `FileSystemChanged(kind="restored")` publication. This aligns direct callers with the existing undo caller admission policy and prevents the former `copy2` overwrite plus broad cleanup path.

The successful absent-target copy path, index refresh ordering, projection snapshot handling, and repair queue behavior are unchanged. The implementation does not introduce staging or replacement semantics for directory restores.

## Verification

### Focused restore matrix

```text
python -m pytest -n 0 -q tests/integration/test_file_operation_service.py tests/unit/test_undo_low_batch.py
```

Result: **62 passed**, exit code 0. Raw output: `artifacts/evidence/2026-08-26/restore-backup-admission/focused.stdout.log`.

The newly added conflict regressions are:

- existing file target remains byte-for-byte unchanged and emits no `restored` event;
- existing directory target and sentinel child remain unchanged, with no cleanup and no `restored` event;
- the existing absent-target directory restore still verifies index visibility before event publication.

### Full Python suite

The first serial run reached one unrelated pre-existing viewer-cache assertion failure (`os.scandir` count 3 rather than 2 in `test_viewer_directory_scan_is_cached_per_directory`). The failure is outside the restore call path and concerns exact directory-mtime cache equality. Its raw output is retained at `artifacts/evidence/2026-08-26/restore-backup-admission/full-first-run.stdout.log`; the isolated test was then rerun and passed.

A second serial run completed successfully:

```text
python -m pytest -n 0 -q
```

Final result: **4051 passed, 16 skipped, 20 deselected, 2 warnings**, exit code 0, 624.55 seconds. Raw output: `artifacts/evidence/2026-08-26/restore-backup-admission/full.stdout.log`.

The skips are capability/platform-gated (Windows symlink privilege, POSIX flock recovery, and one nondeterministic Windows queue-termination boundary). The two warnings are the existing Qt signal disconnect warning and duplicate ZIP member warning; neither is caused by this batch.

### Static and repository gates

All of the following exited 0; outputs are recorded under `artifacts/evidence/2026-08-26/restore-backup-admission/`:

- targeted and full Ruff checks;
- targeted and full `compileall` checks;
- `git diff --check`;
- repository governance scripts: `check_doc_stats.py`, `check_boundaries.py`, `check_style_sources.py`, `check_route_capabilities.py`, `check_frontend_data_fetch.py`, and `check_layers.py`.

The independent `scripts/check_audit_reports.py` validator is run after this report, manifest, and index entry are written; its output is retained as a separate artifact.

## Finding and boundaries

- `RESTORE-BACKUP-TARGET-ADMISSION-31-01` is **fixed-unverified**. The locked `lexists` guard and file/directory preservation regressions pass in the focused matrix and the full serial Python suite. The status remains conservative because no cross-process race test, power-loss test, or clean-checkout run was performed.

The guard closes the direct pre-existing-target overwrite/deletion path. It does not claim:

- cross-process or Windows/POSIX replacement-race proof beyond the existing in-process path lock;
- power-loss safety, filesystem/SQLite/queue atomicity, or exactly-once execution;
- recursive directory staging, quarantine, or crash recovery for restore replacement;
- production LAN/CDN/proxy behavior, browser E2E, dependency/CVE/release status, or clean-checkout reproducibility.

The ignored `.worktrees/grid-zoom-interpolation-fix` directory was inspected only as an unmanaged nested copy and was not modified or removed. No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
