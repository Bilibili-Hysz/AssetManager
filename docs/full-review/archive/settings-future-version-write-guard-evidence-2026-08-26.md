# Future-Version Settings Write Guard Evidence (2026-08-26)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `settings-future-version-write-guard-evidence-2026-08-26` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; bounded core settings future-version protection batch |
| Baseline status SHA-256 | `1b1f6ede3eb0307afa575afe9e50b37ebab103ede3be01ff5b70d0e8bc975572` |
| Baseline diff SHA-256 | `0bbcd5ab96fe65ec8586a1743a84eb37806bbe0c47471f9de47023febffedf8f` |
| Baseline tracked / untracked entries | `158 / 144` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only snapshot records fail-closed protection for settings files written by a newer application version. The machine-readable companion is [audit-manifest-settings-future-version-write-guard-evidence-2026-08-26.json](audit-manifest-settings-future-version-write-guard-evidence-2026-08-26.json).

## Implemented contract

- `config_migrator.migrate()` now raises a dedicated `FutureConfigVersionError` for `_cfg_version > CURRENT_VERSION`, while preserving the existing `ValueError` compatibility and leaving the input mapping unchanged before rejection.
- `AppSettings.load()` records the newer version, clears any stale in-memory snapshot, skips legacy migration, keeps `_dirty` false, and leaves the future-version file untouched. The instance exposes `is_write_blocked` for callers that need to distinguish this state.
- All settings mutation and persistence boundaries are guarded: scalar/list writes, LAN security history writes and commits, `save()`, and `_atexit_save()`. Blocked writes do not validate-and-mutate, create temporary files, replace the newer file, or change dirty state.
- `library_manager.record_visit()` and `remove()` return without mutating the live settings dictionary when the settings instance is write-blocked; `_save()` also has a defensive guard. Read-only settings/library queries remain available.
- Existing supported-version migration and atomic-save behavior remain unchanged.

## Verification

### Focused settings matrix

```text
python -m pytest -n 0 -q tests/core/test_settings.py tests/unit/test_settings_low_batch.py
```

Result: **45 passed**, exit code 0. The new regressions cover future-version rejection without input mutation, exact file preservation, blocked setters/list/security/commit/atexit writes, legacy migration suppression, and library-manager write suppression.

### Expanded core matrix

```text
python -m pytest -n 0 -q tests/core/test_settings.py tests/unit/test_settings_low_batch.py tests/unit/test_library_settings_adapter.py tests/unit/test_project_data.py
```

Result: **70 passed**, exit code 0. The run emitted pre-existing unclosed SQLite `ResourceWarning` lines after test completion; no test failed and the warnings were not introduced by the settings guard. Raw focused output is retained at `artifacts/evidence/2026-08-26/settings-future-version/focused.stdout.log`.

### Full Python suite

```text
python -m pytest -n 0 -q
```

Result: **4055 passed, 16 skipped, 20 deselected, 2 warnings**, exit code 0, 645.20 seconds. Raw output: `artifacts/evidence/2026-08-26/settings-future-version/full.stdout.log`.

The two pytest summary warnings are the existing Qt signal disconnect warning and duplicate ZIP member warning. Platform-gated skips include Windows symlink privilege, POSIX flock recovery, and the nondeterministic Windows queue-termination boundary.

### Static and repository gates

All of the following exited 0; outputs are recorded under `artifacts/evidence/2026-08-26/settings-future-version/`:

- targeted and full Ruff checks;
- targeted and full `compileall` checks;
- `git diff --check`;
- repository governance scripts: `check_doc_stats.py`, `check_boundaries.py`, `check_style_sources.py`, `check_route_capabilities.py`, `check_frontend_data_fetch.py`, and `check_layers.py`.

The independent `scripts/check_audit_reports.py` validator is run after this report, manifest, and index entry are written. Its output is retained as an artifact but is intentionally not self-referenced by the manifest.

## Finding and boundaries

- `SETTINGS-FUTURE-VERSION-GUARD-33-01` is **fixed-unverified**. Focused, expanded, and full serial suites pass. A newer settings payload remains preserved and all tested write paths fail closed. The status remains conservative because no multi-process settings race, cross-version runtime compatibility run, power-loss test, or clean-checkout run was performed.

The batch does not claim:

- compatibility with unknown future setting semantics beyond preserving the file and blocking writes;
- multi-process locking or replacement-race proof;
- power-loss safety, filesystem/SQLite/queue atomicity, or exactly-once execution;
- production E2E, dependency/CVE/release status, or clean-checkout reproducibility.

The independent Shop partial-update metadata-loss finding remains a separate unimplemented batch. The frozen `DeepSeek Docs/` directory and ignored `.worktrees/grid-zoom-interpolation-fix` directory were not modified. No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
