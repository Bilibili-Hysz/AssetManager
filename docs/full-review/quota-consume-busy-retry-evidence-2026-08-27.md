# Quota Consume SQLite Busy Retry Evidence (2026-08-27)

## Scope
Finding `QUOTA-CONSUME-BUSY-RETRY-47-01`: batch 38 gave `prune_windows` bounded busy retry but left `consume()` single-attempt, so transient lock contention surfaced to routes as a quota-store failure (`503`) instead of resolving after the holder released the write lock.

## Change
`FreeDownloadQuotaRepository.consume()` replays its complete transaction up to `SQLITE_BUSY_RETRY_ATTEMPTS` when no caller transaction wraps it, mirroring `prune_windows`: rollback + bounded backoff between attempts, business exceptions propagate untouched. Each replay is the full idempotent CAS, so no partial state exists between attempts; the route-level `503 fail-closed` contract for non-busy errors is unchanged.

## Verification
- Connection-proxy fault injection: first `SAVEPOINT free_download_quota_consume` raising `database is locked` resolves on attempt two (allowed=True, used=1); inside a caller `BEGIN` no replay occurs and no row leaks after rollback. Existing CAS/thread-pool single-slot regressions stay green. Quota matrix: **24 passed**. Full serial suite: **4097 passed, 16 skipped, 20 deselected, 2 warnings**.

## Boundaries
Status is `fixed-unverified`. Retry covers SQLite lock contention only, not multi-process scheduler fairness, WAL checkpoint stalls, or crash-recovery timing; no power-loss or exactly-once semantics are claimed — repeated retries may still exhaust and surface as `503`.
