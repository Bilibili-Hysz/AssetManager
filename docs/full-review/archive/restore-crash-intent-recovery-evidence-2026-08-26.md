# Restore Crash Intent Recovery Evidence (2026-08-26)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `restore-crash-intent-recovery-evidence-2026-08-26` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; bounded interrupted-restore intent/recovery batch |
| Baseline status SHA-256 | `dc3cc2fd2cd9b0ae0527b4bcc589a413e3ff465c2bff2690851de44b24869c16` |
| Baseline diff SHA-256 | `d4eb539bba7b6527f250fd7fa61da0a5642d85b8ff1478c89a48853a438428db` |
| Baseline tracked / untracked entries | `163 / 152` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only snapshot closes the confirmed P2 crash window in the library backup restore: a process death between the quarantine replace and the install replace previously left no on-disk evidence, and the next open silently materialized an empty database while the previous copy sat undiscoverable in `_orphaned/restore-backups/`. The machine-readable companion is [audit-manifest-restore-crash-intent-recovery-evidence-2026-08-26.json](audit-manifest-restore-crash-intent-recovery-evidence-2026-08-26.json).

## Implemented contract

- **Intent marker** (`library_export_io.py`, pure functions): `. {data_dir.name}.restore-intent.json` written atomically (tempfile + fsync + `os.replace`) as a sibling of the data slot, recording token, map key, quarantine entry, staging path, and UTC start time. Reading is tolerant: absent/unreadable/corrupt all return None while corrupt bytes stay on disk for fail-closed judgment.
- **Write timing** (`_restore_under_reservation`): the marker is written after the quarantine entry path is known and before the first replace; cleared after the installed quick_check passes; and in the exception path cleared only when the final state is consistent (`data_dir` present — installed or rolled back). A still-absent data_dir keeps the marker so the next open retries recovery.
- **Open-time recovery** (`LibraryService._open`, under the cross-process library lock and before any `connection_for` call): no marker → behavior unchanged. Marker + data_dir present → stale evidence consumed, open proceeds. Marker + data_dir absent + usable quarantined previous copy (exists, not link/reparse, contained in RuntimeData, map key matches) → automatic rollback via `os.replace(previous, data_dir)`, marker consumed, warning logged, open continues with the user's old data.
- **Fail-closed deviation from the original plan, recorded deliberately**: when the quarantined entry is missing/unusable or the marker is unusable, the open raises a descriptive `RuntimeError` on every attempt instead of writing canonical restore poison. Investigation showed the bootstrap ACK wrapper pins acknowledgement tokens to the session-construction generation, so admission blocking at open time would create an unacknowledgeable lock with no reachable ACK surface. The durable on-disk marker itself keeps every later open failing shut until the operator restores the quarantined copy manually (existing settings-dialog tooling) or removes the marker after remediation. No silent empty-schema creation is possible in any branch.

## Verification

### Focused matrices

```text
python -m pytest -n 0 -q tests/unit/test_library_export_service.py
```

Result: **82 passed, 1 skipped**, exit code 0 (capability-gated directory-symlink skip). Raw output: `focused-export.stdout.log`.

```text
python -m pytest -n 0 -q tests/unit/test_library_service.py tests/integration/test_library_service.py
```

Result: exit code 0. Raw output: `focused-libservice.stdout.log`.

New regressions pin: marker presence across both replaces naming the live quarantine entry plus success cleanup; marker cleanup after an in-process rolled-back failure; end-to-end crash simulation (manual quarantine move + marker) where the next `open_session` restores the exact pre-crash directory contents and consumes marker/entry; fail-closed refusal (no DB file created, marker persists) when the quarantined entry is missing; stale-marker consumption after completed install; corrupt-marker cleanup; and the negative control that opening without any marker still creates a fresh library normally.

### Full Python suite

```text
python -m pytest -n 0 -q
```

Result: **4069 passed, 16 skipped, 20 deselected, 2 warnings**, exit code 0, 612.71 seconds. Raw output: `full.stdout.log`. Skips remain capability/platform-gated; the two warnings are pre-existing.

### Static and repository gates

Targeted Ruff (one unused import found and fixed), full Ruff, targeted compileall, full compileall, `git diff --check`, and the six governance scripts all exited 0. The independent audit-manifest validator runs after this report/manifest/index are written; its result is retained separately.

## Finding and boundaries

- `RESTORE-CRASH-INTENT-RECOVERY-36-01` is **fixed-unverified**: the tested crash-aftermath matrix and full serial suite pass on Windows. No real subprocess kill or power-loss test was executed — crash state is constructed by hand at the filesystem level; no claim of power-loss safety, exactly-once, cross-system atomicity, or race-proof replacement windows is made.
- Residuals recorded: orphan `.library-data.restore-*` staging directories are not swept; a crash between marker write and replace#1 leaves a harmless stale marker cleaned at next open; fail-closed states surface as repeated open errors rather than UI poison cards; crash-after-install leaves the previous copy in quarantine by design (discoverable via `list_restore_quarantine`).
- The frozen `DeepSeek Docs/` directory and ignored `.worktrees/grid-zoom-interpolation-fix` directory were not modified. No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
