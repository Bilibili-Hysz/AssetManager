# LAN Temporary ZIP Cancellation Cleanup Evidence (2026-08-26)

## Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `lan-zip-cancel-cleanup-evidence-2026-08-26` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; bounded LAN temporary ZIP cancellation-cleanup batch |
| Baseline status SHA-256 | `9048db17bbe494c015019123f0ddb9b01a9298e364705269bda6cd0bab1a2924` |
| Baseline diff SHA-256 | `41874d9a4a7ee8b5260b62ac2c157438fab0f4711ce1237160eef5b305db7b1f` |
| Baseline tracked / untracked entries | `154 / 142` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This append-only snapshot records cancellation-safe cleanup for temporary ZIPs created by LAN downloads and commerce directory delivery. The machine-readable companion is [audit-manifest-lan-zip-cancel-cleanup-evidence-2026-08-26.json](audit-manifest-lan-zip-cancel-cleanup-evidence-2026-08-26.json).

## Implemented contract

`build_zip_async()` now retains the executor future and awaits it through `asyncio.shield()`. If the request task is cancelled while the synchronous ZIP worker is still running, cleanup is registered on the inner future and removes the caller-owned temporary path only after the worker finishes or queued work is cancelled. If executor submission is rejected before a future is returned, the temporary path is removed immediately and the original exception is re-raised.

This helper-level change covers the directory download, batch download, and commerce directory-delivery call sites. Normal `None` results, quota rejection, post-build response cleanup, and delivery accounting semantics remain unchanged. The synchronous ZIP worker is not forcibly cancelled.

## Verification

### Focused LAN matrix

```text
python -m pytest -n 0 -q tests/lan/test_l3_thread_resources.py tests/lan/test_free_download_quota.py tests/lan/test_order_receipt_routes.py tests/lan/test_lan_api.py
```

Result: **264 passed**, exit code 0. Raw output: `artifacts/evidence/2026-08-26/lan-zip-cancel-cleanup/focused.stdout.log`.

The new lifecycle regressions cover both a running worker cancelled by the awaiting task and a rejected executor submission. The running-worker test releases the worker before asserting that the path is gone, proving cleanup does not race the active writer.

### Full Python suite

```text
python -m pytest -n 0 -q
```

Final result: **4053 passed, 16 skipped, 20 deselected, 2 warnings**, exit code 0, 627.63 seconds. Raw output: `artifacts/evidence/2026-08-26/lan-zip-cancel-cleanup/full.stdout.log`.

The skips are capability/platform-gated (Windows symlink privilege, POSIX flock recovery, and one nondeterministic Windows queue-termination boundary). The two warnings are the existing Qt signal disconnect warning and duplicate ZIP member warning; neither is caused by this batch.

### Static and repository gates

All of the following exited 0; outputs are recorded under `artifacts/evidence/2026-08-26/lan-zip-cancel-cleanup/`:

- targeted and full Ruff checks;
- targeted and full `compileall` checks;
- `git diff --check`;
- repository governance scripts: `check_doc_stats.py`, `check_boundaries.py`, `check_style_sources.py`, `check_route_capabilities.py`, `check_frontend_data_fetch.py`, and `check_layers.py`.

The independent `scripts/check_audit_reports.py` validator is run after this report, manifest, and index entry are written; its output is retained as a separate artifact and is intentionally not self-referenced by the manifest.

## Finding and boundaries

- `LAN-ZIP-CANCEL-CLEANUP-32-01` is **fixed-unverified**. Focused LAN cleanup coverage and the final full serial Python suite pass. The former cancellation leak is closed for the tested executor lifecycle: cleanup waits for the worker future rather than unlinking while the worker may still write.

The batch does not claim:

- cancellation of an already-running synchronous ZIP worker;
- power-loss safety, filesystem/SQLite/queue atomicity, or exactly-once execution;
- cross-process or Windows/POSIX replacement-race proof;
- production CDN/proxy/TLS behavior, browser E2E, dependency/CVE/release status, or clean-checkout reproducibility;
- a change to delivery `CancelledError` accounting or quota policy.

The ignored `.worktrees/grid-zoom-interpolation-fix` directory and frozen `DeepSeek Docs/` directory were not modified. No commit, push, release, revert, reset, clean, or dirty-worktree overwrite was performed.
