# Cache, Failure-Map, Quota Hygiene and DeepSeek Archive Evidence (2026-08-25)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `cache-failure-quota-hygiene-deepseek-archive-evidence-2026-08-25` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; bounded low-risk hygiene and selective documentation migration batch |
| Baseline status SHA-256 | `9f3dba02940c3879d9c1ad3fe8b5b475ebf19590e46e219695588f8f3f35bea7` |
| Baseline diff SHA-256 | `0756d33eefc8c50534dd618b0e52420e66c2321e996c4f3875f15eb60032212f` |
| Baseline tracked / untracked entries | `153 / 138` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only snapshot records four bounded housekeeping changes and the approved DeepSeek Docs option B migration. The machine-readable companion is [audit-manifest-cache-failure-quota-hygiene-deepseek-archive-evidence-2026-08-25.json](audit-manifest-cache-failure-quota-hygiene-deepseek-archive-evidence-2026-08-25.json).

## Implemented contract

- **Metadata size-cache timestamps**: `MetadataService._mark_size_cached()` performs an opportunistic TTL sweep under the existing lock. Entries that can no longer satisfy the freshness test are removed; the current key is recorded normally. This bounds stale timestamp retention without changing the size result contract.
- **Share password failures and delivery claim failures**: each existing write path now removes globally stale keys after recording the current failure. The existing per-key pruning and cooldown/window semantics remain in place. This bounds memory growth from identifiers or remote addresses that are not accessed again.
- **Free-download quota history**: `FreeDownloadQuotaRepository.prune_windows()` is a separate transaction from the hot `consume()` path. `FreeDownloadQuotaService.prune_stale_windows()` computes a conservative cutoff and keeps two previous periods by default. LAN service resolution invokes this maintenance once per service lifetime and logs maintenance errors without breaking request service resolution.
- **DeepSeek Docs option B**: eight selected files were copied verbatim, with migration banners, into `docs/reports/deepseek-archive-2026-08-25/`. The original `DeepSeek Docs/` directory was not modified and remains the frozen historical source. Unselected documents remain available in that directory; current facts continue to belong to code, `docs/architecture.md`, and `docs/full-review/`.

## Verification

### Focused regression matrix

```text
python -m pytest -n 0 -q tests/integration/test_metadata_service.py tests/integration/test_share_service.py tests/lan/test_share_claim_routes.py tests/unit/test_free_download_quota.py
```

Result: **95 passed**, exit code 0. Raw output: `artifacts/evidence/2026-08-25/hygiene-deepseek/focused.stdout.log`.

### Full Python suite

```text
python -m pytest -n 0 -q
```

Final result: **4049 passed, 16 skipped, 20 deselected, 2 warnings**, exit code 0, 612.48 seconds. Raw output: `artifacts/evidence/2026-08-25/hygiene-deepseek/full.stdout.log`.

### Static and repository gates

The following gates exited 0; their stdout/stderr artifacts are recorded under `artifacts/evidence/2026-08-25/hygiene-deepseek/`:

- repository governance scripts: `check_doc_stats.py`, `check_boundaries.py`, `check_style_sources.py`, `check_route_capabilities.py`, `check_frontend_data_fetch.py`, and `check_layers.py`;
- `python -m ruff check AssetsManager tests scripts run.py`;
- `python -m compileall AssetsManager -q`;
- `git diff --check`.

The independent `scripts/check_audit_reports.py` validator is run after this report and its index/manifest links are written; its result is kept as a separate validator artifact.

## Findings and boundaries

- `CACHE-SIZE-TIMESTAMP-HYGIENE-2026-08-25` is **fixed-unverified**. Focused and full regression suites pass, but no long-running memory benchmark was performed. The sweep is opportunistic and does not claim a global memory ceiling under arbitrary clock behavior.
- `FAILURE-MAP-HYGIENE-2026-08-25` is **fixed-unverified**. Share and delivery stale-key regressions pass. No production traffic soak or cross-process memory behavior was measured; the maps remain process-local by design.
- `FREE-QUOTA-HISTORY-PRUNE-2026-08-25` is **fixed-unverified**. Repository/service boundary tests and the full suite pass. The maintenance call is opportunistic, retains two prior periods conservatively, and is not a claim of cross-process exactly-once maintenance, clock correctness, or power-loss durability.
- `DEEPSEEK-SELECTIVE-ARCHIVE-2026-08-25` is **fixed-unverified**. The archive inventory and provenance are recorded in `docs/reports/deepseek-archive-2026-08-25/INDEX.md`; this batch did not rewrite historical links or remove the original directory. The copied documents remain historical snapshots and are not current implementation authority.

Not established by this batch: production LAN/CDN/proxy behavior, browser E2E behavior, benchmark results, dependency/CVE/release status, clean-checkout reproducibility, power-loss safety, cross-system atomicity, exactly-once semantics, or race-proof behavior across Windows/POSIX replacement windows. No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
