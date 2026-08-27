# LAN Activity-Log Event-Loop Offload Evidence (2026-08-27)

## Scope
Finding `ACTIVITY-OFFLOAD-53-01`: the auth-offload batch had explicitly left "activity logging on-loop" as a residual — after PBKDF2 moved to `to_thread`, the final `ActivityLog.add` (SQLite INSERT + commit under `db_write_lock`, wired to the real connection) still blocked the event loop on login paths.

## Change
`ActivityLog.add` semantics are unchanged (memory deque ordering, lock, swallow-on-error, event publish). Only the async handler call sites are offloaded:
- `routes/auth.py`: `_record_activity` is now `async` and wraps `to_thread(activity_log.add, ...)`; the three login success paths `await` it (username, password, access-key).
- `routes/shares.py`: share-link creation adds via `await asyncio.to_thread(activity_log.add, ...)`.
- `routes/downloads.py`: `_record_download_route` became async and awaits a `to_thread`-wrapped add (called from both download handlers' `finally`).

## Verification
Behavioral net **259 passed** (login/register/share/quota/download contracts intact); parked-recording regression added to `test_login_share_verify_offload.py` proves the activity add is routed through `to_thread` and the loop stays schedulable during the deferred persist (5 passed in that file). Final serial suite **4117 passed, 16 skipped, 20 deselected, 2 warnings**; static gates green.

## Boundaries
Status `fixed-unverified`. Ordering across concurrent offloaded writes still follows `ActivityLog`'s internal lock (append order), not cross-thread arrival; only the five identified async call sites were converted — no non-async caller exists, and none is claimed.