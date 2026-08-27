# Free Download Quota Maintenance Cadence and Retry Evidence (2026-08-26)

## Scope
Finding `FREE-QUOTA-MAINTENANCE-CADENCE-38-01` covered the cached LAN quota service performing stale-window maintenance only once and lacking bounded retry after SQLite lock contention. The implementation adds a process-local monotonic maintenance gate, short retry-after-failure, complete-transaction SQLite busy retry for global pruning, and fail-closed download handling for quota-store errors.

## Changes
- `FreeDownloadQuotaService.maybe_prune_stale_windows()` runs only when due, skips within the one-hour success cadence, and retries after a bounded failure cooldown.
- `FreeDownloadQuotaRepository.prune_windows()` retries only SQLite locked/busy errors when no caller transaction is active; each retry is a fresh transaction.
- File, directory, and batch downloads return canonical `503 service_unavailable` when the quota store cannot safely decide, and prepared ZIP files are removed before the response.

## Verification
- Focused quota matrix: **22 passed**.
- Final serial Python suite: **4089 passed, 16 skipped, 20 deselected, 2 warnings**, exit code 0.
- Full Ruff, compileall, diff-check, and six repository governance gates passed.

## Boundaries
Status is `fixed-unverified`: no long-running LAN soak, DST/clock correctness proof, cross-process maintenance scheduler, power-loss durability, exactly-once maintenance, or quota preflight/reservation benchmark was performed. Maintenance remains process-local and advisory.
